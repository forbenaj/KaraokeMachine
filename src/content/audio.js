function isAdPlaying() {
  return document.querySelector("#movie_player")?.classList.contains("ad-showing") || false;
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
  persistPlaybackState();
  applyStemSelection(true);
}

function targetAudioTime() {
  if (!syncedVideo) return 0;
  const target = syncedVideo.currentTime + settings.latencyMs / 1000;
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
    .catch((error) => {
      // Seeking can abort an in-flight play() promise. That is a transient
      // player state, not a failure of the selected stem.
      if (error?.name === "AbortError" || syncedVideo?.seeking) return;
      if (playBlocked) return;
      playBlocked = true;
      recordDiagnostic("warning", "custom_audio_play_blocked", error?.message || "Separated audio could not start.", {
        errorName: error?.name || "",
        userInitiated,
        readyState: syncedVideo?.readyState ?? "",
        paused: Boolean(syncedVideo?.paused),
      });
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
    clearCustomAudioInterruptionTimer();
    stopCustomAudio();
    updatePlaybackMonitor();
  }, options);
  video.addEventListener("seeked", () => {
    clearCustomAudioInterruptionTimer();
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
  setDebugJobProcess(activeJobId || "audio-load", "audioLoad", false);
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
  const debugJobId = activeJobId || "audio-load";
  setDebugJobProcess(debugJobId, "audioLoad", true, {
    message: "Loading separated audio in the page...",
  });
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
      setDebugJobProcess(debugJobId, "audioLoad", false, {
        message: "Separated audio loaded in the page.",
      });
      updateStemButtons();
      setProcessStatus(readyMessage, "success");
      applyStemSelection();
    });
    audio.addEventListener("waiting", () => {
      if (customAudio[stem] !== audio || sourceMode !== "custom" || !stemEnabled[stem]) return;
      clearCustomAudioInterruptionTimer();
      customAudioInterruptionTimer = setTimeout(() => {
        customAudioInterruptionTimer = null;
        if (
          customAudio[stem] !== audio
          || sourceMode !== "custom"
          || syncedVideo?.seeking
          || audio.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
        ) return;
        recordDiagnostic("warning", "custom_audio_interrupted", `The ${stem} stem was interrupted.`, {
          stem,
          readyState: audio.readyState,
          networkState: audio.networkState,
        });
        stemEnabled = { instrumental: true, vocals: true };
        setSourceMode("original");
        setProcessStatus("Separated audio was interrupted. Using original YouTube audio.", "info");
      }, 750);
    });
    audio.addEventListener("playing", clearCustomAudioInterruptionTimer);
    audio.addEventListener("ended", () => {
      if (customAudio[stem] !== audio || sourceMode !== "custom" || !syncedVideo || syncedVideo.ended) return;
      recordDiagnostic("error", "custom_audio_ended_early", `The ${stem} stem ended before YouTube ended.`, {
        stem,
        audioDuration: audio.duration,
        audioTime: audio.currentTime,
        videoDuration: syncedVideo.duration,
        videoTime: syncedVideo.currentTime,
      });
      stemEnabled = { instrumental: true, vocals: true };
      setSourceMode("original");
      setProcessStatus("Separated audio ended early. Using original YouTube audio.", "error");
    });
    audio.addEventListener("error", () => {
      if (customAudio[stem] !== audio) return;
      customAudioReady = false;
      recordDiagnostic("error", "custom_audio_load_failed", `The ${stem} track failed to load.`, {
        stem,
        errorCode: audio.error?.code ?? "",
        errorMessage: audio.error?.message || "",
        networkState: audio.networkState,
        readyState: audio.readyState,
      });
      setDebugJobProcess(debugJobId, "audioLoad", false, {
        message: `The ${stem} track failed to load.`,
      });
      setSourceMode("original");
      updateStemButtons();
      setProcessStatus(`The ${stem} track could not be loaded from the backend.`, "error");
    });
    document.documentElement.appendChild(audio);
    audio.load();
  }
}
