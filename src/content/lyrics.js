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

function compactLyricsProcessText(message, state = "idle") {
  const text = String(localizeMessage(message) || "").toLowerCase();
  if (state === "error" || /\b(error|failed|cannot|could not|timed out|missing)\b/.test(text)) return "Error";
  if (/\b(no reliable match|no lyrics|not found)\b/.test(text) || /\bno\b.*\bmatch\b/.test(text)) return "No lyrics";
  if (/\b(sav\w*|writ\w*)\b/.test(text) && state !== "busy") return "Saved";
  if (state === "success") return "Ready";
  if (state === "info" && /\b(lyric|lyrics|lrclib)\b/.test(text)) return "Lyrics";
  if (state !== "busy") return "Waiting...";
  if (/\b(search|lrclib)\b/.test(text)) return "Searching...";
  if (/\b(extract|align|timing|detect|refin|vocal)\b/.test(text)) return "Extracting...";
  if (/\b(sav\w*|writ\w*)\b/.test(text)) return "Saving...";
  if (/\b(creat\w*|new)\b/.test(text)) return "Creating...";
  if (/\b(load\w*|read\w*|file|cache|synchroniz\w*)\b/.test(text)) return "Loading...";
  return "Processing...";
}

function updateLyricsIndicator() {
  const editor = document.getElementById(LYRICS_TEXT_ID);
  const indicator = document.getElementById(LYRICS_INDICATOR_ID);
  if (!editor || !indicator) return;
  const state = editor.dataset.processState || "idle";
  indicator.textContent = editor.dataset.processText || "Waiting...";
  indicator.dataset.state = state;
}

function updateLyricsMonitor(message, state = "idle") {
  const localized = localizeMessage(message);
  const processText = compactLyricsProcessText(localized, state);
  const editor = document.getElementById(LYRICS_TEXT_ID);
  if (editor) {
    editor.dataset.processState = state;
    editor.dataset.processText = processText;
    editor.title = localized;
  }
  updateLyricsIndicator();
}

function setLyricsStatus(message, state = "idle") {
  const localized = localizeMessage(message);
  updateLyricsMonitor(localized, state);
  if (state === "error") showFailureNotification(localized);
  if (!isProgressDebugMessage(localized)) {
    appendDebugLog(lyricsSearchJobId ? "lyricsSearch" : "lyricsTiming", state, localized);
  }
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
  button.title = lyricsReady
    ? t(lyricsEnabled ? "hideLyricsTitle" : "showLyricsTitle")
    : t("addLyricsTitle");
}

function updateLyricsProcessButtons() {
  const searchButton = document.getElementById(LRCLIB_SEARCH_ID);
  const timingsButton = document.getElementById(EXTRACT_TIMINGS_ID);
  const saveButton = document.getElementById(LYRICS_SAVE_ID);
  const nameInput = document.getElementById(LYRICS_NAME_ID);
  const newButton = document.getElementById(LYRICS_NEW_FILE_ID);
  const hasText = Boolean(document.getElementById(LYRICS_TEXT_ID)?.value.trim() || lyricsText.trim());
  if (searchButton) {
    searchButton.disabled = Boolean(lyricsSearchJobId) || timingsProcessing || Boolean(lyricFileJobId);
    searchButton.textContent = lyricsSearchJobId ? t("searchingLrclib") : t("searchLrclib");
  }
  if (timingsButton) {
    timingsButton.disabled = timingsProcessing || Boolean(lyricsSearchJobId) || Boolean(lyricFileJobId) || !hasText;
    timingsButton.textContent = timingsProcessing ? t("extractingTimings") : t("extractTimings");
  }
  if (saveButton) {
    saveButton.disabled = Boolean(lyricFileJobId) || !activeLyricsFileId;
    saveButton.textContent = lyricFileJobId ? t("savingLyrics") : t("saveLyrics");
  }
  if (nameInput) {
    nameInput.disabled = Boolean(lyricFileJobId) || !activeLyricsFileId;
  }
  if (newButton) {
    newButton.disabled = Boolean(lyricFileJobId);
    newButton.title = lyricFileJobId ? t("creatingLyricsFile") : "New";
  }
}

