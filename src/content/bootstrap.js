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
    updateQueueUI(message.queue || [], message.processedSongs || []);
    return;
  }
  if (message?.type !== "dkaraoke-status") return;
  recordBackendDebug(message);
  if (message.status === "error") {
    showFailureNotification(message.message || "Backend reported an error.");
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
      updateLyricFiles(message.lyricFiles || [], message.activeLyricsFileId || "");
      if (message.lyrics?.text) {
        lyricsText = message.lyrics.text;
        youtubeLyrics = message.lyrics;
        setLyrics(message.lyrics);
        setLyricsStatus(
          message.lyrics.segments?.length
            ? t("savedLyricsSyncedReady")
            : t("savedLyricsTextReady"),
          message.lyrics.segments?.length ? "success" : "info"
        );
      }
      if (message.hasStems && message.instrumentalUrl && message.vocalsUrl) {
        prepareCustomAudio(
          { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
          t("cachedInstrumentalReady")
        );
      } else {
        setProcessStatus(
          message.hasLyrics ? t("savedLyricsReadyPrepareAudio") : t("prepareAudio"),
          message.hasLyrics ? "success" : "idle"
        );
      }
      setProcessing(false);
    } else if (message.status === "error") {
      cacheCheckJobId = null;
      cacheCheckComplete = true;
      karaokizeAvailable = true;
      setProcessing(false);
      setProcessStatus(message.message || t("cacheCheckFailedStillAvailable"), "info");
    }
    return;
  }
  if (timingsJobId && message.jobId === timingsJobId) {
    if (message.status === "lyricsPreview") {
      if (message.lyrics?.text) {
        lyricsText = message.lyrics.text;
        updateLyricFiles(message.lyricFiles || lyricFiles, message.activeLyricsFileId || activeLyricsFileId);
        setLyrics(message.lyrics);
      }
      updateLyricsProcessButtons();
      setLyricsStatus(
        message.message || t("lyricsAvailableRefining"),
        message.lyrics?.segments?.length ? "success" : "busy"
      );
    } else if (message.status === "lyricsComplete") {
      timingsProcessing = false;
      timingsJobId = null;
      updateLyricFiles(
        message.lyricFiles || lyricFiles,
        message.activeLyricsFileId || (normalizeTimingMethod(settings.timingExtractionMethod) === "silero-vad" ? "silero" : "ctc"),
      );
      setLyrics(message.lyrics || { text: lyricsText, segments: [], source: "manual" });
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(message.message || t("lyricsTimingsExtracted"), "success");
    } else if (message.status === "error") {
      timingsProcessing = false;
      timingsJobId = null;
      autoExtractAfterSearch = false;
      updateLyricsProcessButtons();
      setProcessing(processing);
      setLyricsStatus(message.message || t("couldNotExtractTimings"), "error");
    } else {
      setLyricsStatus(message.message || t("extractingTimings"), "busy");
    }
    return;
  }
  if (lyricsSearchJobId && message.jobId === lyricsSearchJobId) {
    if (message.status === "lyrics") {
      lyricsSearchJobId = null;
      youtubeLyrics = message.lyrics || { text: "", segments: [], source: "none" };
      updateLyricFiles(message.lyricFiles || lyricFiles, message.activeLyricsFileId || (youtubeLyrics.text ? "lrclib" : ""));
      lyricsText = youtubeLyrics.text || "";
      setLyrics(youtubeLyrics);
      updateLyricsProcessButtons();
      setLyricsStatus(
        youtubeLyrics.text ? (message.message || t("lrclibLyricsLoaded")) : t("lrclibNoReliableMatch"),
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
      setLyricsStatus(message.message || t("lrclibSearchFailedManual"), "info");
    }
    return;
  }
  if (lyricFileJobId && message.jobId === lyricFileJobId) {
    lyricFileJobId = null;
    if (
      message.status === "lyricFileLoaded"
      || message.status === "lyricFileSaved"
      || message.status === "lyricFileCreated"
    ) {
      updateLyricFiles(message.lyricFiles || lyricFiles, message.activeLyricsFileId || activeLyricsFileId);
      if (message.lyrics) setLyrics(message.lyrics);
      updateLyricsProcessButtons();
      setLyricsStatus(
        message.droppedTimings ? t("lyricsSavedTimingsCleared") : (message.message || t("lyricsFileLoaded")),
        message.status === "lyricFileSaved" || message.status === "lyricFileCreated" ? "success" : "info",
      );
    } else if (message.status === "lyricFiles") {
      updateLyricFiles(message.lyricFiles || [], activeLyricsFileId);
      updateLyricsProcessButtons();
      setLyricsStatus(message.message || t("lyricsFilesLoaded"), "info");
    } else if (message.status === "error") {
      updateLyricsProcessButtons();
      setLyricsStatus(message.message || t("lyricsFileActionFailed"), "error");
    }
    return;
  }
  if (!activeJobId || message.jobId !== activeJobId) return;

  if (message.status === "lyricsPreview") {
    if (message.lyrics?.text) {
      lyricsText = message.lyrics.text;
      updateLyricFiles(message.lyricFiles || lyricFiles, message.activeLyricsFileId || activeLyricsFileId);
      setLyrics(message.lyrics);
    }
    setLyricsStatus(
      message.message || t("lyricsAvailableRefining"),
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
      setProcessStatus(t("backendMissingTracks"), "error");
      return;
    }
    activeJobStemsReady = true;
    prepareCustomAudio(
      { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
      message.cacheHit
        ? t("cachedSeparatedReady")
        : t("separatedAudioReady")
    );
  } else if (message.status === "complete") {
    const hasFinalStems = activeJobStemsReady || Boolean(message.instrumentalUrl && message.vocalsUrl);
    activeJobId = null;
    karaokizeAvailable = !hasFinalStems;
    setProcessing(false);
    if (message.lyrics) {
      updateLyricFiles(message.lyricFiles || lyricFiles, message.activeLyricsFileId || activeLyricsFileId);
      setLyrics(message.lyrics);
      setLyricsStatus(
        message.lyrics.segments?.length ? t("synchronizedLyricsReady") : t("lyricsLoadedNoTimings"),
        message.lyrics.segments?.length ? "success" : "info"
      );
    }
    if (!activeJobStemsReady && message.instrumentalUrl && message.vocalsUrl) {
      prepareCustomAudio(
        { instrumental: message.instrumentalUrl, vocals: message.vocalsUrl },
        t("separatedAudioReadySync")
      );
    } else {
      setProcessStatus(t("separatedAudioReady"), "success");
    }
    activeJobStemsReady = false;
  } else if (message.status === "canceled") {
    activeJobId = null;
    activeJobStemsReady = false;
    setProcessing(false);
    setProcessStatus(message.message || t("canceled"), "idle");
  } else if (message.status === "error") {
    activeJobId = null;
    activeJobStemsReady = false;
    setProcessing(false);
    setProcessStatus(message.message || t("downloadFailed"), "error");
  } else {
    setProcessing(true);
    if (["lyrics", "lyricsLookup"].includes(message.phase)) {
      setLyricsStatus(message.message || t("processingLyrics"), "busy");
    } else {
      setProcessStatus(message.message || t("processing"), "busy", message.progress);
    }
  }
});
