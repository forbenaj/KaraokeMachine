let renderedClassicSegmentIndex = -1;
const classicGraphemeSegmenter = typeof Intl !== "undefined" && typeof Intl.Segmenter === "function"
  ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
  : null;

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
  lyricsStyle = normalizeLyricsStyle(nextStyle);
  const overlay = document.getElementById(LYRICS_OVERLAY_ID);
  if (overlay) {
    overlay.dataset.style = lyricsStyle;
    overlay.classList.remove("is-classic-advancing");
  }
  const selector = document.getElementById(LYRICS_STYLE_ID);
  if (selector) selector.value = lyricsStyle;
  renderedLyricSegment = null;
  renderedClassicSegmentIndex = -1;
  if (persist) chrome.storage.local.set({ dkaraokeLyricsStyle: lyricsStyle });
}

function activeLyricSegmentIndex(time) {
  const directIndex = lyricSegments.findIndex((segment) =>
    time >= Number(segment.start_time) && time <= Number(segment.end_time)
  );
  if (directIndex >= 0) return directIndex;
  return lyricSegments.findIndex((segment) =>
    time >= Number(segment.start_time) - 0.35 && time <= Number(segment.end_time) + 0.6
  );
}

function activeLyricSegment(time) {
  const index = activeLyricSegmentIndex(time);
  return index >= 0 ? lyricSegments[index] : null;
}

function classicLineText(segment) {
  if (typeof segment?.text === "string" && segment.text.trim()) return segment.text.trim();
  if (Array.isArray(segment?.words)) {
    const text = segment.words.map((word) => word?.text || "").join(" ").trim();
    if (text) return text;
  }
  return "\u00a0";
}

function lyricWords(segment) {
  return Array.isArray(segment?.words) ? segment.words : [];
}

function splitClassicLetters(text) {
  const value = String(text || "");
  if (!value) return [];
  if (classicGraphemeSegmenter) {
    return Array.from(classicGraphemeSegmenter.segment(value), (part) => part.segment);
  }
  return Array.from(value);
}

function getClassicWordSpan(word, fallbackStart, fallbackEnd) {
  const start = Number.isFinite(Number(word?.start_time)) ? Number(word.start_time) : fallbackStart;
  const end = Number.isFinite(Number(word?.end_time)) ? Number(word.end_time) : fallbackEnd;
  return {
    start: Math.max(0, start),
    end: Math.max(Math.max(0, start) + 0.02, end),
  };
}

function buildClassicWord(word, wordIndex) {
  const wordEl = document.createElement("span");
  wordEl.className = "dkaraoke-classic-word";
  wordEl.dataset.wordIndex = String(wordIndex);
  wordEl.dataset.wordText = String(word?.text || "");

  const span = getClassicWordSpan(word, 0, 0.02);
  wordEl.dataset.start = String(span.start);
  wordEl.dataset.end = String(span.end);

  const letters = splitClassicLetters(word?.text || "");
  if (!letters.length) {
    wordEl.textContent = word?.text || "";
    return wordEl;
  }

  const duration = Math.max(0.02, span.end - span.start);
  const step = duration / letters.length;
  letters.forEach((letter, letterIndex) => {
    const letterEl = document.createElement("span");
    letterEl.className = "dkaraoke-classic-letter";
    letterEl.textContent = letter;
    const letterStart = span.start + step * letterIndex;
    const letterEnd = letterIndex === letters.length - 1
      ? span.end
      : Math.min(span.end, letterStart + step);
    letterEl.dataset.start = String(letterStart);
    letterEl.dataset.end = String(letterEnd);
    wordEl.appendChild(letterEl);
  });
  return wordEl;
}

