function summarizeQueueItem(item) {
  if (item.status === "queued") return t("queued");
  if (item.status === "canceled") return t("canceled");
  if (Number.isFinite(item.progress) && !/%/.test(item.message || "")) {
    return `${localizeMessage(item.message || t("processing"))} ${Math.round(item.progress)}%`;
  }
  return localizeMessage(item.message || t("processing"));
}

function isQueueButtonSuppressed() {
  return !enabled
    || Boolean(document.fullscreenElement)
    || Boolean(document.querySelector(".html5-video-player.ytp-fullscreen"));
}

function syncQueueButtonVisibility(button) {
  if (!button) return;
  button.hidden = isQueueButtonSuppressed();
}

function ensureQueueVisibilityObserver() {
  if (queueVisibilityObserver) return;
  queueVisibilityObserver = new MutationObserver(() => {
    syncQueueButtonVisibility(document.getElementById(QUEUE_BUTTON_ID));
  });
  queueVisibilityObserver.observe(document.documentElement, {
    attributes: true,
    subtree: true,
    attributeFilter: ["class"],
  });
  document.addEventListener("fullscreenchange", () => {
    syncQueueButtonVisibility(document.getElementById(QUEUE_BUTTON_ID));
  });
  document.addEventListener("webkitfullscreenchange", () => {
    syncQueueButtonVisibility(document.getElementById(QUEUE_BUTTON_ID));
  });
}

function isQueueItemTerminal(item) {
  return ["complete", "error", "canceled"].includes(item?.status);
}

function activeQueueItems(items = queueItems) {
  return (items || []).filter((item) => !isQueueItemTerminal(item) && !finishedJobIds.has(item.jobId));
}

function queueItemUrl(item) {
  if (item?.url) return item.url;
  if (item?.videoId) return `https://www.youtube.com/watch?v=${encodeURIComponent(item.videoId)}`;
  return "";
}

function openQueueItem(item) {
  const url = queueItemUrl(item);
  if (url) window.location.assign(url);
}

function removeQueueItem(item) {
  if (!item?.jobId) return;
  chrome.runtime.sendMessage({
    type: "dkaraoke-remove-queue-item",
    jobId: item.jobId,
  }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (error || !response?.ok) {
      recordDiagnostic("warning", "queue_remove_failed", error || t("queueUpdated"), {
        jobId: item.jobId,
      });
      return;
    }
    updateQueueUI(response.queue || [], response.processedSongs || []);
  });
}

function applyQueueForCurrentVideo() {
  const videoId = currentVideoId();
  const job = activeQueueItems().find((item) =>
    item.videoId
    && item.videoId === videoId
  );
  if (!job) return;
  setDebugJobProcess(job.jobId, "queue", job.status === "queued", {
    silent: true,
  });
  if (activeJobId === job.jobId) return;
  activeJobId = job.jobId;
  activeJobStemsReady = false;
  cacheCheckComplete = true;
  karaokizeAvailable = false;
  setProcessing(true);
  setProcessStatus(summarizeQueueItem(job), "busy", job.progress);
  setMonitorActivity(job.jobId, "audio", job.status === "queued" ? t("monitorQueued") : t("processing"));
}

function renderQueueRow(item) {
  const row = document.createElement("li");
  row.dataset.status = item.status || "queued";

  const openButton = document.createElement("button");
  openButton.type = "button";
  openButton.className = "dkaraoke-queue-open";
  openButton.addEventListener("click", () => openQueueItem(item));

  const itemTitle = document.createElement("span");
  itemTitle.className = "dkaraoke-queue-title";
  itemTitle.textContent = item.title || t("youtubeSong");
  const meta = document.createElement("span");
  meta.className = "dkaraoke-queue-meta";
  meta.textContent = summarizeQueueItem(item);
  openButton.append(itemTitle, meta);

  const remove = document.createElement("button");
  remove.type = "button";
  remove.className = "dkaraoke-queue-remove";
  remove.textContent = "x";
  remove.title = t("remove");
  remove.setAttribute("aria-label", `${t("remove")}: ${item.title || t("youtubeSong")}`);
  remove.addEventListener("click", (event) => {
    event.stopPropagation();
    removeQueueItem(item);
  });

  row.append(openButton, remove);
  return row;
}

function renderQueuePanel(panel) {
  panel.replaceChildren();
  const header = document.createElement("div");
  header.className = "dkaraoke-queue-header";
  const title = document.createElement("strong");
  title.textContent = t("queue");

  const actions = document.createElement("div");
  actions.className = "dkaraoke-queue-header-actions";
  const viewAll = document.createElement("button");
  viewAll.type = "button";
  viewAll.textContent = t("viewAll");
  viewAll.addEventListener("click", () => {
    processedSongsDialogOpen = true;
    renderProcessedSongsDialog();
  });
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = t("close");
  close.addEventListener("click", () => {
    queuePanelOpen = false;
    updateQueueUI();
  });
  actions.append(viewAll, close);
  header.append(title, actions);
  panel.appendChild(header);

  const list = document.createElement("ol");
  list.className = "dkaraoke-queue-list";
  const compactItems = queueItems.slice(0, QUEUE_COMPACT_LIMIT);
  if (compactItems.length) {
    for (const item of compactItems) list.appendChild(renderQueueRow(item));
  } else {
    const empty = document.createElement("li");
    empty.className = "dkaraoke-queue-empty";
    empty.textContent = t("noProcessedSongs");
    list.appendChild(empty);
  }
  panel.appendChild(list);
}

