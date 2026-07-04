function positionMonitorStar() {
  const frame = document.querySelector(".dkaraoke-monitor-frame");
  const star = frame?.querySelector(".dkaraoke-monitor-star");
  if (!frame || !star) return;
  if (frame.classList.contains("is-monitor-prompt")) {
    star.style.left = "0";
    star.style.top = "0";
    return;
  }
  const bounds = frame.getBoundingClientRect();
  star.style.left = `${bounds.left + bounds.width / 2}px`;
  star.style.top = `${bounds.top + bounds.height / 2}px`;
}

function updatePlaybackMonitor() {
  const monitor = document.getElementById(MONITOR_ID);
  const status = document.getElementById(MONITOR_TEXT_ID);
  const frame = monitor?.closest(".dkaraoke-monitor-frame");
  if (!monitor || !status) return;

  const playing = Boolean(
    enabled
    && syncedVideo
    && !syncedVideo.paused
    && !syncedVideo.ended
    && !syncedVideo.seeking
    && syncedVideo.readyState >= HTMLMediaElement.HAVE_FUTURE_DATA
    && !isAdPlaying()
  );
  const paused = Boolean(
    enabled
    && syncedVideo
    && (syncedVideo.paused || syncedVideo.ended)
    && !syncedVideo.seeking
    && !isAdPlaying()
  );
  const activityItems = Array.from(monitorActivities.values());
  const messages = Array.from(new Set(activityItems.map((item) => item.message).filter(Boolean))).slice(-3);
  const measuredProgress = activityItems
    .map((item) => item.progress)
    .filter(Number.isFinite)
    .slice(-1)[0];
  const hasActivity = messages.length > 0;
  const busy = hasActivity || processing || !cacheCheckComplete;
  const prompt = Boolean(cacheCheckComplete && karaokizeAvailable && !processing && !hasActivity);
  if (!messages.length) {
    if (busy) messages.push(t("loading"));
    else if (prompt) messages.push(t("pressMe"));
    else if (playing) messages.push(t("playing"));
    else if (paused) messages.push(t("pause"));
    else messages.push(t("readyBang"));
  }
  status.textContent = messages.join("; ");
  const monitorState = busy ? "busy" : prompt ? "prompt" : playing ? "playing" : paused ? "paused" : "ready";
  monitor.dataset.count = String(messages.length);
  monitor.dataset.state = monitorState;
  monitor.setAttribute("aria-label", status.textContent);
  monitor.title = prompt
    ? t("pressMeTitle")
    : busy
      ? t("preparationInProgress")
      : t("alreadyPrepared");
  monitor.disabled = busy || !prompt;
  monitor.classList.toggle("is-busy", busy);
  monitor.classList.toggle("is-prompt", prompt);
  monitor.classList.toggle("is-playing", !busy && !prompt && playing);
  monitor.classList.toggle("is-paused", !busy && !prompt && paused);
  monitor.classList.toggle("is-ready", !busy && !prompt && !playing && !paused);
  if (frame) {
    frame.classList.toggle("is-monitor-busy", busy);
    frame.classList.toggle("is-monitor-prompt", prompt);
    frame.classList.toggle("is-monitor-playing", !busy && !prompt && playing);
    frame.classList.toggle("is-monitor-paused", !busy && !prompt && paused);
    frame.classList.toggle("is-monitor-ready", !busy && !prompt && !playing && !paused);
  }
  const hasMeasuredProgress = Number.isFinite(measuredProgress);
  const renderKey = `${busy}:${hasMeasuredProgress}:${messages.join("\u001f")}`;
  let spinner = monitor.querySelector(":scope > .dkaraoke-monitor-spinner");
  if (monitor.dataset.renderKey !== renderKey) {
    const children = [];
    if (busy) {
      spinner = document.createElement("span");
      spinner.className = "dkaraoke-monitor-spinner";
      spinner.setAttribute("aria-hidden", "true");
      children.push(spinner);
    } else {
      spinner = null;
    }
    children.push(...messages.map((message) => {
      const item = document.createElement("span");
      item.className = "dkaraoke-monitor-message";
      item.textContent = message;
      return item;
    }));
    monitor.replaceChildren(...children);
    monitor.dataset.renderKey = renderKey;
  }
  if (spinner) {
    spinner.classList.toggle("is-measured", hasMeasuredProgress);
    if (hasMeasuredProgress) {
      const clampedProgress = Math.max(0, Math.min(100, measuredProgress));
      spinner.style.setProperty("--dk-monitor-progress-angle", `${clampedProgress * 3.6}deg`);
    } else {
      spinner.style.removeProperty("--dk-monitor-progress-angle");
    }
  }
  positionMonitorStar();
}

function setMonitorActivity(jobId, channel, message, progress = null) {
  if (!jobId || !channel) return;
  const key = `${jobId}:${channel}`;
  if (message) monitorActivities.set(key, {
    message,
    progress: Number.isFinite(progress) ? progress : null,
  });
  else monitorActivities.delete(key);
  updatePlaybackMonitor();
}

function clearMonitorJob(jobId) {
  if (!jobId) return;
  for (const key of monitorActivities.keys()) {
    if (key.startsWith(`${jobId}:`)) monitorActivities.delete(key);
  }
  updatePlaybackMonitor();
}

function updateMonitorFromBackend(message) {
  const phase = message.phase || "";
  if (["lyrics", "lyricsLookup"].includes(phase)) {
    if (message.status !== "monitorEnd" && message.message) {
      setLyricsStatus(message.message, message.status === "error" ? "error" : "busy");
    }
    return message.status === "monitorStart" || message.status === "monitorEnd";
  }
  if (message.status === "monitorStart") {
    setMonitorActivity(
      message.jobId,
      phase || "task",
      localizeMessage(message.message || t("processing")),
      message.progress,
    );
    return true;
  }
  if (message.status === "monitorEnd") {
    setMonitorActivity(message.jobId, phase || "task", "");
    return true;
  }
  if (phase === "download") setMonitorActivity(message.jobId, "audio", t("monitorDownloading"), message.progress);
  else if (["convert", "separate"].includes(phase)) setMonitorActivity(message.jobId, "audio", t("monitorExtracting"), message.progress);
  if (message.status === "stemsReady") setMonitorActivity(message.jobId, "audio", "");
  if (["cacheCheck", "complete", "lyrics", "lyricsComplete", "error", "canceled"].includes(message.status)) {
    clearMonitorJob(message.jobId);
  }
  return false;
}
