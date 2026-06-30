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
  const localized = localizeMessage(message);
  status.textContent = localized;
  status.dataset.state = state;
  if (!isProgressDebugMessage(localized)) appendDebugLog("karaokize", state, localized, { progress });
  setProcessProgress(progress);
}

function setProcessing(nextProcessing) {
  processing = nextProcessing;
  setDebugJobProcess(activeJobId || "karaokize", "karaokize", processing, {
    message: processing ? t("karaokizeActive") : t("karaokizeIdle"),
  });
  setProcessProgress();
  updateLyricsProcessButtons();
  updatePlaybackMonitor();
}

function checkSavedResults() {
  const videoId = currentVideoId();
  if (!videoId || cacheCheckJobId) return;
  cacheCheckComplete = false;
  karaokizeAvailable = false;
  const jobId = crypto.randomUUID();
  cacheCheckJobId = jobId;
  setMonitorActivity(jobId, "cache", t("cacheChecking"));
  setDebugJobProcess(jobId, "cache", true, { message: t("savedChecking") });
  setProcessing(false);
  setProcessStatus(t("savedChecking"), "busy");
  chrome.runtime.sendMessage({
    type: "dkaraoke-check-cache",
    jobId,
    url: location.href
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (cacheCheckJobId !== jobId) return;
    if (!response?.ok || error) {
      recordDiagnostic("warning", "cache_check_failed", error || "Could not check saved results.", {
        jobId,
      });
      clearMonitorJob(jobId);
      cacheCheckJobId = null;
      cacheCheckComplete = true;
      karaokizeAvailable = true;
      setProcessing(false);
      setProcessStatus(error || t("cacheCheckFailedStillAvailable"), "info");
    }
  });
}
