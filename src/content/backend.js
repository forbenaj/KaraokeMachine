function startKaraokize() {
  if (processing || !cacheCheckComplete || !karaokizeAvailable) return;

  const lyricsTiming = prepareKaraokizeLyricsTiming();
  const jobId = crypto.randomUUID();
  activeJobId = jobId;
  activeJobStemsReady = false;
  setMonitorActivity(jobId, "audio", "Connecting...");
  setProcessing(true);
  setProcessStatus("Connecting to the downloader...", "busy");

  chrome.runtime.sendMessage({
    type: "dkaraoke-karaokize",
    jobId,
    url: location.href,
    title: currentSongTitle(),
    lyricsTiming
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (activeJobId !== jobId) return;
    if (!response?.ok || error) {
      clearMonitorJob(jobId);
      activeJobId = null;
      if (lyricsTiming && timingsJobId === lyricsTiming.jobId) {
        timingsProcessing = false;
        timingsJobId = null;
        updateLyricsProcessButtons();
        setLyricsStatus("Could not start lyric timing because Karaokize failed to start.", "error");
      }
      setProcessing(false);
      setProcessStatus(error || "Could not start the downloader.", "error");
    }
  });
  if (!lyricsTiming) startLyricsExtractionPipeline();
}