function buildClassicLine(segment, role, segmentIndex) {
  const line = document.createElement("div");
  line.className = `dkaraoke-classic-line is-${role}`;
  line.dataset.role = role;
  line.dataset.segmentIndex = String(segmentIndex);
  const words = lyricWords(segment);
  if (!segment || !words.length) {
    line.classList.add("is-empty");
    line.textContent = classicLineText(segment);
    return line;
  }

  words.forEach((word, index) => {
    line.appendChild(buildClassicWord(word, index));
    if (index < words.length - 1) {
      line.appendChild(document.createTextNode(" "));
    }
  });
  return line;
}

function buildClassicStack(segmentIndex) {
  const stack = document.createElement("div");
  stack.className = "dkaraoke-classic-stack";
  for (const [offset, position] of [[-1, "previous"], [0, "current"], [1, "next"]]) {
    stack.appendChild(buildClassicLine(lyricSegments[segmentIndex + offset], position, segmentIndex + offset));
  }
  return stack;
}

function restartClassicAdvanceAnimation(overlay) {
  overlay.classList.remove("is-classic-advancing");
  void overlay.offsetWidth;
  overlay.classList.add("is-classic-advancing");
}

function updateClassicWordState(wordEl, word, lyricTime, role) {
  if (!wordEl || !word) return;
  const start = Number(wordEl.dataset.start) || 0;
  const end = Number(wordEl.dataset.end) || start + 0.02;
  const wordSung = lyricTime >= end;
  const wordCurrent = lyricTime >= start && lyricTime < end;

  wordEl.classList.toggle("is-sung", role === "previous" || wordSung);
  wordEl.classList.toggle("is-current", role === "current" && wordCurrent);

  const letterEls = wordEl.querySelectorAll(".dkaraoke-classic-letter");
  if (!letterEls.length) return;

  letterEls.forEach((letterEl) => {
    const letterStart = Number(letterEl.dataset.start) || start;
    const letterEnd = Number(letterEl.dataset.end) || end;
    const letterSung = lyricTime >= letterEnd;
    const letterCurrent = lyricTime >= letterStart && lyricTime < letterEnd;

    letterEl.classList.toggle("is-sung", role === "previous" || letterSung);
    letterEl.classList.toggle("is-current", role === "current" && letterCurrent);
  });
}

function updateClassicLineState(lineEl, segment, role, lyricTime) {
  if (!lineEl) return;
  lineEl.classList.toggle("is-previous", role === "previous");
  lineEl.classList.toggle("is-current", role === "current");
  lineEl.classList.toggle("is-next", role === "next");
  lineEl.classList.toggle("is-empty", !segment);
  lineEl.dataset.role = role;
  const words = lyricWords(segment);
  if (!segment || !words.length) return;

  const wordEls = lineEl.querySelectorAll(".dkaraoke-classic-word");
  wordEls.forEach((wordEl, index) => {
    const word = words[index];
    updateClassicWordState(wordEl, word, lyricTime, role);
  });
}

function updateClassicOverlayState(overlay, lyricTime, segmentIndex) {
  const lineEls = overlay.querySelectorAll(".dkaraoke-classic-line");
  if (!lineEls.length) return;
  lineEls.forEach((lineEl, offset) => {
    const role = offset === 0 ? "previous" : offset === 1 ? "current" : "next";
    const segment = lyricSegments[segmentIndex + offset - 1];
    updateClassicLineState(lineEl, segment, role, lyricTime);
  });
}