function activeLyricFile() {
  return lyricFiles.find((file) => file.id === activeLyricsFileId) || null;
}

function lyricFileLabel(file) {
  if (file?.label) return file.label;
  return file?.label || t("newLyricsFile");
}

function updateLyricsNameField() {
  const input = document.getElementById(LYRICS_NAME_ID);
  if (!input) return;
  const file = activeLyricFile();
  input.value = file ? lyricFileLabel(file) : "";
  input.disabled = Boolean(lyricFileJobId) || !file;
}

function updateLyricFiles(files, activeFileId = activeLyricsFileId) {
  lyricFiles = Array.isArray(files) ? files : [];
  const requestedFileId = activeFileId || "";
  if (requestedFileId && lyricFiles.some((file) => file.id === requestedFileId)) {
    activeLyricsFileId = requestedFileId;
  } else if (!activeLyricsFileId || !lyricFiles.some((file) => file.id === activeLyricsFileId)) {
    activeLyricsFileId = lyricFiles[0]?.id || "";
  }
  updateLyricsNameField();
  renderLyricFileBar();
  updateLyricsProcessButtons();
}

function renderLyricFileBar() {
  const bar = document.getElementById(LYRICS_FILE_BAR_ID);
  if (!bar) return;
  const fileIconUrl = chrome.runtime.getURL("assets/extension/file.svg");
  const buttons = lyricFiles.map((file) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "dkaraoke-lyrics-file-button";
    button.dataset.fileId = file.id || "";
    button.classList.toggle("is-active", file.id === activeLyricsFileId);
    button.title = lyricFileLabel(file);
    button.setAttribute("aria-label", lyricFileLabel(file));
    button.style.setProperty("--dk-file-icon", `url("${fileIconUrl}")`);
    button.addEventListener("click", () => loadLyricFile(file.id));
    const label = document.createElement("span");
    label.className = "dkaraoke-lyrics-file-label";
    label.textContent = lyricFileLabel(file);
    const icon = document.createElement("span");
    icon.className = "dkaraoke-lyrics-file-icon";
    button.append(label, icon);
    return button;
  });
  const newButton = document.createElement("button");
  newButton.id = LYRICS_NEW_FILE_ID;
  newButton.type = "button";
  newButton.className = "dkaraoke-lyrics-file-button dkaraoke-lyrics-file-new";
  newButton.title = "New";
  newButton.setAttribute("aria-label", "New");
  newButton.addEventListener("click", createLyricFile);
  const newLabel = document.createElement("span");
  newLabel.className = "dkaraoke-lyrics-file-label";
  newLabel.textContent = "New";
  newButton.append(newLabel);
  bar.replaceChildren(...buttons, newButton);
  updateLyricsProcessButtons();
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
    if (editor) {
      editor.value = lyricsText;
      updateLyricsIndicator();
    }
  }
  renderedLyricSegment = null;
  renderedClassicSegmentIndex = -1;
  updateLyricsButton();
  if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
  else stopLyricsRendering();
}

function requestLyricFileAction(type, extra = {}, busyMessage = "") {
  const videoId = currentVideoId();
  if (!videoId || lyricFileJobId) return;
  const jobId = crypto.randomUUID();
  lyricFileJobId = jobId;
  updateLyricsProcessButtons();
  if (busyMessage) setLyricsStatus(busyMessage, "busy");
  chrome.runtime.sendMessage({
    type,
    jobId,
    url: location.href,
    ...extra,
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (lyricFileJobId !== jobId) return;
    if (!response?.ok || error) {
      lyricFileJobId = null;
      updateLyricsProcessButtons();
      setLyricsStatus(error || t("lyricsFileActionFailed"), "error");
    }
  });
}

function refreshLyricFiles() {
  requestLyricFileAction("dkaraoke-list-lyric-files", {}, t("lyricsFilesLoaded"));
}

