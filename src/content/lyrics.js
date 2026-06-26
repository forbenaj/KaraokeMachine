function ensureLyricsOverlay() {
  const player = document.querySelector("#movie_player");
  if (!player) return null;
  let overlay = document.getElementById(LYRICS_OVERLAY_ID);
  if (overlay?.parentElement !== player) overlay?.remove();
  if (!overlay || overlay.parentElement !== player) {
    overlay = document.createElement("div");
    overlay.id = LYRICS_OVERLAY_ID;
    overlay.setAttribute("aria-live", "off");
    overlay.hidden = true;
    player.appendChild(overlay);
  }
  overlay.dataset.style = lyricsStyle;
  return overlay;
}

function setLyricsStatus(message, state = "idle") {
  const status = document.getElementById(LYRICS_STATUS_ID);
  if (!status) return;
  status.textContent = message;
  status.dataset.state = state;
}

function setLyricsStyle(nextStyle, persist = true) {
  lyricsStyle = nextStyle === "simple" ? "simple" : "arcade";
  const overlay = document.getElementById(LYRICS_OVERLAY_ID);
  if (overlay) overlay.dataset.style = lyricsStyle;
  const selector = document.getElementById(LYRICS_STYLE_ID);
  if (selector) selector.value = lyricsStyle;
  if (persist) chrome.storage.local.set({ dkaraokeLyricsStyle: lyricsStyle });
}

function activeLyricSegment(time) {
  return lyricSegments.find((segment) => time >= segment.start_time - 0.35 && time <= segment.end_time + 0.6) || null;
}

function renderLyricsFrame() {
  lyricAnimationId = null;
  const overlay = ensureLyricsOverlay();
  if (!overlay || !enabled || !lyricsEnabled || !lyricsReady || !syncedVideo) {
    if (overlay) overlay.hidden = true;
    return;
  }

  if (isAdPlaying()) {
    overlay.hidden = true;
    lyricAnimationId = requestAnimationFrame(renderLyricsFrame);
    return;
  }

  const lyricTime = syncedVideo.currentTime + settings.lyricsLatencyMs / 1000;
  const segment = activeLyricSegment(lyricTime);
  if (!segment) {
    overlay.hidden = true;
    renderedLyricSegment = null;
  } else {
    overlay.hidden = false;
    if (renderedLyricSegment !== segment) {
      overlay.replaceChildren(...segment.words.map((word) => {
        const span = document.createElement("span");
        span.textContent = `${word.text} `;
        return span;
      }));
      renderedLyricSegment = segment;
    }
    segment.words.forEach((word, index) => {
      const element = overlay.children[index];
      if (!element) return;
      element.classList.toggle("is-sung", lyricTime >= word.end_time);
      element.classList.toggle("is-current", lyricTime >= word.start_time && lyricTime < word.end_time);
    });
  }
  lyricAnimationId = requestAnimationFrame(renderLyricsFrame);
}

function updateLyricsButton() {
  const button = document.getElementById(LYRICS_ID);
  if (!button) return;
  button.disabled = !lyricsReady;
  button.classList.toggle("is-active", lyricsEnabled && lyricsReady);
  button.setAttribute("aria-pressed", String(lyricsEnabled && lyricsReady));
  button.title = lyricsReady ? `${lyricsEnabled ? "Hide" : "Show"} synchronized lyrics.` : "Add or load lyrics, then Karaokize.";
}

function updateLyricsProcessButtons() {
  const searchButton = document.getElementById(LRCLIB_SEARCH_ID);
  const timingsButton = document.getElementById(EXTRACT_TIMINGS_ID);
  const hasText = Boolean(document.getElementById(LYRICS_TEXT_ID)?.value.trim() || lyricsText.trim());
  if (searchButton) {
    searchButton.disabled = Boolean(lyricsSearchJobId) || timingsProcessing;
    searchButton.textContent = lyricsSearchJobId ? "Searching LRCLIB..." : "Search LRCLIB";
  }
  if (timingsButton) {
    timingsButton.disabled = timingsProcessing || Boolean(lyricsSearchJobId) || !hasText;
    timingsButton.textContent = timingsProcessing ? "Extracting timings..." : "Extract timings";
  }
}
function startLyricsRendering() {
  if (lyricAnimationId === null) lyricAnimationId = requestAnimationFrame(renderLyricsFrame);
}

function stopLyricsRendering() {
  if (lyricAnimationId !== null) cancelAnimationFrame(lyricAnimationId);
  lyricAnimationId = null;
  const overlay = document.getElementById(LYRICS_OVERLAY_ID);
  if (overlay) overlay.hidden = true;
}

function setLyrics(data, updateEditor = true) {
  lyricSegments = Array.isArray(data?.segments) ? data.segments : [];
  lyricsReady = lyricSegments.length > 0;
  if (updateEditor && typeof data?.text === "string") {
    lyricsText = data.text;
    const editor = document.getElementById(LYRICS_TEXT_ID);
    if (editor) editor.value = lyricsText;
  }
  renderedLyricSegment = null;
  updateLyricsButton();
  if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
  else stopLyricsRendering();
}

function toggleLyrics() {
  if (!lyricsReady) return;
  lyricsEnabled = !lyricsEnabled;
  persistPlaybackState();
  updateLyricsButton();
  if (enabled && lyricsEnabled) startLyricsRendering();
  else stopLyricsRendering();
}

function searchLrclibLyrics() {
  const videoId = currentVideoId();
  if (!videoId || lyricsSearchJobId) return;
  const jobId = crypto.randomUUID();
  lyricsSearchJobId = jobId;
  updateLyricsProcessButtons();
  setLyricsStatus("Searching LRCLIB...", "busy");
  chrome.runtime.sendMessage({
    type: "dkaraoke-search-lrclib",
    jobId,
    url: location.href
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (lyricsSearchJobId !== jobId) return;
    if (!response?.ok || error) {
      lyricsSearchJobId = null;
      updateLyricsProcessButtons();
      setLyricsStatus(error || "LRCLIB search failed. You can enter lyrics manually.", "info");
    }
  });
}

function extractLyricsTimings() {
  if (timingsProcessing) return;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value.trim() || "";
  if (!text) {
    setLyricsStatus("Enter or find lyrics before extracting timings.", "info");
    return;
  }
  timingsProcessing = true;
  const jobId = crypto.randomUUID();
  timingsJobId = jobId;
  updateLyricsProcessButtons();
  setProcessing(processing);
  setLyricsStatus("Extracting word timings from vocals...", "busy");
  chrome.runtime.sendMessage({
    type: "dkaraoke-extract-lyrics-timings",
    jobId,
    url: location.href,
    lyricsText: text
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (timingsJobId !== jobId) return;
    if (!response?.ok || error) {
      timingsProcessing = false;
      timingsJobId = null;
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(error || "Could not extract lyric timings.", "error");
    }
  });
}
