function showFailureNotification(message) {
  const localized = localizeMessage(message);
  if (!localized) return;

  let notification = document.getElementById(FAILURE_NOTIFICATION_ID);
  if (!notification) {
    notification = document.createElement("section");
    notification.id = FAILURE_NOTIFICATION_ID;
    notification.setAttribute("role", "alert");

    const header = document.createElement("div");
    header.className = "dkaraoke-failure-header";
    const title = document.createElement("strong");
    title.textContent = "Failure";
    const actions = document.createElement("div");
    actions.className = "dkaraoke-failure-actions";
    const copy = document.createElement("button");
    copy.type = "button";
    copy.textContent = "Copy";
    copy.addEventListener("click", () => {
      const text = notification.querySelector(".dkaraoke-failure-text")?.value || "";
      const copied = navigator.clipboard?.writeText(text);
      if (copied) {
        copied.catch(() => {
          const field = notification.querySelector(".dkaraoke-failure-text");
          field?.select();
          document.execCommand("copy");
        });
        return;
      }
      try {
        const field = notification.querySelector(".dkaraoke-failure-text");
        field?.select();
        document.execCommand("copy");
      } catch (_error) {
        // The textarea remains selectable if the browser blocks clipboard access.
      }
    });
    const close = document.createElement("button");
    close.type = "button";
    close.textContent = "x";
    close.setAttribute("aria-label", "Close");
    close.addEventListener("click", () => notification.remove());
    actions.append(copy, close);
    header.append(title, actions);

    const text = document.createElement("textarea");
    text.className = "dkaraoke-failure-text";
    text.readOnly = true;
    text.rows = 3;

    notification.append(header, text);
    document.body.appendChild(notification);
  }

  const text = notification.querySelector(".dkaraoke-failure-text");
  if (text) text.value = localized;
  notification.hidden = false;
}

function setProcessStatus(message, state = "idle", progress = null) {
  const localized = localizeMessage(message);
  if (state === "error") showFailureNotification(localized);
  if (!isProgressDebugMessage(localized)) appendDebugLog("karaokize", state, localized, { progress });
}

function setProcessing(nextProcessing) {
  processing = nextProcessing;
  setDebugJobProcess(activeJobId || "karaokize", "karaokize", processing, {
    message: processing ? t("karaokizeActive") : t("karaokizeIdle"),
  });
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
