(() => {
  const ROOT_CLASS = "dkaraoke-enabled";
  const BUTTON_ID = "dkaraoke-toggle";
  const LOGO_ID = "dkaraoke-logo";
  const MENU_ID = "dkaraoke-menu";
  const LEFT_PANEL_ID = "dkaraoke-left-panel";
  const RIGHT_RAIL_ID = "dkaraoke-right-rail";
  const RIGHT_PANEL_ID = "dkaraoke-right-panel";
  const MONITOR_ID = "dkaraoke-monitor";
  const MONITOR_TEXT_ID = "dkaraoke-monitor-text";
  const STATUS_ID = "dkaraoke-process-status";
  const PROGRESS_ID = "dkaraoke-process-progress";
  const PROGRESS_FILL_ID = "dkaraoke-process-progress-fill";
  const KARAOKIZE_ID = "dkaraoke-karaokize";
  const LYRICS_ID = "dkaraoke-lyrics";
  const LYRICS_TEXT_ID = "dkaraoke-lyrics-text";
  const REFRESH_LYRICS_ID = "dkaraoke-refresh-lyrics";
  const LYRICS_OVERLAY_ID = "dkaraoke-lyrics-overlay";
  const STEMS = ["instrumental", "vocals"];
  // A separate HTMLAudioElement reaches the speakers slightly after YouTube's
  // video renderer. Keep replacement audio modestly ahead to compensate. This
  // is an installation-level calibration value, not a universal browser delay.
  const SYNC_OFFSET_SECONDS = 0.075;
  // Caption timestamps tend to trail the sung consonant slightly. Advance the
  // display clock without modifying the reusable timing data from the backend.
  const LYRICS_OFFSET_SECONDS = 0.075;
  const SYNC_MONITOR_INTERVAL_MS = 250;
  const SOFT_SYNC_THRESHOLD_SECONDS = 0.03;
  const HARD_SYNC_THRESHOLD_SECONDS = 0.15;
  const MAX_RATE_CORRECTION = 0.05;
  const MIN_AUDIO_PLAYBACK_RATE = 0.25;
  const MAX_AUDIO_PLAYBACK_RATE = 4;

  let enabled = false;
  let syncQueued = false;
  let mountAttempts = 0;
  let processing = false;
  let cacheCheckJobId = null;
  let cacheCheckComplete = false;
  let karaokizeAvailable = false;
  let activeJobId = null;
  let activeJobStemsReady = false;
  let customAudio = {};
  let customAudioReady = false;
  let sourceMode = "original";
  let stemEnabled = { instrumental: true, vocals: false };
  let syncedVideo = null;
  let videoEvents = null;
  let adObserver = null;
  let originalMuted = false;
  let adActive = false;
  let playBlocked = false;
  let syncMonitorId = null;
  let customAudioInterruptionTimer = null;
  let lyricsEnabled = true;
  let lyricsReady = false;
  let lyricsText = "";
  let lyricSegments = [];
  let youtubeLyrics = { text: "", segments: [], source: "none" };
  let lyricsFetchJobId = null;
  let lyricsVideoId = "";
  let lyricAnimationId = null;
  let renderedLyricSegment = null;
  let lyricsProcessing = false;
  let lyricsProcessingJobId = null;
  let monitorObserver = null;

  function getYouTubeVideo() {
    return document.querySelector("video.html5-main-video, #movie_player video");
  }

  function currentVideoId() {
    return new URL(location.href).searchParams.get("v") || "";
  }

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
    return overlay;
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

    const lyricTime = syncedVideo.currentTime + LYRICS_OFFSET_SECONDS;
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

  function updateRefreshLyricsButton() {
    const button = document.getElementById(REFRESH_LYRICS_ID);
    if (!button) return;
    const hasText = Boolean(document.getElementById(LYRICS_TEXT_ID)?.value.trim() || lyricsText.trim());
    button.disabled = processing || lyricsProcessing || !hasText;
    button.textContent = lyricsProcessing ? "Refreshing..." : "Refresh lyrics";
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
    updateLyricsButton();
    if (enabled && lyricsEnabled) startLyricsRendering();
    else stopLyricsRendering();
  }

  function fetchYouTubeLyrics() {
    const videoId = currentVideoId();
    if (!videoId || lyricsVideoId === videoId || lyricsFetchJobId) return;
    lyricsVideoId = videoId;
    lyricsFetchJobId = crypto.randomUUID();
    setProcessStatus("Looking for synchronized lyrics...", "busy");
    chrome.runtime.sendMessage({
      type: "dkaraoke-fetch-lyrics",
      jobId: lyricsFetchJobId,
      url: location.href
    }, (response) => {
      const error = chrome.runtime.lastError?.message || response?.error;
      if (!response?.ok || error) {
        lyricsFetchJobId = null;
        setProcessStatus(error || "Could not find online lyrics. You can enter them manually.", "info");
      }
    });
  }

  function refreshLyrics() {
    if (processing || lyricsProcessing) return;
    const text = document.getElementById(LYRICS_TEXT_ID)?.value.trim() || "";
    if (!text) {
      setProcessStatus("Enter lyrics before refreshing their timing.", "info");
      return;
    }
    lyricsProcessing = true;
    lyricsProcessingJobId = crypto.randomUUID();
    updateRefreshLyricsButton();
    setProcessing(processing);
    setProcessStatus("Refreshing word timing...", "busy");
    chrome.runtime.sendMessage({
      type: "dkaraoke-refresh-lyrics",
      jobId: lyricsProcessingJobId,
      url: location.href,
      lyricsText: text
    }, (response) => {
      const error = chrome.runtime.lastError?.message || response?.error;
      if (!response?.ok || error) {
        lyricsProcessing = false;
        lyricsProcessingJobId = null;
        updateRefreshLyricsButton();
        setProcessing(processing);
        setProcessStatus(error || "Could not refresh lyric timing.", "error");
      }
    });
  }

  function isAdPlaying() {
    return document.querySelector("#movie_player")?.classList.contains("ad-showing") || false;
  }

  function updatePlaybackMonitor() {
    const canvas = document.getElementById(MONITOR_ID);
    const status = document.getElementById(MONITOR_TEXT_ID);
    if (!canvas || !status) return;

    const playing = Boolean(
      enabled
      && syncedVideo
      && !syncedVideo.paused
      && !syncedVideo.ended
      && !syncedVideo.seeking
      && syncedVideo.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
      && !isAdPlaying()
    );
    const message = playing ? "playing!" : "wait...";
    status.textContent = message;

    const size = Math.max(1, Math.round(canvas.getBoundingClientRect().width));
    const scale = window.devicePixelRatio || 1;
    const pixelSize = Math.max(1, Math.round(size * scale));
    if (canvas.width !== pixelSize || canvas.height !== pixelSize) {
      canvas.width = pixelSize;
      canvas.height = pixelSize;
    }

    const context = canvas.getContext("2d");
    if (!context) return;
    context.setTransform(scale, 0, 0, scale, 0, 0);
    context.clearRect(0, 0, size, size);
    context.fillStyle = "#ffff00";
    context.fillRect(0, 0, size, size);
    const rayCount = 10;
    for (let index = 0; index < rayCount; index += 1) {
      if (index % 2 === 0) continue;
      const start = (index / rayCount) * Math.PI * 2;
      const end = ((index + 1) / rayCount) * Math.PI * 2;
      context.beginPath();
      context.moveTo(size / 2, size / 2);
      context.arc(size / 2, size / 2, size, start, end);
      context.closePath();
      context.fillStyle = playing ? "#ff00b8" : "#d4d4d4";
      context.fill();
    }
    context.save();
    context.translate(size / 2, size / 2);
    context.rotate(-5 * Math.PI / 180);
    context.textAlign = "center";
    context.textBaseline = "middle";
    context.font = `900 ${Math.max(27, Math.round(size * 0.15))}px Impact, Haettenschweiler, sans-serif`;
    context.lineJoin = "round";
    context.lineWidth = Math.max(4, size * 0.025);
    context.strokeStyle = "#000000";
    context.strokeText(message.toUpperCase(), 0, 0, size * 0.82);
    context.fillStyle = playing ? "#00ffff" : "#ffffff";
    context.shadowColor = playing ? "rgba(255, 255, 0, 0.9)" : "transparent";
    context.shadowBlur = playing ? size * 0.08 : 0;
    context.fillText(message.toUpperCase(), 0, 0, size * 0.82);
    context.restore();
  }

  function setProcessProgress(value = null) {
    const progress = document.getElementById(PROGRESS_ID);
    const fill = document.getElementById(PROGRESS_FILL_ID);
    if (!progress || !fill) return;

    const determinate = Number.isFinite(value);
    const percent = determinate ? Math.max(0, Math.min(100, value)) : 0;
    progress.hidden = !processing;
    progress.classList.toggle("is-indeterminate", processing && !determinate);
    fill.style.width = determinate ? `${percent}%` : "36%";
    if (determinate) {
      progress.setAttribute("aria-valuenow", String(Math.round(percent)));
    } else {
      progress.removeAttribute("aria-valuenow");
    }
  }

  function setProcessStatus(message, state = "idle", progress = null) {
    const status = document.getElementById(STATUS_ID);
    if (!status) return;
    status.textContent = message;
    status.dataset.state = state;
    setProcessProgress(progress);
  }

  function setProcessing(nextProcessing) {
    processing = nextProcessing;
    const button = document.getElementById(KARAOKIZE_ID);
    if (button) {
      button.disabled = processing || lyricsProcessing || !cacheCheckComplete || !karaokizeAvailable;
      button.textContent = processing ? "Karaokizing..." : "Karaokize!";
    }
    setProcessProgress();
    updateRefreshLyricsButton();
  }

  function checkSavedResults() {
    const videoId = currentVideoId();
    if (!videoId || cacheCheckJobId) return;
    cacheCheckComplete = false;
    karaokizeAvailable = false;
    cacheCheckJobId = crypto.randomUUID();
    setProcessing(false);
    setProcessStatus("Checking saved karaoke results...", "busy");
    chrome.runtime.sendMessage({
      type: "dkaraoke-check-cache",
      jobId: cacheCheckJobId,
      url: location.href
    }, (response) => {
      const error = chrome.runtime.lastError?.message || response?.error;
      if (!response?.ok || error) {
        cacheCheckJobId = null;
        cacheCheckComplete = true;
        karaokizeAvailable = true;
        setProcessing(false);
        setProcessStatus(error || "Could not check saved results. Karaokize is still available.", "info");
      }
    });
  }

  function updateStemButtons() {
    for (const stem of STEMS) {
      const button = document.getElementById(`dkaraoke-${stem}`);
      if (!button) continue;
      button.disabled = !customAudioReady;
      button.classList.toggle("is-active", stemEnabled[stem]);
      button.setAttribute("aria-pressed", String(stemEnabled[stem]));
      button.title = customAudioReady
        ? `${stemEnabled[stem] ? "Disable" : "Enable"} ${stem}.`
        : "Karaokize this song to enable separated audio.";
    }
  }

  function restoreYouTubeAudio() {
    if (syncedVideo) syncedVideo.muted = originalMuted;
  }

  function stopSyncMonitor() {
    if (syncMonitorId === null) return;
    clearInterval(syncMonitorId);
    syncMonitorId = null;
  }

  function clearCustomAudioInterruptionTimer() {
    if (customAudioInterruptionTimer === null) return;
    clearTimeout(customAudioInterruptionTimer);
    customAudioInterruptionTimer = null;
  }

  function stopCustomAudio() {
    stopSyncMonitor();
    for (const audio of Object.values(customAudio)) {
      audio.pause();
      audio.playbackRate = 1;
    }
  }

  function activeCustomAudio() {
    if (sourceMode !== "custom") return [];
    return STEMS.filter((stem) => stemEnabled[stem]).map((stem) => customAudio[stem]).filter(Boolean);
  }

  function setSourceMode(nextMode, userInitiated = false) {
    if (nextMode !== "original" && !customAudioReady) {
      setProcessStatus("Karaokize this song before switching audio.", "info");
      return;
    }

    bindVideo();

    if (nextMode === "original") {
      sourceMode = "original";
      stopCustomAudio();
      clearCustomAudioInterruptionTimer();
      restoreYouTubeAudio();
      adActive = false;
      updateStemButtons();
      return;
    }

    if (!syncedVideo) {
      setProcessStatus("YouTube's player is not ready yet.", "error");
      return;
    }

    if (sourceMode === "original") originalMuted = syncedVideo.muted;
    sourceMode = nextMode;
    playBlocked = false;
    syncedVideo.muted = true;
    for (const audio of Object.values(customAudio)) {
      audio.volume = syncedVideo.volume;
      audio.muted = originalMuted;
    }
    updateStemButtons();
    if (nextMode === "silent") {
      stopCustomAudio();
      return;
    }
    syncCustomAudio(true);

    if (!syncedVideo.paused && !isAdPlaying()) {
      playCustomAudio(userInitiated);
    }
  }

  function applyStemSelection(userInitiated = false) {
    const count = STEMS.filter((stem) => stemEnabled[stem]).length;
    setSourceMode(count === 2 ? "original" : count === 1 ? "custom" : "silent", userInitiated);
    const message = count === 2
      ? "Using original YouTube audio."
      : count === 1
        ? `Using synchronized ${stemEnabled.instrumental ? "instrumental" : "vocals"}.`
        : "Both stems are off.";
    setProcessStatus(message, count ? "success" : "info");
  }

  function toggleStem(stem) {
    if (!customAudioReady) return;
    stemEnabled[stem] = !stemEnabled[stem];
    applyStemSelection(true);
  }

  function targetAudioTime() {
    if (!syncedVideo) return 0;
    const target = syncedVideo.currentTime + SYNC_OFFSET_SECONDS;
    const durations = Object.values(customAudio)
      .map((audio) => audio.duration)
      .filter(Number.isFinite);
    if (!durations.length) return Math.max(0, target);
    return Math.max(0, Math.min(target, ...durations));
  }

  function syncCustomAudio(force = false) {
    if (!syncedVideo) return;
    const target = targetAudioTime();
    const baseRate = syncedVideo.playbackRate;
    for (const audio of activeCustomAudio()) {
      if (audio.readyState < 1) continue;
      const drift = audio.currentTime - target;
      const absoluteDrift = Math.abs(drift);
      if (force || absoluteDrift >= HARD_SYNC_THRESHOLD_SECONDS) {
        audio.currentTime = target;
        audio.playbackRate = baseRate;
      } else if (absoluteDrift >= SOFT_SYNC_THRESHOLD_SECONDS) {
        const correction = Math.max(-MAX_RATE_CORRECTION, Math.min(MAX_RATE_CORRECTION, -drift * 0.25));
        audio.playbackRate = Math.max(MIN_AUDIO_PLAYBACK_RATE, Math.min(MAX_AUDIO_PLAYBACK_RATE, baseRate * (1 + correction)));
      } else {
        audio.playbackRate = baseRate;
      }
    }
  }

  function startSyncMonitor() {
    if (syncMonitorId !== null) return;
    syncMonitorId = setInterval(() => {
      if (
        sourceMode !== "custom"
        || adActive
        || !activeCustomAudio().length
        || !syncedVideo
        || syncedVideo.paused
        || syncedVideo.seeking
      ) {
        return;
      }
      syncCustomAudio();
    }, SYNC_MONITOR_INTERVAL_MS);
  }

  function playCustomAudio(userInitiated = false) {
    const activeAudio = activeCustomAudio();
    if (!activeAudio.length || !syncedVideo || isAdPlaying()) return;
    syncCustomAudio(true);
    Promise.all(activeAudio.map((audio) => audio.play()))
      .then(() => {
        if (sourceMode === "custom" && !syncedVideo.paused) {
          startSyncMonitor();
        }
      })
      .catch(() => {
        if (playBlocked) return;
        playBlocked = true;
        stemEnabled = { instrumental: true, vocals: true };
        setSourceMode("original");
        setProcessStatus(
          userInitiated
            ? "The separated audio could not start. Toggle a stem to try again."
            : "Separated audio is ready. Toggle a stem to switch from original audio.",
          "info"
        );
      });
  }

  function handleAdState() {
    updatePlaybackMonitor();
    if (sourceMode === "original" || !customAudioReady || !syncedVideo) return;
    const adNow = isAdPlaying();
    if (adNow) {
      if (!adActive) {
        adActive = true;
        stopCustomAudio();
        restoreYouTubeAudio();
      }
      return;
    }

    if (adActive) {
      adActive = false;
      originalMuted = syncedVideo.muted;
      for (const audio of Object.values(customAudio)) audio.muted = originalMuted;
      syncedVideo.muted = true;
      if (sourceMode === "custom") {
        syncCustomAudio(true);
        if (!syncedVideo.paused) playCustomAudio();
      }
    }
  }

  function bindVideo() {
    const video = getYouTubeVideo();
    if (!video || video === syncedVideo) return Boolean(video);

    if (videoEvents) videoEvents.abort();
    if (adObserver) adObserver.disconnect();
    const preservedOriginalMuted = originalMuted;
    if (syncedVideo && sourceMode !== "original") syncedVideo.muted = originalMuted;

    syncedVideo = video;
    originalMuted = sourceMode !== "original" ? preservedOriginalMuted : video.muted;
    videoEvents = new AbortController();
    const options = { signal: videoEvents.signal };

    video.addEventListener("play", () => {
      playCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("playing", () => {
      playCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("pause", () => {
      stopCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("waiting", () => {
      stopCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("stalled", () => {
      stopCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("seeking", () => {
      stopCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("seeked", () => {
      syncCustomAudio(true);
      if (!video.paused) playCustomAudio();
      updatePlaybackMonitor();
    }, options);
    video.addEventListener("ratechange", () => {
      syncCustomAudio();
    }, options);
    video.addEventListener("volumechange", () => {
      if (sourceMode === "original" || adActive) return;
      for (const audio of Object.values(customAudio)) audio.volume = video.volume;
      if (!video.muted) video.muted = true;
    }, options);
    video.addEventListener("ended", () => {
      stopCustomAudio();
      updatePlaybackMonitor();
    }, options);

    const player = document.querySelector("#movie_player");
    if (player) {
      adObserver = new MutationObserver(handleAdState);
      adObserver.observe(player, { attributes: true, attributeFilter: ["class"] });
    }

    if (sourceMode !== "original") {
      video.muted = true;
      if (sourceMode === "custom") syncCustomAudio(true);
    }
    updatePlaybackMonitor();
    return true;
  }

  function discardCustomAudio() {
    setSourceMode("original");
    clearCustomAudioInterruptionTimer();
    customAudioReady = false;
    for (const audio of Object.values(customAudio)) {
      audio.pause();
      audio.removeAttribute("src");
      audio.load();
      audio.remove();
    }
    customAudio = {};
    updateStemButtons();
  }

  function prepareCustomAudio(urls, readyMessage = "Separated audio ready. Synchronizing instrumental...") {
    discardCustomAudio();
    stemEnabled = { instrumental: true, vocals: false };
    const ready = new Set();
    for (const stem of STEMS) {
      const audio = document.createElement("audio");
      customAudio[stem] = audio;
      audio.id = `dkaraoke-audio-${stem}`;
      audio.crossOrigin = "anonymous";
      audio.preload = "auto";
      audio.src = urls[stem];
      audio.hidden = true;
      audio.addEventListener("canplay", () => {
        if (customAudio[stem] !== audio || customAudioReady) return;
        ready.add(stem);
        if (ready.size !== STEMS.length) return;
        customAudioReady = true;
        playBlocked = false;
        updateStemButtons();
        setProcessStatus(readyMessage, "success");
        applyStemSelection();
      });
      audio.addEventListener("waiting", () => {
        if (customAudio[stem] !== audio || sourceMode !== "custom" || !stemEnabled[stem]) return;
        clearCustomAudioInterruptionTimer();
        customAudioInterruptionTimer = setTimeout(() => {
          customAudioInterruptionTimer = null;
          if (customAudio[stem] !== audio || sourceMode !== "custom" || audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA) return;
          stemEnabled = { instrumental: true, vocals: true };
          setSourceMode("original");
          setProcessStatus("Separated audio was interrupted. Using original YouTube audio.", "info");
        }, 750);
      });
      audio.addEventListener("playing", clearCustomAudioInterruptionTimer);
      audio.addEventListener("ended", () => {
        if (customAudio[stem] !== audio || sourceMode !== "custom" || !syncedVideo || syncedVideo.ended) return;
        stemEnabled = { instrumental: true, vocals: true };
        setSourceMode("original");
        setProcessStatus("Separated audio ended early. Using original YouTube audio.", "error");
      });
      audio.addEventListener("error", () => {
        if (customAudio[stem] !== audio) return;
        customAudioReady = false;
        setSourceMode("original");
        updateStemButtons();
        setProcessStatus(`The ${stem} track could not be loaded from the backend.`, "error");
      });
      document.documentElement.appendChild(audio);
      audio.load();
    }
  }

  function startKaraokize() {
    if (processing || lyricsProcessing) return;

    activeJobId = crypto.randomUUID();
    activeJobStemsReady = false;
    setProcessing(true);
    setProcessStatus("Connecting to the downloader...", "busy");

    const title = document.querySelector("ytd-watch-metadata h1")?.textContent?.trim()
      || document.title.replace(/\s*-\s*YouTube\s*$/, "");

    chrome.runtime.sendMessage({
      type: "dkaraoke-karaokize",
      jobId: activeJobId,
      url: location.href,
      title,
      lyricsText: (document.getElementById(LYRICS_TEXT_ID)?.value || "") !== (youtubeLyrics.text || "")
        ? document.getElementById(LYRICS_TEXT_ID)?.value || ""
        : "",
      youtubeLyrics
    }, (response) => {
      const error = chrome.runtime.lastError?.message || response?.error;
      if (!response?.ok || error) {
        activeJobId = null;
        setProcessing(false);
        setProcessStatus(error || "Could not start the downloader.", "error");
      }
    });
  }

  function mountKaraokeMenu() {
    const columns = document.querySelector("ytd-watch-flexy #columns");
    const primary = columns?.querySelector(":scope > #primary");
    if (!columns || !primary) return false;

    let leftPanel = document.getElementById(LEFT_PANEL_ID);
    let rightRail = document.getElementById(RIGHT_RAIL_ID);
    let rightPanel = document.getElementById(RIGHT_PANEL_ID);
    if (leftPanel?.parentElement !== columns) leftPanel?.remove();
    if (rightRail?.parentElement !== columns) {
      const nestedSecondary = rightRail?.querySelector(":scope > #secondary");
      if (nestedSecondary) primary.insertAdjacentElement("afterend", nestedSecondary);
      rightRail?.remove();
    }

    if (!document.getElementById(RIGHT_RAIL_ID)) {
      rightRail = document.createElement("div");
      rightRail.id = RIGHT_RAIL_ID;
      primary.insertAdjacentElement("afterend", rightRail);
    }

    if (rightPanel?.parentElement !== rightRail) rightPanel?.remove();

    if (!document.getElementById(LEFT_PANEL_ID)) {
      leftPanel = document.createElement("aside");
      leftPanel.id = LEFT_PANEL_ID;
      leftPanel.setAttribute("aria-label", "Karaoke playback controls");

      const monitor = document.createElement("div");
      monitor.className = "dkaraoke-monitor-frame";
      const canvas = document.createElement("canvas");
      canvas.id = MONITOR_ID;
      canvas.setAttribute("aria-hidden", "true");
      const monitorText = document.createElement("span");
      monitorText.id = MONITOR_TEXT_ID;
      monitorText.className = "dkaraoke-visually-hidden";
      monitorText.setAttribute("role", "status");
      monitorText.setAttribute("aria-live", "polite");
      monitorText.textContent = "wait...";
      monitor.append(canvas, monitorText);
      leftPanel.appendChild(monitor);
      columns.insertBefore(leftPanel, primary);
    }

    if (!document.getElementById(RIGHT_PANEL_ID)) {
      rightPanel = document.createElement("aside");
      rightPanel.id = RIGHT_PANEL_ID;
      rightPanel.setAttribute("aria-label", "Karaoke lyrics editor");
      rightRail.appendChild(rightPanel);
    }

    let menu = document.getElementById(MENU_ID);
    if (menu?.parentElement !== leftPanel) menu?.remove();
    const existingLyricsEditor = document.querySelector(".dkaraoke-lyrics-editor");
    if (existingLyricsEditor && existingLyricsEditor.parentElement !== rightPanel) {
      rightPanel.appendChild(existingLyricsEditor);
    } else if (menu && !existingLyricsEditor) {
      menu.remove();
      menu = null;
    }

    if (!document.getElementById(MENU_ID)) {
      menu = document.createElement("section");
      menu.id = MENU_ID;
      menu.setAttribute("aria-label", "Karaoke controls");

      const header = document.createElement("div");
      header.className = "dkaraoke-menu-header";
      header.innerHTML = "<strong>Karaoke studio</strong><span>Audio preparation</span>";

      const instruments = document.createElement("div");
      instruments.className = "dkaraoke-instruments";
      instruments.setAttribute("aria-label", "Separated audio tracks");

      for (const stem of STEMS) {
        const toggle = document.createElement("button");
        toggle.id = `dkaraoke-${stem}`;
        toggle.type = "button";
        toggle.textContent = stem === "vocals" ? "Voice" : "Instrumental";
        toggle.disabled = true;
        toggle.addEventListener("click", () => toggleStem(stem));
        instruments.appendChild(toggle);
      }

      const lyricsToggle = document.createElement("button");
      lyricsToggle.id = LYRICS_ID;
      lyricsToggle.type = "button";
      lyricsToggle.textContent = "Lyrics";
      lyricsToggle.disabled = true;
      lyricsToggle.addEventListener("click", toggleLyrics);
      instruments.appendChild(lyricsToggle);

      const lyricsEditor = document.createElement("div");
      lyricsEditor.className = "dkaraoke-lyrics-editor";
      const lyricsHeading = document.createElement("div");
      lyricsHeading.className = "dkaraoke-lyrics-heading";
      const lyricsLabel = document.createElement("label");
      lyricsLabel.htmlFor = LYRICS_TEXT_ID;
      lyricsLabel.innerHTML = "Lyrics <small>Edit, then refresh timing</small>";
      const refreshButton = document.createElement("button");
      refreshButton.id = REFRESH_LYRICS_ID;
      refreshButton.type = "button";
      refreshButton.textContent = "Refresh lyrics";
      refreshButton.addEventListener("click", refreshLyrics);
      lyricsHeading.append(lyricsLabel, refreshButton);
      const lyricsTextarea = document.createElement("textarea");
      lyricsTextarea.id = LYRICS_TEXT_ID;
      lyricsTextarea.placeholder = "YouTube or LRCLIB lyrics will appear here when available. You can also paste or type lyrics.";
      lyricsTextarea.value = lyricsText;
      lyricsTextarea.addEventListener("input", () => {
        lyricsText = lyricsTextarea.value;
        updateRefreshLyricsButton();
      });
      lyricsEditor.append(lyricsHeading, lyricsTextarea);

      const actionRow = document.createElement("div");
      actionRow.className = "dkaraoke-action-row";

      const status = document.createElement("p");
      status.id = STATUS_ID;
      status.dataset.state = "idle";
      status.setAttribute("aria-live", "polite");
      status.textContent = "Ready to prepare this song.";

      const statusStack = document.createElement("div");
      statusStack.className = "dkaraoke-status-stack";

      const progress = document.createElement("div");
      progress.id = PROGRESS_ID;
      progress.hidden = true;
      progress.setAttribute("role", "progressbar");
      progress.setAttribute("aria-label", "Karaokize progress");
      progress.setAttribute("aria-valuemin", "0");
      progress.setAttribute("aria-valuemax", "100");

      const progressFill = document.createElement("span");
      progressFill.id = PROGRESS_FILL_ID;
      progress.appendChild(progressFill);
      statusStack.append(status, progress);

      const karaokize = document.createElement("button");
      karaokize.id = KARAOKIZE_ID;
      karaokize.type = "button";
      karaokize.textContent = "Karaokize!";
      karaokize.addEventListener("click", startKaraokize);

      actionRow.append(statusStack, karaokize);
      menu.append(header, instruments, actionRow);
      leftPanel.appendChild(menu);
      rightPanel.appendChild(lyricsEditor);
    }

    if (monitorObserver) monitorObserver.disconnect();
    monitorObserver = new ResizeObserver(updatePlaybackMonitor);
    monitorObserver.observe(document.getElementById(MONITOR_ID));
    updateWorkspaceLayout();
    updatePlaybackMonitor();

    setProcessing(processing);
    updateStemButtons();
    updateLyricsButton();
    updateRefreshLyricsButton();
    checkSavedResults();
    return true;
  }

  function updateWorkspaceLayout() {
    const columns = document.querySelector("ytd-watch-flexy #columns");
    const primary = columns?.querySelector(":scope > #primary");
    const rightRail = columns?.querySelector(`:scope > #${RIGHT_RAIL_ID}`);
    const secondary = columns?.querySelector(":scope > #secondary")
      || rightRail?.querySelector(":scope > #secondary");
    if (!primary || !rightRail || !secondary) return;

    if (enabled) rightRail.appendChild(secondary);
    else primary.insertAdjacentElement("afterend", secondary);
  }

  function applyState() {
    document.documentElement.classList.toggle(ROOT_CLASS, enabled);

    const button = document.getElementById(BUTTON_ID);
    if (button) {
      button.classList.toggle("is-active", enabled);
      button.setAttribute("aria-pressed", String(enabled));
      button.title = enabled ? "Close Karaoke mode" : "Open Karaoke mode";
    }

    if (!enabled) {
      setSourceMode("original");
      stopLyricsRendering();
    } else if (customAudioReady) {
      applyStemSelection();
    }
    if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
    updateWorkspaceLayout();
    requestAnimationFrame(() => {
      updatePlaybackMonitor();
      window.dispatchEvent(new Event("resize"));
    });
  }

  function toggleMode() {
    enabled = !enabled;
    applyState();
    chrome.storage.local.set({ dkaraokeEnabled: enabled });
  }

  function mountControls() {
    const start = document.querySelector("ytd-masthead #start");
    if (!start) return false;

    const youtubeLogo = Array.from(start.children).find((element) =>
      element.matches?.("ytd-topbar-logo-renderer#logo")
    );
    if (!youtubeLogo) return false;

    let button = document.getElementById(BUTTON_ID);
    if (!button) {
      button = document.createElement("button");
      button.id = BUTTON_ID;
      button.type = "button";
      button.textContent = "K";
      button.setAttribute("aria-label", "Toggle Karaoke mode");
      button.addEventListener("click", toggleMode);
      youtubeLogo.insertAdjacentElement("afterend", button);
    }

    mountKaraokeMenu();
    bindVideo();
    applyState();
    return true;
  }

  function queueMount() {
    if (syncQueued) return;
    syncQueued = true;
    requestAnimationFrame(() => {
      syncQueued = false;
      if (mountControls()) {
        mountAttempts = 0;
      } else if (mountAttempts < 20) {
        mountAttempts += 1;
        setTimeout(queueMount, 250);
      }
    });
  }

  function remountAfterNavigation() {
    processing = false;
    cacheCheckJobId = null;
    cacheCheckComplete = false;
    karaokizeAvailable = false;
    activeJobId = null;
    activeJobStemsReady = false;
    discardCustomAudio();
    lyricsFetchJobId = null;
    lyricsProcessing = false;
    lyricsProcessingJobId = null;
    lyricsVideoId = "";
    lyricsText = "";
    youtubeLyrics = { text: "", segments: [], source: "none" };
    setLyrics(youtubeLyrics);
    setProcessStatus("Checking saved karaoke results...", "busy");
    mountAttempts = 0;
    queueMount();
  }

  chrome.storage.local.get({ dkaraokeEnabled: false }, (result) => {
    enabled = result.dkaraokeEnabled;
    applyState();
    queueMount();
  });

  document.addEventListener("yt-navigate-finish", remountAfterNavigation);
  document.addEventListener("visibilitychange", () => {
    if (
      document.visibilityState === "visible"
      && sourceMode === "custom"
      && syncedVideo
      && !syncedVideo.paused
    ) {
      syncCustomAudio(true);
    }
  });

  chrome.runtime.onMessage.addListener((message) => {
    if (message?.type !== "dkaraoke-status") return;
    if (cacheCheckJobId && message.jobId === cacheCheckJobId) {
      if (message.status === "cacheCheck") {
        cacheCheckJobId = null;
        cacheCheckComplete = true;
        karaokizeAvailable = !(message.hasLyrics && message.hasStems);
        if (message.lyrics?.text) {
          lyricsText = message.lyrics.text;
          youtubeLyrics = message.lyrics;
          setLyrics(message.lyrics);
        }
        if (message.hasStems && message.instrumentalUrl && message.vocalsUrl) {
          prepareCustomAudio(
            { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
            "Cached instrumental ready."
          );
        } else {
          setProcessStatus(
            message.hasLyrics ? "Saved lyrics ready. Karaokize to prepare audio." : "Karaokize to prepare this song.",
            message.hasLyrics ? "success" : "idle"
          );
        }
        setProcessing(false);
      } else if (message.status === "error") {
        cacheCheckJobId = null;
        cacheCheckComplete = true;
        karaokizeAvailable = true;
        setProcessing(false);
        setProcessStatus(message.message || "Could not check saved results. Karaokize is still available.", "info");
      }
      return;
    }
    if (lyricsProcessingJobId && message.jobId === lyricsProcessingJobId) {
      if (message.status === "lyricsComplete") {
        lyricsProcessing = false;
        lyricsProcessingJobId = null;
        setLyrics(message.lyrics || { text: lyricsText, segments: [], source: "manual" });
        updateRefreshLyricsButton();
        setProcessing(processing);
        setProcessStatus(message.message || "Lyrics timing refreshed.", "success");
      } else if (message.status === "error") {
        lyricsProcessing = false;
        lyricsProcessingJobId = null;
        updateRefreshLyricsButton();
        setProcessing(processing);
        setProcessStatus(message.message || "Could not refresh lyric timing.", "error");
      } else {
        setProcessStatus(message.message || "Refreshing word timing...", "busy", message.progress);
      }
      return;
    }
    if (lyricsFetchJobId && message.jobId === lyricsFetchJobId) {
      if (message.status === "lyrics") {
        lyricsFetchJobId = null;
        youtubeLyrics = message.lyrics || { text: "", segments: [], source: "none" };
        lyricsText = youtubeLyrics.text || "";
        setLyrics(youtubeLyrics);
        updateRefreshLyricsButton();
        setProcessStatus(
          youtubeLyrics.segments?.length ? (message.message || "Synchronized lyrics loaded.") : "No synchronized lyrics found. You can enter them manually.",
          youtubeLyrics.segments?.length ? "success" : "info"
        );
      } else if (message.status === "error") {
        lyricsFetchJobId = null;
        setProcessStatus(message.message || "No online lyrics found. You can enter them manually.", "info");
      }
      return;
    }
    if (!activeJobId || message.jobId !== activeJobId) return;

    if (message.status === "lyricsPreview") {
      if (message.lyrics?.text) {
        lyricsText = message.lyrics.text;
        setLyrics(message.lyrics);
      }
      setProcessStatus(
        message.message || "Lyrics available; refining word timing after separation...",
        message.lyrics?.segments?.length ? "success" : "busy"
      );
    } else if (message.status === "stemsReady") {
      if (!message.instrumentalUrl || !message.vocalsUrl) {
        activeJobId = null;
        setProcessing(false);
        setProcessStatus("The backend did not return both separated audio tracks.", "error");
        return;
      }
      activeJobStemsReady = true;
      prepareCustomAudio(
        { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
        message.cacheHit
          ? "Cached separated audio ready; refining lyrics..."
          : "Separated audio ready; refining lyrics..."
      );
    } else if (message.status === "complete") {
      const hasFinalLyrics = Boolean(message.lyrics?.text && message.lyrics?.segments?.length);
      const hasFinalStems = activeJobStemsReady || Boolean(message.instrumentalUrl && message.vocalsUrl);
      activeJobId = null;
      karaokizeAvailable = !(hasFinalLyrics && hasFinalStems);
      setProcessing(false);
      if (message.lyrics) {
        setLyrics(message.lyrics);
      }
      if (!activeJobStemsReady && message.instrumentalUrl && message.vocalsUrl) {
        prepareCustomAudio(
          { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
          "Separated audio ready. Synchronizing instrumental..."
        );
      } else {
        setProcessStatus(message.message || "Stems and synchronized lyrics ready.", "success");
      }
      activeJobStemsReady = false;
    } else if (message.status === "error") {
      activeJobId = null;
      activeJobStemsReady = false;
      setProcessing(false);
      setProcessStatus(message.message || "Download failed.", "error");
    } else {
      setProcessing(true);
      setProcessStatus(message.message || "Processing...", "busy", message.progress);
    }
  });
})();
