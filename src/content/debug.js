const DEBUG_PROCESS_DEFINITIONS = [
  ["cache", "Cache"],
  ["queue", "Queue"],
  ["karaokize", "Karaokize"],
  ["download", "Download"],
  ["separate", "Separate"],
  ["convert", "Convert"],
  ["lyricsSearch", "LRCLIB"],
  ["lyricsTiming", "Timing"],
  ["audioLoad", "Audio"],
];
const DEBUG_PHASE_KEYS = new Set(["cache", "download", "separate", "convert", "lyricsSearch", "lyricsTiming"]);
const DEBUG_TERMINAL_STATUSES = new Set(["cacheCheck", "complete", "lyrics", "lyricsComplete", "error"]);
const DEBUG_MAX_LOG_ENTRIES = 180;

function debugTimestamp() {
  return new Date().toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function debugProcessLabel(key) {
  return DEBUG_PROCESS_DEFINITIONS.find(([processKey]) => processKey === key)?.[1] || key || "Event";
}

function isProgressDebugMessage(message) {
  return /\b\d+(?:\.\d+)?%/.test(String(message || ""))
    || /\babout\s+\d/i.test(String(message || ""));
}

function debugProcessKeyForMessage(message) {
  if (!message) return "";
  if (message.status === "cacheCheck" || message.phase === "cache") return "cache";
  if (message.status === "lyrics") return "lyricsSearch";
  if (message.status === "lyricsComplete") return "lyricsTiming";
  if (message.phase === "lyrics") return "lyricsTiming";
  if (message.phase === "lyricsLookup") return "lyricsSearch";
  if (message.phase === "download") return "download";
  if (message.phase === "separate") return "separate";
  if (message.phase === "convert") return "convert";
  if (message.phase === "queue" || message.status === "queued") return "queue";
  if (message.phase === "connect") return "karaokize";
  if (message.status === "stemsReady") return "audioLoad";
  return "";
}

function debugActiveKeys() {
  const keys = new Set();
  for (const [key, jobs] of debugProcessJobs) {
    if (jobs.size) keys.add(key);
  }
  if (cacheCheckJobId || !cacheCheckComplete) keys.add("cache");
  if (queueItems.length) keys.add("queue");
  if (processing || activeJobId) keys.add("karaokize");
  if (lyricsSearchJobId) keys.add("lyricsSearch");
  if (timingsProcessing || timingsJobId) keys.add("lyricsTiming");
  return keys;
}

function renderDebugPanel() {
  if (!settings.debugEnabled) {
    document.getElementById(DEBUG_PANEL_ID)?.remove();
    return;
  }
  const aboveFold = document.querySelector("ytd-watch-metadata #above-the-fold");
  if (!aboveFold) return;

  let panel = document.getElementById(DEBUG_PANEL_ID);
  if (!panel) {
    panel = document.createElement("section");
    panel.id = DEBUG_PANEL_ID;
    panel.setAttribute("aria-label", "DKaraoKe debug log");

    const header = document.createElement("div");
    header.className = "dkaraoke-debug-header";
    const title = document.createElement("strong");
    title.textContent = "DKaraoKe debug";
    const meta = document.createElement("span");
    meta.className = "dkaraoke-debug-meta";
    meta.textContent = "Live process trace";
    header.append(title, meta);

    const indicators = document.createElement("div");
    indicators.id = DEBUG_INDICATORS_ID;
    indicators.className = "dkaraoke-debug-indicators";

    const log = document.createElement("ol");
    log.id = DEBUG_LOG_ID;
    log.className = "dkaraoke-debug-log";

    panel.append(header, indicators, log);
    aboveFold.insertAdjacentElement("afterend", panel);
  } else if (panel.previousElementSibling !== aboveFold) {
    aboveFold.insertAdjacentElement("afterend", panel);
  }

  const active = debugActiveKeys();
  const indicators = panel.querySelector(`#${DEBUG_INDICATORS_ID}`);
  if (indicators) {
    indicators.replaceChildren(...DEBUG_PROCESS_DEFINITIONS.map(([key, label]) => {
      const item = document.createElement("span");
      item.className = "dkaraoke-debug-indicator";
      item.dataset.process = key;
      item.dataset.active = String(active.has(key));
      item.title = `${label}: ${active.has(key) ? "active" : "idle"}`;
      const square = document.createElement("span");
      square.className = "dkaraoke-debug-square";
      const text = document.createElement("span");
      text.textContent = label;
      item.append(square, text);
      return item;
    }));
  }

  const log = panel.querySelector(`#${DEBUG_LOG_ID}`);
  if (log) {
    log.replaceChildren(...debugLogEntries.slice(-DEBUG_MAX_LOG_ENTRIES).map((entry) => {
      const row = document.createElement("li");
      row.dataset.process = entry.process || "event";
      row.dataset.state = entry.state || "info";
      const time = document.createElement("time");
      time.textContent = entry.time;
      const process = document.createElement("strong");
      process.textContent = debugProcessLabel(entry.process);
      const message = document.createElement("span");
      message.textContent = entry.message || "";
      row.append(time, process, message);
      return row;
    }));
    log.scrollTop = log.scrollHeight;
  }
}

function appendDebugLog(process, state, message, details = {}) {
  const signature = [
    process || "event",
    state || "info",
    message || "",
    details.jobId || "",
    details.phase || "",
    Number.isFinite(details.progress) ? Math.round(details.progress) : "",
  ].join("|");
  if (signature === debugLastSignature) return;
  debugLastSignature = signature;
  debugLogEntries.push({
    time: debugTimestamp(),
    process: process || "event",
    state: state || "info",
    message: message || "",
  });
  if (debugLogEntries.length > DEBUG_MAX_LOG_ENTRIES * 2) {
    debugLogEntries = debugLogEntries.slice(-DEBUG_MAX_LOG_ENTRIES);
  }
  renderDebugPanel();
}

function setDebugJobProcess(jobId, process, active, details = {}) {
  if (!process) return;
  let jobs = debugProcessJobs.get(process);
  if (!jobs) {
    jobs = new Set();
    debugProcessJobs.set(process, jobs);
  }
  const wasActive = jobId ? jobs.has(jobId) : jobs.size > 0;
  if (active && jobId) jobs.add(jobId);
  else if (jobId) jobs.delete(jobId);
  else jobs.clear();
  if (details.silent || (active && wasActive)) {
    renderDebugPanel();
  } else if (details.message) {
    appendDebugLog(process, active ? "active" : "idle", details.message, details);
  } else {
    renderDebugPanel();
  }
}

function setDebugExclusiveJobPhase(jobId, process, details = {}) {
  if (!jobId || !process) return;
  const previous = debugCurrentPhaseByJob.get(jobId);
  if (previous && previous !== process) {
    setDebugJobProcess(jobId, previous, false, {
      message: `${debugProcessLabel(previous)} finished.`,
    });
  }
  debugCurrentPhaseByJob.set(jobId, process);
  for (const key of DEBUG_PHASE_KEYS) {
    if (key !== process) setDebugJobProcess(jobId, key, false);
  }
  setDebugJobProcess(jobId, process, true, details);
}

function clearDebugJob(jobId, message = "") {
  if (!jobId) return;
  debugCurrentPhaseByJob.delete(jobId);
  for (const key of DEBUG_PROCESS_DEFINITIONS.map(([process]) => process)) {
    setDebugJobProcess(jobId, key, false);
  }
  if (message) appendDebugLog("karaokize", "idle", message, { jobId });
  renderDebugPanel();
}

function markJobFinished(jobId) {
  if (!jobId) return;
  finishedJobIds.add(jobId);
  if (finishedJobIds.size > 80) {
    finishedJobIds = new Set(Array.from(finishedJobIds).slice(-40));
  }
}

function recordBackendDebug(message) {
  if (!message || typeof message !== "object") return;
  const process = debugProcessKeyForMessage(message);
  const terminal = DEBUG_TERMINAL_STATUSES.has(message.status);
  const details = {
    jobId: message.jobId,
    phase: message.phase || "",
    progress: message.progress,
    message: message.message || message.status || "Backend update",
  };

  if (process && !terminal && message.status !== "stemsReady") {
    const nextDetails = { ...details, silent: message.status === "progress" };
    if (DEBUG_PHASE_KEYS.has(process)) setDebugExclusiveJobPhase(message.jobId, process, nextDetails);
    else setDebugJobProcess(message.jobId, process, true, nextDetails);
  } else if (process) {
    appendDebugLog(process, terminal ? "done" : "info", details.message, details);
  }

  if (message.status === "stemsReady") {
    setDebugJobProcess(message.jobId, "download", false);
    setDebugJobProcess(message.jobId, "separate", false);
    setDebugJobProcess(message.jobId, "convert", false);
    setDebugJobProcess(message.jobId, "audioLoad", true, details);
  }

  if (terminal) {
    if (!process) appendDebugLog("karaokize", "done", details.message, details);
    markJobFinished(message.jobId);
    clearDebugJob(message.jobId);
  } else {
    renderDebugPanel();
  }
}

function recordQueueDebug(nextItems) {
  const queueDebugMessage = (item) => {
    if (!item) return "Queue updated";
    if (item.status === "queued") return `Queued: ${item.title || "YouTube song"}`;
    if (item.phase === "download") return `Running download: ${item.title || "YouTube song"}`;
    if (item.phase === "separate") return `Running separation: ${item.title || "YouTube song"}`;
    if (item.phase === "convert") return `Running conversion: ${item.title || "YouTube song"}`;
    if (item.phase === "connect") return `Connecting: ${item.title || "YouTube song"}`;
    return `${item.status || "running"}: ${item.title || "YouTube song"}`;
  };
  const signature = (nextItems || [])
    .map((item) => `${item.jobId}:${item.status}:${item.phase}:${item.position || ""}:${item.count || ""}`)
    .join(",");
  if (signature && signature !== debugQueueSignature) {
    const current = nextItems[0];
    appendDebugLog(
      "queue",
      nextItems.length ? "active" : "idle",
      nextItems.length ? queueDebugMessage(current) : "Queue empty",
    );
  }
  if (!signature && debugQueueSignature) appendDebugLog("queue", "idle", "Queue empty");
  debugQueueSignature = signature;
  renderDebugPanel();
}
