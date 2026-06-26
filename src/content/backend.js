function startKaraokize() {
  if (processing) return;

  const jobId = crypto.randomUUID();
  activeJobId = jobId;
  activeJobStemsReady = false;
  setMonitorActivity(jobId, "audio", "Connecting...");
  setProcessing(true);
  setProcessStatus("Connecting to the downloader...", "busy");

  const title = document.querySelector("ytd-watch-metadata h1")?.textContent?.trim()
    || document.title.replace(/\s*-\s*YouTube\s*$/, "");

  chrome.runtime.sendMessage({
    type: "dkaraoke-karaokize",
    jobId,
    url: location.href,
    title
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (activeJobId !== jobId) return;
    if (!response?.ok || error) {
      clearMonitorJob(jobId);
      activeJobId = null;
      setProcessing(false);
      setProcessStatus(error || "Could not start the downloader.", "error");
    }
  });
}