function loadLyricFile(fileId) {
  if (!fileId || fileId === activeLyricsFileId || lyricFileJobId) return;
  requestLyricFileAction("dkaraoke-load-lyric-file", { fileId }, t("lyricsFileLoaded"));
}

function saveActiveLyricFile() {
  if (!activeLyricsFileId || lyricFileJobId) return;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value || "";
  const label = document.getElementById(LYRICS_NAME_ID)?.value || lyricFileLabel(activeLyricFile());
  requestLyricFileAction(
    "dkaraoke-save-lyric-file",
    { fileId: activeLyricsFileId, lyricsText: text, label },
    t("savingLyrics"),
  );
}

function createLyricFile() {
  if (lyricFileJobId) return;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value || lyricsText || "";
  requestLyricFileAction(
    "dkaraoke-create-lyric-file",
    { lyricsText: text, label: "New" },
    t("creatingLyricsFile"),
  );
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
  setDebugJobProcess(jobId, "lyricsSearch", true, { message: t("searchingLrclib") });
  updateLyricsProcessButtons();
  setLyricsStatus(t("searchingLrclib"), "busy");
  chrome.runtime.sendMessage({
    type: "dkaraoke-search-lrclib",
    jobId,
    url: location.href,
    title: currentSongTitle(),
    artist: currentSongArtist(),
    duration: currentVideoDuration(),
    forceRefresh: true
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (lyricsSearchJobId !== jobId) return;
    if (!response?.ok || error) {
      recordDiagnostic("warning", "lrclib_search_start_failed", error || "LRCLIB search could not start.", {
        jobId,
      });
      lyricsSearchJobId = null;
      markJobFinished(jobId);
      clearDebugJob(jobId);
      updateLyricsProcessButtons();
      setLyricsStatus(error || t("lrclibSearchFailedManual"), "info");
    }
  });
}

function extractLyricsTimings() {
  if (timingsProcessing) return;
  const text = document.getElementById(LYRICS_TEXT_ID)?.value.trim() || "";
  if (!text) {
    setLyricsStatus(t("enterLyricsBeforeExtracting"), "info");
    return;
  }
  timingsProcessing = true;
  const jobId = crypto.randomUUID();
  timingsJobId = jobId;
  setDebugJobProcess(jobId, "lyricsTiming", true, {
    message: t("startingTiming"),
  });
  updateLyricsProcessButtons();
  setProcessing(processing);
  const timingMethod = normalizeTimingMethod(settings.timingExtractionMethod);
  const timingSource = normalizeTimingSource(settings.timingExtractionSource);
  const methodLabel = timingMethodLabel(timingMethod);
  const sourceLabel = timingSourceLabel(timingSource);
  setLyricsStatus(t("extractingWith", { method: methodLabel, source: sourceLabel }), "busy");
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
      recordDiagnostic("error", "lyrics_timing_start_failed", error || "Lyric timing extraction could not start.", {
        jobId,
        timingMethod,
        timingSource,
      });
      timingsProcessing = false;
      timingsJobId = null;
      markJobFinished(jobId);
      clearDebugJob(jobId);
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(error || t("couldNotExtractTimings"), "error");
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
  setDebugJobProcess(jobId, "lyricsTiming", true, {
    message: t("queuedTimingWithPrepare"),
  });
  updateLyricsProcessButtons();
  setProcessing(processing);
  const timingMethod = normalizeTimingMethod(settings.timingExtractionMethod);
  const methodLabel = timingMethodLabel(timingMethod);
  const scheduleLabel = timingScheduleLabel(timingSchedule);
  setLyricsStatus(
    text
      ? t("willExtractTimings", { method: methodLabel, schedule: scheduleLabel })
      : t("willFindThenExtract", { method: methodLabel, schedule: scheduleLabel }),
    "busy",
  );
  return {
    jobId,
    lyricsText: text,
    timingMethod,
    timingSource,
    timingSchedule,
    title: currentSongTitle(),
    artist: currentSongArtist(),
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
