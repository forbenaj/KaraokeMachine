const HOST_NAME = "com.dkaraoke.downloader";

let nativePort = null;
const jobs = new Map();
const downloadQueue = [];
let activeDownloadJobId = null;
const deferredTimingPosts = new Map();
const DOWNLOAD_TERMINAL_TYPES = new Set(["complete", "error"]);
const DEFAULT_TIMING_METHOD = "ctc";
const TIMING_METHODS = new Set([DEFAULT_TIMING_METHOD, "silero-vad"]);
const DEFAULT_TIMING_SOURCE = "original";
const TIMING_SOURCES = new Set([DEFAULT_TIMING_SOURCE, "vocal-stem"]);
const DEFAULT_TIMING_SCHEDULE = "stems-first";
const TIMING_SCHEDULES = new Set([DEFAULT_TIMING_SCHEDULE, "lyrics-first", "parallel"]);
const jobTimeouts = new Map();
const JOB_TIMEOUT_MS = {
  cache: 2 * 60 * 1000,
  download: 8.5 * 60 * 60 * 1000,
  lyricsSearch: 3 * 60 * 1000,
  lyricsTimings: 10.5 * 60 * 60 * 1000,
};

function clearJobTimeout(jobId) {
  const timeoutId = jobTimeouts.get(jobId);
  if (timeoutId !== undefined) clearTimeout(timeoutId);
  jobTimeouts.delete(jobId);
}

function armJobTimeout(jobId, kind) {
  clearJobTimeout(jobId);
  const delay = JOB_TIMEOUT_MS[kind];
  if (!delay) return;
  jobTimeouts.set(jobId, setTimeout(() => {
    const job = jobs.get(jobId);
    if (!job) return;
    const message = `The ${kind} operation timed out.`;
    if (job.kind !== "download") {
      failJob(jobId, message);
      return;
    }
    const port = nativePort;
    nativePort = null;
    if (port) port.disconnect();
    failAllJobs(`${message} The backend was restarted.`);
  }, delay));
}

function videoIdFromUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    if (url.hostname === "youtu.be") return url.pathname.replace(/^\/+/, "").split("/")[0] || "";
    return url.searchParams.get("v") || "";
  } catch (_error) {
    return "";
  }
}

function normalizeTimingMethod(value) {
  return TIMING_METHODS.has(value) ? value : DEFAULT_TIMING_METHOD;
}

function normalizeTimingSource(value) {
  return TIMING_SOURCES.has(value) ? value : DEFAULT_TIMING_SOURCE;
}

function normalizeTimingSchedule(value) {
  return TIMING_SCHEDULES.has(value) ? value : DEFAULT_TIMING_SCHEDULE;
}

function sendToTab(tabId, payload) {
  if (!tabId) return;
  chrome.tabs.sendMessage(tabId, payload, () => void chrome.runtime.lastError);
}

function queueSnapshot() {
  const orderedJobs = [
    activeDownloadJobId ? jobs.get(activeDownloadJobId) : null,
    ...downloadQueue,
  ].filter(Boolean);
  return orderedJobs.map((job, index) => ({
    jobId: job.jobId,
    videoId: job.videoId || "",
    url: job.url || "",
    title: job.title || "YouTube song",
    status: job.status || (index === 0 ? "running" : "queued"),
    message: job.message || "",
    phase: job.phase || "",
    progress: Number.isFinite(job.progress) ? job.progress : null,
    position: index + 1,
    count: orderedJobs.length,
    createdAt: job.createdAt || 0,
    startedAt: job.startedAt || 0,
  }));
}

function broadcastQueue() {
  const payload = { type: "dkaraoke-queue", queue: queueSnapshot() };
  chrome.tabs.query({ url: ["https://www.youtube.com/*"] }, (tabs) => {
    if (chrome.runtime.lastError) return;
    for (const tab of tabs) sendToTab(tab.id, payload);
  });
}

