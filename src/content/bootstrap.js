chrome.storage.local.get({
  dkaraokeEnabled: false,
  dkaraokeLyricsStyle: DEFAULT_LYRICS_STYLE,
  dkaraokeSettings: DEFAULT_SETTINGS,
  dkaraokePlaybackState: DEFAULT_PLAYBACK_STATE,
}, (result) => {
  enabled = result.dkaraokeEnabled;
  lyricsStyle = normalizeLyricsStyle(result.dkaraokeLyricsStyle);
  settings = normalizeSettings(result.dkaraokeSettings);
  applyPlaybackState(
    settings.defaultStateMode === "reset"
      ? defaultPlaybackState()
      : { ...DEFAULT_PLAYBACK_STATE, ...(result.dkaraokePlaybackState || {}) }
  );
  applyState();
  queueMount();
  refreshQueueState();
});

document.addEventListener("yt-navigate-finish", remountAfterNavigation);
window.addEventListener("scroll", positionMonitorStar, { passive: true });
window.addEventListener("resize", positionMonitorStar);
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
  if (message?.type === "dkaraoke-queue") {
    updateQueueUI(message.queue || []);
    return;
  }
  if (message?.type !== "dkaraoke-status") return;
  recordBackendDebug(message);
  if (message.status === "error") {
    recordDiagnostic("error", "backend_status_error", message.message || "Backend reported an error.", {
      jobId: message.jobId || "",
      phase: message.phase || "",
      cacheHit: message.cacheHit === true,
      hasLyrics: message.hasLyrics === true,
      hasStems: message.hasStems === true,
    });
  }
  if (updateMonitorFromBackend(message)) return;
  if (cacheCheckJobId && message.jobId === cacheCheckJobId) {
    if (message.status === "cacheCheck") {
      cacheCheckJobId = null;
      cacheCheckComplete = true;
      karaokizeAvailable = !message.hasStems;
      if (message.lyrics?.text) {
        lyricsText = message.lyrics.text;
        youtubeLyrics = message.lyrics;
        setLyrics(message.lyrics);
        setLyricsStatus(
          message.lyrics.segments?.length
            ? "Saved synchronized lyrics ready."
            : "Saved lyrics text ready. Extract timings to show it.",
          message.lyrics.segments?.length ? "success" : "info"
        );
      }
      if (message.hasStems && message.instrumentalUrl && message.vocalsUrl) {
        prepareCustomAudio(
          { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
          "Cached instrumental ready."
        );
      } else {
        setProcessStatus(
          message.hasLyrics ? "Saved lyrics ready. Karaokize to prepare audio." : "Karaokize to prepare audio.",
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
  if (timingsJobId && message.jobId === timingsJobId) {
    if (message.status === "lyricsComplete") {
      timingsProcessing = false;
      timingsJobId = null;
      setLyrics(message.lyrics || { text: lyricsText, segments: [], source: "manual" });
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(message.message || "Lyrics timings extracted.", "success");
    } else if (message.status === "error") {
      timingsProcessing = false;
      timingsJobId = null;
      autoExtractAfterSearch = false;
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(message.message || "Could not extract lyric timings.", "error");
    } else {
      setLyricsStatus(message.message || "Extracting timings...", "busy");
    }
    return;
  }
  if (lyricsSearchJobId && message.jobId === lyricsSearchJobId) {
    if (message.status === "lyrics") {
      lyricsSearchJobId = null;
      youtubeLyrics = message.lyrics || { text: "", segments: [], source: "none" };
      lyricsText = youtubeLyrics.text || "";
      setLyrics(youtubeLyrics);
      updateLyricsProcessButtons();
      setLyricsStatus(
        youtubeLyrics.text ? (message.message || "LRCLIB lyrics loaded.") : "LRCLIB found no reliable match. You can enter lyrics manually.",
        youtubeLyrics.segments?.length ? "success" : "info"
      );
      if (autoExtractAfterSearch) {
        autoExtractAfterSearch = false;
        if (youtubeLyrics.text) extractLyricsTimings();
      }
    } else if (message.status === "error") {
      lyricsSearchJobId = null;
      autoExtractAfterSearch = false;
      updateLyricsProcessButtons();
      setLyricsStatus(message.message || "LRCLIB search failed. You can enter lyrics manually.", "info");
    }
    return;
  }
  if (!activeJobId || message.jobId !== activeJobId) return;

  if (message.status === "lyricsPreview") {
    if (message.lyrics?.text) {
      lyricsText = message.lyrics.text;
      setLyrics(message.lyrics);
    }
    setLyricsStatus(
      message.message || "Lyrics available; refining timing after separation...",
      message.lyrics?.segments?.length ? "success" : "busy"
    );
  } else if (message.status === "stemsReady") {
    if (!message.instrumentalUrl || !message.vocalsUrl) {
      recordDiagnostic("error", "stems_ready_missing_urls", "Backend reported stems ready without both audio URLs.", {
        jobId: activeJobId,
        hasInstrumentalUrl: Boolean(message.instrumentalUrl),
        hasVocalsUrl: Boolean(message.vocalsUrl),
      });
      clearMonitorJob(activeJobId);
      activeJobId = null;
      setProcessing(false);
      setProcessStatus("The backend did not return both separated audio tracks.", "error");
      return;
    }
    activeJobStemsReady = true;
    prepareCustomAudio(
      { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
      message.cacheHit
        ? "Cached separated audio ready."
        : "Separated audio ready."
    );
  } else if (message.status === "complete") {
    const hasFinalStems = activeJobStemsReady || Boolean(message.instrumentalUrl && message.vocalsUrl);
    activeJobId = null;
    karaokizeAvailable = !hasFinalStems;
    setProcessing(false);
    if (message.lyrics) {
      setLyrics(message.lyrics);
      setLyricsStatus(
        message.lyrics.segments?.length ? "Synchronized lyrics ready." : "Lyrics loaded without extracted timings.",
        message.lyrics.segments?.length ? "success" : "info"
      );
    }
    if (!activeJobStemsReady && message.instrumentalUrl && message.vocalsUrl) {
      prepareCustomAudio(
        { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
        "Separated audio ready. Synchronizing instrumental..."
      );
    } else {
      setProcessStatus("Separated audio ready.", "success");
    }
    activeJobStemsReady = false;
  } else if (message.status === "error") {
    activeJobId = null;
    activeJobStemsReady = false;
    setProcessing(false);
    setProcessStatus(message.message || "Download failed.", "error");
  } else {
    setProcessing(true);
    if (["lyrics", "lyricsLookup"].includes(message.phase)) {
      setLyricsStatus(message.message || "Processing lyrics...", "busy");
    } else {
      setProcessStatus(message.message || "Processing...", "busy", message.progress);
    }
  }
});