function filteredProcessedSongs() {
  const query = processedSongsSearch.trim().toLowerCase();
  if (!query) return processedSongItems;
  return processedSongItems.filter((item) => {
    return [item.title, item.message, item.videoId]
      .some((value) => String(value || "").toLowerCase().includes(query));
  });
}

function renderProcessedSongsDialog() {
  let dialog = document.getElementById(QUEUE_DIALOG_ID);
  if (!dialog) {
    dialog = document.createElement("dialog");
    dialog.id = QUEUE_DIALOG_ID;
    dialog.addEventListener("close", () => {
      processedSongsDialogOpen = false;
    });
    document.body.appendChild(dialog);
  }

  dialog.replaceChildren();
  const header = document.createElement("div");
  header.className = "dkaraoke-modal-header";
  const title = document.createElement("strong");
  title.textContent = t("processedSongs");
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = t("close");
  close.addEventListener("click", () => dialog.close());
  header.append(title, close);

  const body = document.createElement("div");
  body.className = "dkaraoke-processed-body";
  const search = document.createElement("input");
  search.type = "search";
  search.className = "dkaraoke-processed-search";
  search.placeholder = t("searchSongs");
  search.value = processedSongsSearch;
  search.addEventListener("input", () => {
    processedSongsSearch = search.value;
    renderProcessedSongsDialog();
  });

  const list = document.createElement("ol");
  list.className = "dkaraoke-queue-list dkaraoke-processed-list";
  const matches = filteredProcessedSongs();
  if (matches.length) {
    for (const item of matches) list.appendChild(renderQueueRow(item));
  } else {
    const empty = document.createElement("li");
    empty.className = "dkaraoke-queue-empty";
    empty.textContent = t("noProcessedSongs");
    list.appendChild(empty);
  }
  body.append(search, list);
  dialog.append(header, body);

  if (processedSongsDialogOpen && !dialog.open) dialog.showModal();
  if (document.activeElement !== search) search.focus({ preventScroll: true });
}

function ensureQueueUI() {
  ensureQueueVisibilityObserver();
  let button = document.getElementById(QUEUE_BUTTON_ID);
  let panel = document.getElementById(QUEUE_PANEL_ID);
  if (!button) {
    button = document.createElement("button");
    button.id = QUEUE_BUTTON_ID;
    button.type = "button";
    button.addEventListener("click", () => {
      queuePanelOpen = !queuePanelOpen;
      updateQueueUI();
    });
    document.body.appendChild(button);
  }
  if (!panel) {
    panel = document.createElement("aside");
    panel.id = QUEUE_PANEL_ID;
    panel.hidden = true;
    panel.setAttribute("aria-label", t("queueAria"));
    document.body.appendChild(panel);
  }
  return { button, panel };
}

function updateQueueButton(button, activeItems) {
  syncQueueButtonVisibility(button);
  button.replaceChildren();
  button.classList.toggle("is-idle", activeItems.length === 0);
  if (!activeItems.length) {
    button.textContent = "♪";
    button.setAttribute("aria-label", t("queue"));
    return;
  }
  const current = activeItems[0];
  const label = document.createElement("span");
  label.className = "dkaraoke-queue-button-title";
  label.textContent = current.title || t("processingSong");
  button.appendChild(label);
  if (activeItems.length > 1) {
    const count = document.createElement("span");
    count.className = "dkaraoke-queue-count";
    count.textContent = String(activeItems.length);
    button.appendChild(count);
  }
}

function updateQueueUI(nextItems = queueItems, nextProcessedSongs = processedSongItems) {
  queueItems = (Array.isArray(nextItems) ? nextItems : []).slice(0, QUEUE_COMPACT_LIMIT);
  processedSongItems = Array.isArray(nextProcessedSongs) ? nextProcessedSongs : queueItems;
  const activeItems = activeQueueItems(queueItems);
  recordQueueDebug(activeItems);
  const { button, panel } = ensureQueueUI();
  updateQueueButton(button, activeItems);
  const hideQueuePanel = isQueueButtonSuppressed() || !queuePanelOpen;
  panel.hidden = hideQueuePanel;
  if (!panel.hidden) renderQueuePanel(panel);
  if (processedSongsDialogOpen) renderProcessedSongsDialog();
  applyQueueForCurrentVideo();
}

function refreshQueueState() {
  chrome.runtime.sendMessage({ type: "dkaraoke-get-queue" }, (response) => {
    const error = chrome.runtime.lastError?.message || response?.error;
    if (error || !response?.ok) {
      recordDiagnostic("warning", "queue_refresh_failed", error || t("queueUpdated"));
      return;
    }
    updateQueueUI(response.queue || [], response.processedSongs || []);
  });
}