function renderClassicLyricsFrame(overlay, segmentIndex, lyricTime) {
  const currentSegment = segmentIndex >= 0 ? lyricSegments[segmentIndex] : null;
  if (!currentSegment) {
    overlay.hidden = true;
    renderedClassicSegmentIndex = -1;
    return;
  }

  overlay.hidden = false;
  if (renderedClassicSegmentIndex !== segmentIndex) {
    overlay.replaceChildren(buildClassicStack(segmentIndex));
    renderedClassicSegmentIndex = segmentIndex;
    restartClassicAdvanceAnimation(overlay);
  }
  updateClassicOverlayState(overlay, lyricTime, segmentIndex);
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
  const segmentIndex = activeLyricSegmentIndex(lyricTime);
  const segment = segmentIndex >= 0 ? lyricSegments[segmentIndex] : null;
  if (lyricsStyle === "classic") {
    renderClassicLyricsFrame(overlay, segmentIndex, lyricTime);
  } else {
    if (!segment) {
      overlay.hidden = true;
      renderedLyricSegment = null;
    } else {
      overlay.hidden = false;
      const words = lyricWords(segment);
      if (renderedLyricSegment !== segment) {
        const spans = words.length ? words.map((word) => {
          const span = document.createElement("span");
          span.textContent = `${word.text} `;
          return span;
        }) : [document.createElement("span")];
        if (!words.length) spans[0].textContent = classicLineText(segment);
        overlay.replaceChildren(...spans);
        renderedLyricSegment = segment;
      }
      if (words.length) {
        words.forEach((word, index) => {
          const element = overlay.children[index];
          if (!element) return;
          element.classList.toggle("is-sung", lyricTime >= word.end_time);
          element.classList.toggle("is-current", lyricTime >= word.start_time && lyricTime < word.end_time);
        });
      } else if (overlay.firstElementChild) {
        overlay.firstElementChild.classList.toggle("is-sung", false);
        overlay.firstElementChild.classList.toggle("is-current", true);
      }
    }
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
  if (overlay) {
    overlay.hidden = true;
    overlay.classList.remove("is-classic-advancing");
  }
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
  renderedClassicSegmentIndex = -1;
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
    url: location.href,
    title: currentSongTitle(),
    duration: currentVideoDuration()
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
  const timingMethod = normalizeTimingMethod(settings.timingExtractionMethod);
  const timingSource = normalizeTimingSource(settings.timingExtractionSource);
  const methodLabel = TIMING_METHOD_LABELS[timingMethod] || TIMING_METHOD_LABELS[DEFAULT_TIMING_METHOD];
  const sourceLabel = TIMING_SOURCE_LABELS[timingSource] || TIMING_SOURCE_LABELS[DEFAULT_TIMING_SOURCE];
  setLyricsStatus(`Extracting timings with ${methodLabel} from ${sourceLabel}...`, "busy");
  chrome.runtime.sendMessage({
    type: "dkaraoke-extract-lyrics-timings",
    jobId,
    url: location.href,
    lyricsText: text,
    timingMethod,
    timingSource
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

function prepareKaraokizeLyricsTiming() {
  if (timingsProcessing || lyricsSearchJobId) return null;
  const timingSource = normalizeTimingSource(settings.timingExtractionSource);
  if (timingSource !== "original") return null;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value.trim() || lyricsText.trim();
  const timingSchedule = normalizeTimingSchedule(settings.timingPipelineSchedule);

  timingsProcessing = true;
  const jobId = crypto.randomUUID();
  timingsJobId = jobId;
  updateLyricsProcessButtons();
  setProcessing(processing);
  const timingMethod = normalizeTimingMethod(settings.timingExtractionMethod);
  const methodLabel = TIMING_METHOD_LABELS[timingMethod] || TIMING_METHOD_LABELS[DEFAULT_TIMING_METHOD];
  const scheduleLabel = TIMING_SCHEDULE_LABELS[timingSchedule] || TIMING_SCHEDULE_LABELS[DEFAULT_TIMING_SCHEDULE];
  setLyricsStatus(
    text
      ? `Will extract timings with ${methodLabel} ${scheduleLabel}...`
      : `Will find lyrics, then extract timings with ${methodLabel} ${scheduleLabel}...`,
    "busy",
  );
  return {
    jobId,
    lyricsText: text,
    timingMethod,
    timingSource,
    timingSchedule,
    title: currentSongTitle(),
    duration: currentVideoDuration(),
  };
}

function startLyricsExtractionPipeline() {
  if (timingsProcessing || lyricsSearchJobId) return;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value.trim() || lyricsText.trim();
  if (text) {
    extractLyricsTimings();
    return;
  }
  autoExtractAfterSearch = true;
  searchLrclibLyrics();
}