function updateDownloadJob(jobId, fields) {
  const job = jobs.get(jobId);
  if (!job || job.kind !== "download") return;
  Object.assign(job, fields);
  broadcastQueue();
}

function failAllJobs(message) {
  for (const [jobId, job] of jobs) {
    sendToTab(job.tabId, {
      type: "dkaraoke-status",
      jobId,
      status: "error",
      message
    });
  }
  for (const jobId of jobTimeouts.keys()) clearJobTimeout(jobId);
  jobs.clear();
  deferredTimingPosts.clear();
  downloadQueue.length = 0;
  activeDownloadJobId = null;
  broadcastQueue();
}

function failJob(jobId, message) {
  const job = jobs.get(jobId);
  if (!job) return;
  sendToTab(job.tabId, {
    type: "dkaraoke-status",
    jobId,
    status: "error",
    message
  });
  clearJobTimeout(jobId);
  jobs.delete(jobId);
  deferredTimingPosts.delete(jobId);
}

function flushDeferredTimings(videoId) {
  for (const [jobId, deferred] of deferredTimingPosts) {
    if (deferred.videoId !== videoId) continue;
    deferredTimingPosts.delete(jobId);
    const job = jobs.get(jobId);
    if (!job) continue;
    try {
      ensureNativePort().postMessage(deferred.message);
    } catch (error) {
      failJob(jobId, String(error));
    }
  }
}

function failDeferredTimings(videoId, message) {
  for (const [jobId, deferred] of deferredTimingPosts) {
    if (deferred.videoId === videoId) failJob(jobId, message);
  }
}

function ensureNativePort() {
  if (nativePort) return nativePort;

  nativePort = chrome.runtime.connectNative(HOST_NAME);

  nativePort.onMessage.addListener((hostMessage) => {
    if (!hostMessage || typeof hostMessage !== "object" || typeof hostMessage.jobId !== "string") {
      return;
    }
    const job = jobs.get(hostMessage.jobId);
    if (!job) return;
    const statusMessage = hostMessage.message || "";

    if (job.kind === "download") {
      updateDownloadJob(hostMessage.jobId, {
        status: DOWNLOAD_TERMINAL_TYPES.has(hostMessage.type) ? hostMessage.type : "running",
        message: statusMessage,
        phase: hostMessage.phase || "",
        progress: Number.isFinite(hostMessage.progress) ? hostMessage.progress : null,
      });
    }

    sendToTab(job.tabId, {
      type: "dkaraoke-status",
      jobId: hostMessage.jobId,
      status: hostMessage.type,
      message: statusMessage,
      instrumentalUrl: hostMessage.instrumentalUrl || "",
      vocalsUrl: hostMessage.vocalsUrl || "",
      lyrics: hostMessage.lyrics || null,
      videoId: hostMessage.videoId || "",
      progress: Number.isFinite(hostMessage.progress) ? hostMessage.progress : null,
      phase: hostMessage.phase || "",
      cacheHit: hostMessage.cacheHit === true,
      hasLyrics: hostMessage.hasLyrics === true,
      hasStems: hostMessage.hasStems === true
    });

    if (["cacheCheck", "complete", "lyrics", "lyricsComplete", "error"].includes(hostMessage.type)) {
      clearJobTimeout(hostMessage.jobId);
      jobs.delete(hostMessage.jobId);
      if (job.kind === "download" && activeDownloadJobId === hostMessage.jobId) {
        activeDownloadJobId = null;
        broadcastQueue();
        startNextDownload();
      }
    }
  });

  nativePort.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message;
    nativePort = null;
    failAllJobs(error || "The downloader backend stopped unexpectedly.");
  });

  return nativePort;
}

