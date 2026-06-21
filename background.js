const HOST_NAME = "com.dkaraoke.downloader";

let nativePort = null;
const jobs = new Map();

function sendToTab(tabId, payload) {
  if (!tabId) return;
  chrome.tabs.sendMessage(tabId, payload, () => void chrome.runtime.lastError);
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
  jobs.clear();
}

function ensureNativePort() {
  if (nativePort) return nativePort;

  nativePort = chrome.runtime.connectNative(HOST_NAME);

  nativePort.onMessage.addListener((hostMessage) => {
    const job = jobs.get(hostMessage.jobId);
    if (!job) return;

    sendToTab(job.tabId, {
      type: "dkaraoke-status",
      jobId: hostMessage.jobId,
      status: hostMessage.type,
      message: hostMessage.message || "",
      filePath: hostMessage.filePath || "",
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
      jobs.delete(hostMessage.jobId);
    }
  });

  nativePort.onDisconnect.addListener(() => {
    const error = chrome.runtime.lastError?.message;
    nativePort = null;
    failAllJobs(error || "The downloader backend stopped unexpectedly.");
  });

  return nativePort;
}

function checkCache(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  jobs.set(message.jobId, { tabId });
  try {
    port.postMessage({
      action: "checkCache",
      jobId: message.jobId,
      url: message.url
    });
    sendResponse({ ok: true });
  } catch (error) {
    jobs.delete(message.jobId);
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
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }

  jobs.set(message.jobId, { tabId });

  collectYouTubeCookies((cookies) => {
    try {
      port.postMessage({
        action: "downloadMp3",
        jobId: message.jobId,
        url: message.url,
          title: message.title || "YouTube song",
          lyricsText: message.lyricsText || "",
          youtubeLyrics: message.youtubeLyrics || {},
          cookies
      });
      sendResponse({ ok: true });
    } catch (error) {
      jobs.delete(message.jobId);
      sendResponse({ ok: false, error: String(error) });
    }
  });
}

function fetchLyrics(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  jobs.set(message.jobId, { tabId });
  collectYouTubeCookies((cookies) => {
    try {
      port.postMessage({
        action: "fetchLyrics",
        jobId: message.jobId,
        url: message.url,
        cookies
      });
      sendResponse({ ok: true });
    } catch (error) {
      jobs.delete(message.jobId);
      sendResponse({ ok: false, error: String(error) });
    }
  });
}

function refreshLyrics(message, tabId, sendResponse) {
  let port;
  try {
    port = ensureNativePort();
  } catch (error) {
    sendResponse({ ok: false, error: String(error) });
    return;
  }
  jobs.set(message.jobId, { tabId });
  try {
    port.postMessage({
      action: "refreshLyrics",
      jobId: message.jobId,
      url: message.url,
      lyricsText: message.lyricsText || ""
    });
    sendResponse({ ok: true });
  } catch (error) {
    jobs.delete(message.jobId);
    sendResponse({ ok: false, error: String(error) });
  }
}

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message?.type === "dkaraoke-check-cache") {
    checkCache(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-karaokize") {
    karaokize(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-fetch-lyrics") {
    fetchLyrics(message, sender.tab?.id, sendResponse);
  } else if (message?.type === "dkaraoke-refresh-lyrics") {
    refreshLyrics(message, sender.tab?.id, sendResponse);
  } else {
    return undefined;
  }
  return true;
});
