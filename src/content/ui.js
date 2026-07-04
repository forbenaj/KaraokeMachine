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
    leftPanel.setAttribute("aria-label", t("controlsAria"));

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
    monitorText.textContent = t("loading");
    monitor.append(star, display, monitorText);
    leftPanel.appendChild(monitor);
    columns.insertBefore(leftPanel, primary);
  }

  if (!document.getElementById(RIGHT_PANEL_ID)) {
    rightPanel = document.createElement("aside");
    rightPanel.id = RIGHT_PANEL_ID;
    rightPanel.setAttribute("aria-label", t("lyricsEditorAria"));
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
    menu.setAttribute("aria-label", t("controlsSectionAria"));

    const header = document.createElement("div");
    header.className = "dkaraoke-menu-header";
    header.innerHTML = `<strong>${t("studioTitle")}</strong><span>${t("audioPreparation")}</span>`;

    const instruments = document.createElement("div");
    instruments.className = "dkaraoke-instruments";
    instruments.setAttribute("aria-label", t("separatedTracksAria"));

    for (const stem of STEMS) {
      const toggle = document.createElement("button");
      toggle.id = `dkaraoke-${stem}`;
      toggle.type = "button";
      const label = document.createElement("span");
      label.className = "dkaraoke-stem-label";
      label.textContent = stemLabel(stem);
      toggle.appendChild(label);
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
    lyricsLabel.textContent = t("lyricsUpper");
    const lyricsIndicator = document.createElement("span");
    lyricsIndicator.id = LYRICS_INDICATOR_ID;
    lyricsIndicator.className = "dkaraoke-lyrics-indicator";
    lyricsIndicator.dataset.state = "idle";
    lyricsIndicator.textContent = "Waiting...";
    lyricsIndicator.setAttribute("role", "status");
    lyricsIndicator.setAttribute("aria-live", "polite");
    lyricsHeading.append(lyricsLabel, lyricsIndicator);

    const searchButton = document.createElement("button");
    searchButton.id = LRCLIB_SEARCH_ID;
    searchButton.type = "button";
    searchButton.textContent = t("searchLrclib");
    searchButton.addEventListener("click", searchLrclibLyrics);
    const timingsButton = document.createElement("button");
    timingsButton.id = EXTRACT_TIMINGS_ID;
    timingsButton.type = "button";
    timingsButton.textContent = t("extractTimings");
    timingsButton.addEventListener("click", extractLyricsTimings);
    const lyricsTextarea = document.createElement("textarea");
    lyricsTextarea.id = LYRICS_TEXT_ID;
    lyricsTextarea.dataset.processState = "idle";
    lyricsTextarea.dataset.processText = "Waiting...";
    lyricsTextarea.value = lyricsText;
    lyricsTextarea.addEventListener("input", () => {
      lyricsText = lyricsTextarea.value;
      updateLyricsIndicator();
      updateLyricsProcessButtons();
    });
    const lyricsTextWrap = document.createElement("div");
    lyricsTextWrap.className = "dkaraoke-lyrics-text-wrap";
    lyricsTextWrap.append(lyricsTextarea);
    const lyricsEditorBody = document.createElement("div");
    lyricsEditorBody.id = LYRICS_EDITOR_BODY_ID;
    lyricsEditorBody.className = "dkaraoke-lyrics-editor-body";
    const lyricsEditHeader = document.createElement("div");
    lyricsEditHeader.className = "dkaraoke-lyrics-edit-header";
    const nameLabel = document.createElement("label");
    nameLabel.className = "dkaraoke-visually-hidden";
    nameLabel.htmlFor = LYRICS_NAME_ID;
    nameLabel.textContent = t("lyricsFileName");
    const nameInput = document.createElement("input");
    nameInput.id = LYRICS_NAME_ID;
    nameInput.type = "text";
    nameInput.placeholder = t("lyricsFileName");
    nameInput.disabled = true;
    const saveButton = document.createElement("button");
    saveButton.id = LYRICS_SAVE_ID;
    saveButton.type = "button";
    saveButton.textContent = t("saveLyrics");
    saveButton.addEventListener("click", saveActiveLyricFile);
    lyricsEditHeader.append(nameLabel, nameInput, saveButton);
    lyricsEditorBody.append(lyricsEditHeader, lyricsTextWrap);
    const lyricsFileBar = document.createElement("div");
    lyricsFileBar.id = LYRICS_FILE_BAR_ID;
    lyricsFileBar.className = "dkaraoke-lyrics-file-bar";
    lyricsFileBar.setAttribute("aria-label", "Lyrics files");
    const lyricsControls = document.createElement("div");
    lyricsControls.className = "dkaraoke-lyrics-controls";

    const lyricsToggle = document.createElement("button");
    lyricsToggle.id = LYRICS_ID;
    lyricsToggle.type = "button";
    lyricsToggle.textContent = t("lyrics");
    lyricsToggle.disabled = true;
    lyricsToggle.addEventListener("click", toggleLyrics);

    const styleLabel = document.createElement("label");
    styleLabel.htmlFor = LYRICS_STYLE_ID;
    styleLabel.textContent = t("lyricsStyle");
    const styleSelector = document.createElement("select");
    styleSelector.id = LYRICS_STYLE_ID;
    for (const [value, label] of [["classic", t("styleClassic")], ["arcade", t("styleArcade")], ["simple", t("styleSimple")]]) {
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
    lyricsEditor.append(lyricsHeading, lyricsEditorBody, lyricsFileBar, lyricsControls);

    const actionRow = document.createElement("div");
    actionRow.className = "dkaraoke-action-row";

    const settingsButton = document.createElement("button");
    settingsButton.id = SETTINGS_BUTTON_ID;
    settingsButton.type = "button";
    settingsButton.textContent = t("settings");
    settingsButton.addEventListener("click", openSettingsModal);

    actionRow.append(settingsButton);
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
  renderLyricFileBar();
  setLyricsStyle(lyricsStyle, false);
  updateSettingsModalControls();
  renderDebugPanel();
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
  updateBackgroundReadiness();

  const button = document.getElementById(BUTTON_ID);
  if (button) {
    button.classList.toggle("is-active", enabled);
    button.setAttribute("aria-pressed", String(enabled));
    button.title = enabled ? t("closeModeTitle") : t("openModeTitle");
  }

  if (!enabled) {
    setSourceMode("original");
    stopLyricsRendering();
  } else if (customAudioReady) {
    applyStemSelection();
  }
  if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
  updateWorkspaceLayout();
  renderDebugPanel();
  updateQueueUI();
  requestAnimationFrame(() => {
    updatePlaybackMonitor();
    window.dispatchEvent(new Event("resize"));
  });
}

function refreshLocalizedUI() {
  const modal = document.getElementById(SETTINGS_MODAL_ID);
  const modalOpen = Boolean(modal?.open);
  if (modal) modal.remove();

  const leftPanel = document.getElementById(LEFT_PANEL_ID);
  if (leftPanel) leftPanel.setAttribute("aria-label", t("controlsAria"));
  const rightPanel = document.getElementById(RIGHT_PANEL_ID);
  if (rightPanel) rightPanel.setAttribute("aria-label", t("lyricsEditorAria"));
  const menu = document.getElementById(MENU_ID);
  if (menu) menu.setAttribute("aria-label", t("controlsSectionAria"));
  const header = menu?.querySelector(".dkaraoke-menu-header");
  if (header) header.innerHTML = `<strong>${t("studioTitle")}</strong><span>${t("audioPreparation")}</span>`;
  const instruments = menu?.querySelector(".dkaraoke-instruments");
  if (instruments) instruments.setAttribute("aria-label", t("separatedTracksAria"));
  for (const stem of STEMS) {
    const button = document.getElementById(`dkaraoke-${stem}`);
    const label = button?.querySelector(".dkaraoke-stem-label");
    if (label) label.textContent = stemLabel(stem);
  }

  const lyricsLabel = document.querySelector(`label[for="${LYRICS_TEXT_ID}"]`);
  if (lyricsLabel) lyricsLabel.textContent = t("lyricsUpper");
  const editor = document.getElementById(LYRICS_TEXT_ID);
  if (editor && !editor.dataset.processText) editor.dataset.processText = "Waiting...";
  const lyricsButton = document.getElementById(LYRICS_ID);
  if (lyricsButton) lyricsButton.textContent = t("lyrics");
  const saveButton = document.getElementById(LYRICS_SAVE_ID);
  if (saveButton) saveButton.textContent = t("saveLyrics");
  const nameInput = document.getElementById(LYRICS_NAME_ID);
  if (nameInput) nameInput.placeholder = t("lyricsFileName");
  const styleLabel = document.querySelector(`label[for="${LYRICS_STYLE_ID}"]`);
  if (styleLabel) styleLabel.textContent = t("lyricsStyle");
  const styleSelector = document.getElementById(LYRICS_STYLE_ID);
  if (styleSelector) {
    const selected = styleSelector.value;
    styleSelector.replaceChildren();
    for (const [value, label] of [["classic", t("styleClassic")], ["arcade", t("styleArcade")], ["simple", t("styleSimple")]]) {
      const option = document.createElement("option");
      option.value = value;
      option.textContent = label;
      styleSelector.appendChild(option);
    }
    styleSelector.value = selected;
  }

  const settingsButton = document.getElementById(SETTINGS_BUTTON_ID);
  if (settingsButton) settingsButton.textContent = t("settings");
  const toggle = document.getElementById(BUTTON_ID);
  if (toggle) toggle.setAttribute("aria-label", t("toggleModeAria"));

  updateStemButtons();
  updateLyricsButton();
  updateLyricsProcessButtons();
  renderLyricFileBar();
  updatePlaybackMonitor();
  updateQueueUI();
  renderDebugPanel();
  applyState();

  if (modalOpen) openSettingsModal();
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
    button.setAttribute("aria-label", t("toggleModeAria"));
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
  debugProcessJobs.clear();
  appendDebugLog("karaokize", "info", t("navigationDetected"));
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
  lyricFiles = [];
  activeLyricsFileId = "";
  lyricFileJobId = null;
  youtubeLyrics = { text: "", segments: [], source: "none" };
  if (settings.defaultStateMode === "reset") applyPlaybackState(defaultPlaybackState());
  setLyrics(youtubeLyrics);
  setProcessStatus(t("savedChecking"), "busy");
  renderDebugPanel();
  mountAttempts = 0;
  queueMount();
  refreshQueueState();
}
