function mountKaraokeMenu() {
  const columns = document.querySelector("ytd-watch-flexy #columns");
  const primary = columns?.querySelector(":scope > #primary");
  if (!columns || !primary) return false;

  let leftPanel = document.getElementById(LEFT_PANEL_ID);
  let rightRail = document.getElementById(RIGHT_RAIL_ID);
  let rightPanel = document.getElementById(RIGHT_PANEL_ID);
  if (leftPanel?.parentElement !== columns) leftPanel?.remove();
  if (rightRail?.parentElement !== columns) {
    const nestedSecondary = rightRail?.querySelector(":scope > #secondary");
    if (nestedSecondary) primary.insertAdjacentElement("afterend", nestedSecondary);
    rightRail?.remove();
  }

  if (!document.getElementById(RIGHT_RAIL_ID)) {
    rightRail = document.createElement("div");
    rightRail.id = RIGHT_RAIL_ID;
    primary.insertAdjacentElement("afterend", rightRail);
  }

  if (rightPanel?.parentElement !== rightRail) rightPanel?.remove();

  if (!document.getElementById(LEFT_PANEL_ID)) {
    leftPanel = document.createElement("aside");
    leftPanel.id = LEFT_PANEL_ID;
    leftPanel.setAttribute("aria-label", "Karaoke playback controls");

    const monitor = document.createElement("div");
    monitor.className = "dkaraoke-monitor-frame";
    const star = document.createElement("div");
    star.className = "dkaraoke-monitor-star";
    star.setAttribute("aria-hidden", "true");
    star.style.setProperty("--dk-star-image", `url("${chrome.runtime.getURL("star.svg")}")`);
    star.style.setProperty("--dk-jagged-star-image", `url("${chrome.runtime.getURL("jagged_star.svg")}")`);
    star.style.setProperty("--dk-lines-image", `url("${chrome.runtime.getURL("lines.svg")}")`);
    const display = document.createElement("button");
    display.id = MONITOR_ID;
    display.type = "button";
    display.className = "dkaraoke-monitor-display";
    display.addEventListener("click", () => {
      if (processing || !cacheCheckComplete || !karaokizeAvailable) return;
      startKaraokize();
    });
    const monitorText = document.createElement("span");
    monitorText.id = MONITOR_TEXT_ID;
    monitorText.className = "dkaraoke-visually-hidden";
    monitorText.setAttribute("role", "status");
    monitorText.setAttribute("aria-live", "polite");
    monitorText.textContent = "wait...";
    monitor.append(star, display, monitorText);
    leftPanel.appendChild(monitor);
    columns.insertBefore(leftPanel, primary);
  }

  if (!document.getElementById(RIGHT_PANEL_ID)) {
    rightPanel = document.createElement("aside");
    rightPanel.id = RIGHT_PANEL_ID;
    rightPanel.setAttribute("aria-label", "Karaoke lyrics editor");
    rightRail.appendChild(rightPanel);
  }

  let menu = document.getElementById(MENU_ID);
  if (menu?.parentElement !== leftPanel) menu?.remove();
  const existingLyricsEditor = document.querySelector(".dkaraoke-lyrics-editor");
  if (existingLyricsEditor && existingLyricsEditor.parentElement !== rightPanel) {
    rightPanel.appendChild(existingLyricsEditor);
  } else if (menu && !existingLyricsEditor) {
    menu.remove();
    menu = null;
  }

  if (!document.getElementById(MENU_ID)) {
    menu = document.createElement("section");
    menu.id = MENU_ID;
    menu.setAttribute("aria-label", "Karaoke controls");

    const header = document.createElement("div");
    header.className = "dkaraoke-menu-header";
    header.innerHTML = "<strong>Karaoke studio</strong><span>Audio preparation</span>";

    const instruments = document.createElement("div");
    instruments.className = "dkaraoke-instruments";
    instruments.setAttribute("aria-label", "Separated audio tracks");

    for (const stem of STEMS) {
      const toggle = document.createElement("button");
      toggle.id = `dkaraoke-${stem}`;
      toggle.type = "button";
      toggle.textContent = stem === "vocals" ? "Vocals" : "Instrumental";
      toggle.disabled = true;
      toggle.addEventListener("click", () => toggleStem(stem));
      instruments.appendChild(toggle);
    }

    const lyricsEditor = document.createElement("div");
    lyricsEditor.className = "dkaraoke-lyrics-editor";
    const lyricsHeading = document.createElement("div");
    lyricsHeading.className = "dkaraoke-lyrics-heading";
    const lyricsLabel = document.createElement("label");
    lyricsLabel.htmlFor = LYRICS_TEXT_ID;
    lyricsLabel.textContent = "LYRICS";
    const lyricsStatus = document.createElement("p");
    lyricsStatus.id = LYRICS_STATUS_ID;
    lyricsStatus.dataset.state = "idle";
    lyricsStatus.setAttribute("aria-live", "polite");
    lyricsStatus.textContent = "Search LRCLIB or enter lyrics, then extract timings.";
    lyricsHeading.append(lyricsLabel, lyricsStatus);

    const searchButton = document.createElement("button");
    searchButton.id = LRCLIB_SEARCH_ID;
    searchButton.type = "button";
    searchButton.textContent = "Search LRCLIB";
    searchButton.addEventListener("click", searchLrclibLyrics);
    const timingsButton = document.createElement("button");
    timingsButton.id = EXTRACT_TIMINGS_ID;
    timingsButton.type = "button";
    timingsButton.textContent = "Extract timings";
    timingsButton.addEventListener("click", extractLyricsTimings);
    const lyricsTextarea = document.createElement("textarea");
    lyricsTextarea.id = LYRICS_TEXT_ID;
    lyricsTextarea.placeholder = "LRCLIB lyrics will appear here. You can also paste or type lyrics.";
    lyricsTextarea.value = lyricsText;
    lyricsTextarea.addEventListener("input", () => {
      lyricsText = lyricsTextarea.value;
      updateLyricsProcessButtons();
    });
    const lyricsControls = document.createElement("div");
    lyricsControls.className = "dkaraoke-lyrics-controls";

    const lyricsToggle = document.createElement("button");
    lyricsToggle.id = LYRICS_ID;
    lyricsToggle.type = "button";
    lyricsToggle.textContent = "Lyrics";
    lyricsToggle.disabled = true;
    lyricsToggle.addEventListener("click", toggleLyrics);

    const styleLabel = document.createElement("label");
    styleLabel.htmlFor = LYRICS_STYLE_ID;
    styleLabel.textContent = "Lyrics style";
    const styleSelector = document.createElement("select");
    styleSelector.id = LYRICS_STYLE_ID;
    for (const [value, label] of [["classic", "Classic"], ["arcade", "Arcade"], ["simple", "Simple"]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      styleSelector.appendChild(option);
    }
    styleSelector.value = lyricsStyle;
    styleSelector.addEventListener("change", () => setLyricsStyle(styleSelector.value));
    const styleField = document.createElement("div");
    styleField.className = "dkaraoke-lyrics-style-field";
    styleField.append(styleLabel, styleSelector);

    const lyricsActions = document.createElement("div");
    lyricsActions.className = "dkaraoke-lyrics-actions";
    lyricsActions.append(searchButton, timingsButton);

    lyricsControls.append(lyricsToggle, styleField, lyricsActions);
    lyricsEditor.append(lyricsHeading, lyricsTextarea, lyricsControls);

    const actionRow = document.createElement("div");
    actionRow.className = "dkaraoke-action-row";

    const status = document.createElement("p");
    status.id = STATUS_ID;
    status.dataset.state = "idle";
    status.setAttribute("aria-live", "polite");
    status.textContent = "Ready to prepare this song.";

    const statusStack = document.createElement("div");
    statusStack.className = "dkaraoke-status-stack";

    const progress = document.createElement("div");
    progress.id = PROGRESS_ID;
    progress.hidden = true;
    progress.setAttribute("role", "progressbar");
    progress.setAttribute("aria-label", "Karaokize progress");
    progress.setAttribute("aria-valuemin", "0");
    progress.setAttribute("aria-valuemax", "100");

    const progressFill = document.createElement("span");
    progressFill.id = PROGRESS_FILL_ID;
    progress.appendChild(progressFill);
    statusStack.append(status, progress);

    const settingsButton = document.createElement("button");
    settingsButton.id = SETTINGS_BUTTON_ID;
    settingsButton.type = "button";
    settingsButton.textContent = "Settings";
    settingsButton.addEventListener("click", openSettingsModal);

    actionRow.append(statusStack, settingsButton);
    menu.append(header, instruments, actionRow);
    leftPanel.appendChild(menu);
    rightPanel.appendChild(lyricsEditor);
  }

  if (monitorObserver) monitorObserver.disconnect();
  monitorObserver = new ResizeObserver(updatePlaybackMonitor);
  monitorObserver.observe(document.querySelector(".dkaraoke-monitor-frame"));
  updateWorkspaceLayout();
  updatePlaybackMonitor();

  setProcessing(processing);
  updateStemButtons();
  updateLyricsButton();
  updateLyricsProcessButtons();
  setLyricsStyle(lyricsStyle, false);
  updateSettingsModalControls();
  refreshQueueState();
  checkSavedResults();
  return true;
}

function updateWorkspaceLayout() {
  const columns = document.querySelector("ytd-watch-flexy #columns");
  const primary = columns?.querySelector(":scope > #primary");
  const rightRail = columns?.querySelector(`:scope > #${RIGHT_RAIL_ID}`);
  const secondary = columns?.querySelector(":scope > #secondary")
    || rightRail?.querySelector(":scope > #secondary");
  if (!primary || !rightRail || !secondary) return;

  if (enabled) rightRail.appendChild(secondary);
  else primary.insertAdjacentElement("afterend", secondary);
}

function applyState() {
  document.documentElement.classList.toggle(ROOT_CLASS, enabled);

  const button = document.getElementById(BUTTON_ID);
  if (button) {
    button.classList.toggle("is-active", enabled);
    button.setAttribute("aria-pressed", String(enabled));
    button.title = enabled ? "Close Karaoke mode" : "Open Karaoke mode";
  }

  if (!enabled) {
    setSourceMode("original");
    stopLyricsRendering();
  } else if (customAudioReady) {
    applyStemSelection();
  }
  if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
  updateWorkspaceLayout();
  requestAnimationFrame(() => {
    updatePlaybackMonitor();
    window.dispatchEvent(new Event("resize"));
  });
}

function toggleMode() {
  enabled = !enabled;
  applyState();
  chrome.storage.local.set({ dkaraokeEnabled: enabled });
}

function mountControls() {
  const start = document.querySelector("ytd-masthead #start");
  if (!start) return false;

  const youtubeLogo = Array.from(start.children).find((element) =>
    element.matches?.("ytd-topbar-logo-renderer#logo")
  );
  if (!youtubeLogo) return false;

  let button = document.getElementById(BUTTON_ID);
  if (!button) {
    button = document.createElement("button");
    button.id = BUTTON_ID;
    button.type = "button";
    button.textContent = "K";
    button.setAttribute("aria-label", "Toggle Karaoke mode");
    button.addEventListener("click", toggleMode);
    youtubeLogo.insertAdjacentElement("afterend", button);
  }

  mountKaraokeMenu();
  bindVideo();
  applyState();
  return true;
}

function queueMount() {
  if (syncQueued) return;
  syncQueued = true;
  requestAnimationFrame(() => {
    syncQueued = false;
    if (mountControls()) {
      mountAttempts = 0;
    } else if (mountAttempts < 20) {
      mountAttempts += 1;
      setTimeout(queueMount, 250);
    }
  });
}

function remountAfterNavigation() {
  monitorActivities.clear();
  processing = false;
  cacheCheckJobId = null;
  cacheCheckComplete = false;
  karaokizeAvailable = false;
  activeJobId = null;
  activeJobStemsReady = false;
  discardCustomAudio();
  lyricsSearchJobId = null;
  timingsProcessing = false;
  timingsJobId = null;
  autoExtractAfterSearch = false;
  lyricsText = "";
  youtubeLyrics = { text: "", segments: [], source: "none" };
  if (settings.defaultStateMode === "reset") applyPlaybackState(defaultPlaybackState());
  setLyrics(youtubeLyrics);
  setProcessStatus("Checking saved karaoke results...", "busy");
  mountAttempts = 0;
  queueMount();
  refreshQueueState();
}