function postDownloadToHost(job) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    failDeferredTimings(job.videoId, "Karaokize could not start, so lyric timings cannot be extracted.");
    sendToTab(job.tabId, {
      type: "dkaraoke-status",
      jobId: job.jobId,
      status: "error",
      message: String(error)
    });
    jobs.delete(job.jobId);
    clearJobTimeout(job.jobId);
    activeDownloadJobId = null;
    broadcastQueue();
    startNextDownload();
    return;
  }

  collectYouTubeCookies((cookies) => {
    try {
      port.postMessage({
        action: "prepareKaraoke",
        jobId: job.jobId,
        url: job.url,
        title: job.title || "YouTube song",
        cookies,
        lyricsTiming: job.lyricsTiming || null
      });
      job.hostPosted = true;
      flushDeferredTimings(job.videoId);
    } catch (error) {
      failDeferredTimings(job.videoId, "Karaokize could not start, so lyric timings cannot be extracted.");
      sendToTab(job.tabId, {
        type: "dkaraoke-status",
        jobId: job.jobId,
        status: "error",
        message: String(error)
      });
      jobs.delete(job.jobId);
      clearJobTimeout(job.jobId);
      activeDownloadJobId = null;
      broadcastQueue();
      startNextDownload();
    }
  });
}

function startNextDownload() {
  if (activeDownloadJobId || downloadQueue.length === 0) return;
  const job = downloadQueue.shift();
  activeDownloadJobId = job.jobId;
  Object.assign(job, {
    status: "running",
    message: "Connecting to the downloader...",
    phase: "connect",
    progress: null,
    startedAt: Date.now(),
  });
  jobs.set(job.jobId, job);
  armJobTimeout(job.jobId, "download");
  sendToTab(job.tabId, {
    type: "dkaraoke-status",
    jobId: job.jobId,
    status: "status",
    message: job.message,
    phase: job.phase,
    progress: null,
    videoId: job.videoId || "",
  });
  broadcastQueue();
  postDownloadToHost(job);
}

function checkCache(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  jobs.set(message.jobId, { tabId, kind: "cache" });
  armJobTimeout(message.jobId, "cache");
  try {
    port.postMessage({
      action: "checkCache",
      jobId: message.jobId,
      url: message.url
    });
    sendResponse({ ok: true });
  } catch (error) {
    jobs.delete(message.jobId);
    clearJobTimeout(message.jobId);
    sendResponse({ ok: false, error: String(error) });
  }
}

function collectYouTubeCookies(callback) {
  const domains = ["youtube.com", "google.com", "accounts.google.com"];
  const cookiesByKey = new Map();
  let pending = domains.length;

  for (const domain of domains) {
    chrome.cookies.getAll({ domain }, (cookies) => {
      if (!chrome.runtime.lastError) {
        for (const cookie of cookies) {
          const key = `${cookie.domain}\n${cookie.path}\n${cookie.name}`;
          cookiesByKey.set(key, {
            domain: cookie.domain,
            path: cookie.path,
            secure: cookie.secure,
            httpOnly: cookie.httpOnly,
            expirationDate: cookie.expirationDate || 0,
            name: cookie.name,
            value: cookie.value
          });
        }
      }

      pending -= 1;
      if (pending === 0) callback([...cookiesByKey.values()]);
    });
  }
}

