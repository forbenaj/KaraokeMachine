function summarizeQueueItem(item) {
  if (item.status === "queued") return "Queued";
  if (Number.isFinite(item.progress) && !/%/.test(item.message || "")) {
    return `${item.message || "Processing"} ${Math.round(item.progress)}%`;
  }
  return item.message || "Processing";
}

function isQueueItemTerminal(item) {
  return ["complete", "error"].includes(item?.status);
}

function applyQueueForCurrentVideo() {
  const videoId = currentVideoId();
  const job = queueItems.find((item) =>
    item.videoId
    && item.videoId === videoId
    && !isQueueItemTerminal(item)
    && !finishedJobIds.has(item.jobId)
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
  setMonitorActivity(job.jobId, "audio", job.status === "queued" ? "Queued..." : "Processing...");
}

function renderQueuePanel(panel) {
  panel.replaceChildren();
  const header = document.createElement("div");
  header.className = "dkaraoke-queue-header";
  const title = document.createElement("strong");
  title.textContent = "Queue";
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Close";
  close.addEventListener("click", () => {
    queuePanelOpen = false;
    updateQueueUI();
  });
  header.append(title, close);
  panel.appendChild(header);

  const list = document.createElement("ol");
  list.className = "dkaraoke-queue-list";
  for (const item of queueItems) {
    const row = document.createElement("li");
    row.dataset.status = item.status || "queued";
    const itemTitle = document.createElement("span");
    itemTitle.className = "dkaraoke-queue-title";
    itemTitle.textContent = item.title || "YouTube song";
    const meta = document.createElement("span");
    meta.className = "dkaraoke-queue-meta";
    meta.textContent = summarizeQueueItem(item);
    row.append(itemTitle, meta);
    list.appendChild(row);
  }
  panel.appendChild(list);
}

function ensureQueueUI() {
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
    panel.setAttribute("aria-label", "DKaraoKe processing queue");
    document.body.appendChild(panel);
  }
  return { button, panel };
}

function updateQueueUI(nextItems = queueItems) {
  queueItems = (Array.isArray(nextItems) ? nextItems : [])
    .filter((item) => !isQueueItemTerminal(item) && !finishedJobIds.has(item.jobId));
  recordQueueDebug(queueItems);
  const { button, panel } = ensureQueueUI();
  const current = queueItems[0];
  button.hidden = queueItems.length === 0;
  button.replaceChildren();
  if (current) {
    const label = document.createElement("span");
    label.className = "dkaraoke-queue-button-title";
    label.textContent = current.title || "Processing song";
    button.appendChild(label);
    if (queueItems.length > 1) {
      const count = document.createElement("span");
      count.className = "dkaraoke-queue-count";
      count.textContent = String(queueItems.length);
      button.appendChild(count);
    }
  }
  panel.hidden = !queuePanelOpen || queueItems.length === 0;
  if (!panel.hidden) renderQueuePanel(panel);
  applyQueueForCurrentVideo();
}

function refreshQueueState() {
  chrome.runtime.sendMessage({ type: "dkaraoke-get-queue" }, (response) => {
    if (chrome.runtime.lastError || !response?.ok) return;
    updateQueueUI(response.queue || []);
  });
}
