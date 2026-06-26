function positionMonitorStar() {
  const frame = document.querySelector(".dkaraoke-monitor-frame");
  const star = frame?.querySelector(".dkaraoke-monitor-star");
  if (!frame || !star) return;
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
  const messages = Array.from(new Set(monitorActivities.values())).slice(-3);
  const hasActivity = messages.length > 0;
  const busy = hasActivity || processing || !cacheCheckComplete;
  if (!messages.length) {
    if (busy) messages.push("Loading...");
    else if (playing) messages.push("Playing");
    else if (paused) messages.push("Pause");
    else messages.push("Ready!");
  }
  status.textContent = messages.join("; ");
  monitor.dataset.count = String(messages.length);
  monitor.dataset.state = busy ? "busy" : playing ? "playing" : paused ? "paused" : "ready";
  monitor.classList.toggle("is-playing", !busy && playing);
  monitor.classList.toggle("is-paused", !busy && paused);
  monitor.classList.toggle("is-ready", !busy && !playing && !paused);
  if (frame) {
    frame.classList.toggle("is-monitor-busy", busy);
    frame.classList.toggle("is-monitor-playing", !busy && playing);
    frame.classList.toggle("is-monitor-paused", !busy && paused);
    frame.classList.toggle("is-monitor-ready", !busy && !playing && !paused);
  }
  monitor.replaceChildren(...messages.map((message) => {
    const item = document.createElement("span");
    item.className = "dkaraoke-monitor-message";
    item.textContent = message;
    return item;
  }));
  positionMonitorStar();
}

function setMonitorActivity(jobId, channel, message) {
  if (!jobId || !channel) return;
  const key = `${jobId}:${channel}`;
  if (message) monitorActivities.set(key, message);
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
    setMonitorActivity(message.jobId, phase || "task", message.message || "Processing...");
    return true;
  }
  if (message.status === "monitorEnd") {
    setMonitorActivity(message.jobId, phase || "task", "");
    return true;
  }
  if (phase === "download") setMonitorActivity(message.jobId, "audio", "Downloading...");
  else if (["convert", "separate"].includes(phase)) setMonitorActivity(message.jobId, "audio", "Extracting...");
  if (message.status === "stemsReady") setMonitorActivity(message.jobId, "audio", "");
  if (["cacheCheck", "complete", "lyrics", "lyricsComplete", "error"].includes(message.status)) {
    clearMonitorJob(message.jobId);
  }
  return false;
}