function karaokize(message, tabId, sendResponse) {
  const rawLyricsTiming = message.lyricsTiming && typeof message.lyricsTiming === "object"
    ? message.lyricsTiming
    : null;
  const lyricsTiming = rawLyricsTiming
    && typeof rawLyricsTiming.jobId === "string"
    && rawLyricsTiming.jobId
    && !jobs.has(rawLyricsTiming.jobId)
    && normalizeTimingSource(rawLyricsTiming.timingSource) === "original"
    && ((rawLyricsTiming.lyricsText || "").trim() || (rawLyricsTiming.title || "").trim())
      ? {
          jobId: rawLyricsTiming.jobId,
          lyricsText: rawLyricsTiming.lyricsText || "",
          timingMethod: normalizeTimingMethod(rawLyricsTiming.timingMethod),
          timingSource: "original",
          timingSchedule: normalizeTimingSchedule(rawLyricsTiming.timingSchedule),
          title: rawLyricsTiming.title || "",
          duration: Number.isFinite(rawLyricsTiming.duration) ? rawLyricsTiming.duration : null,
        }
      : null;
  const job = {
    kind: "download",
    jobId: message.jobId,
    tabId,
    url: message.url,
    videoId: videoIdFromUrl(message.url),
    title: message.title || "YouTube song",
    status: activeDownloadJobId ? "queued" : "queued",
    message: activeDownloadJobId ? "Queued behind another song." : "Waiting to start...",
    phase: "queue",
    progress: null,
    createdAt: Date.now(),
    startedAt: 0,
    hostPosted: false,
    lyricsTiming,
  };

  jobs.set(job.jobId, job);
  if (lyricsTiming) {
    jobs.set(lyricsTiming.jobId, {
      tabId,
      kind: "lyricsTimings",
      videoId: job.videoId,
      parentJobId: job.jobId,
    });
    armJobTimeout(lyricsTiming.jobId, "lyricsTimings");
  }
  downloadQueue.push(job);
  sendToTab(tabId, {
    type: "dkaraoke-status",
    jobId: job.jobId,
    status: "queued",
    message: job.message,
    phase: job.phase,
    progress: null,
    videoId: job.videoId || "",
  });
  broadcastQueue();
  startNextDownload();
  sendResponse({ ok: true, queued: true });
}

function searchLrclib(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  jobs.set(message.jobId, { tabId, kind: "lyricsSearch" });
  armJobTimeout(message.jobId, "lyricsSearch");
  try {
    port.postMessage({
      action: "searchLrclib",
      jobId: message.jobId,
      url: message.url,
      title: message.title || "",
      duration: Number.isFinite(message.duration) ? message.duration : null
    });
    sendResponse({ ok: true });
  } catch (error) {
    jobs.delete(message.jobId);
    clearJobTimeout(message.jobId);
    sendResponse({ ok: false, error: String(error) });
  }
}

function extractLyricsTimings(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  const videoId = videoIdFromUrl(message.url);
  const timingSource = normalizeTimingSource(message.timingSource);
  jobs.set(message.jobId, { tabId, kind: "lyricsTimings", videoId });
  armJobTimeout(message.jobId, "lyricsTimings");
  const hostMessage = {
    action: "extractLyricsTimings",
    jobId: message.jobId,
    url: message.url,
    lyricsText: message.lyricsText || "",
    timingMethod: normalizeTimingMethod(message.timingMethod),
    timingSource
  };
  const matchingDownload = [...jobs.values()].find((job) =>
    job.kind === "download" && job.videoId === videoId
  );
  if (timingSource === "vocal-stem" && matchingDownload && !matchingDownload.hostPosted) {
    deferredTimingPosts.set(message.jobId, { videoId, message: hostMessage });
    sendResponse({ ok: true, waitingForKaraokize: true });
    return;
  }
  collectYouTubeCookies((cookies) => {
    try {
      port.postMessage({ ...hostMessage, cookies });
      sendResponse({ ok: true });
    } catch (error) {
      jobs.delete(message.jobId);
      clearJobTimeout(message.jobId);
      sendResponse({ ok: false, error: String(error) });
    }
  });
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || typeof message !== "object") return undefined;
  if (
    message.type !== "dkaraoke-get-queue"
    && (typeof message.jobId !== "string" || !message.jobId || jobs.has(message.jobId))
  ) {
    sendResponse({ ok: false, error: "Invalid or duplicate job ID." });
    return undefined;
  }
  if (message?.type === "dkaraoke-check-cache") {
    checkCache(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-karaokize") {
    karaokize(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-search-lrclib") {
    searchLrclib(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-extract-lyrics-timings") {
    extractLyricsTimings(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-get-queue") {
    sendResponse({ ok: true, queue: queueSnapshot() });
    return undefined;
  } else {
    return undefined;
  }
  return true;
});
