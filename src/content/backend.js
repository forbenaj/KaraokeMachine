function startKaraokize() {
  if (processing || !cacheCheckComplete || !karaokizeAvailable) return;

  const lyricsTiming = prepareKaraokizeLyricsTiming();
  const jobId = crypto.randomUUID();
  activeJobId = jobId;
  activeJobStemsReady = false;
  setMonitorActivity(jobId, "audio", t("connecting"));
  setProcessing(true);
  setProcessStatus(t("connectingDownloader"), "busy");

  chrome.runtime.sendMessage({
    type: "dkaraoke-karaokize",
    jobId,
    url: location.href,
    title: currentSongTitle(),
    artist: currentSongArtist(),
    lyricsTiming
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (activeJobId !== jobId) return;
    if (!response?.ok || error) {
      recordDiagnostic("error", "karaokize_start_failed", error || "Could not start the downloader.", {
        jobId,
        hasLyricsTiming: Boolean(lyricsTiming),
      });
      clearMonitorJob(jobId);
      activeJobId = null;
      if (lyricsTiming && timingsJobId === lyricsTiming.jobId) {
        timingsProcessing = false;
        timingsJobId = null;
        updateLyricsProcessButtons();
        setLyricsStatus(t("couldNotStartTimingKaraokize"), "error");
      }
      setProcessing(false);
      setProcessStatus(error || t("couldNotStartDownloader"), "error");
    }
  });
  if (!lyricsTiming) startLyricsExtractionPipeline();
}
