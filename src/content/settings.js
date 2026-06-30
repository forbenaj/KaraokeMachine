function normalizeSettings(value = {}) {
  return {
    ...DEFAULT_SETTINGS,
    ...value,
    latencyMs: clampNumber(value.latencyMs, -1000, 1000, DEFAULT_SETTINGS.latencyMs),
    lyricsLatencyMs: clampNumber(value.lyricsLatencyMs, -1000, 1000, DEFAULT_SETTINGS.lyricsLatencyMs),
    timingExtractionMethod: normalizeTimingMethod(value.timingExtractionMethod),
    timingExtractionSource: normalizeTimingSource(value.timingExtractionSource),
    timingPipelineSchedule: normalizeTimingSchedule(value.timingPipelineSchedule),
    defaultStateMode: value.defaultStateMode === "reset" ? "reset" : "keep",
    defaultInstrumental: value.defaultInstrumental !== false,
    defaultVocals: value.defaultVocals === true,
    defaultLyrics: value.defaultLyrics !== false,
    debugEnabled: value.debugEnabled === true,
  };
}

function defaultPlaybackState() {
  return {
    instrumental: settings.defaultInstrumental,
    vocals: settings.defaultVocals,
    lyrics: settings.defaultLyrics,
  };
}

function applyPlaybackState(state) {
  stemEnabled = {
    instrumental: state.instrumental !== false,
    vocals: state.vocals === true,
  };
  lyricsEnabled = state.lyrics !== false;
  updateStemButtons();
  updateLyricsButton();
  if (customAudioReady && enabled) applyStemSelection();
  if (enabled && lyricsEnabled && lyricsReady) startLyricsRendering();
  else stopLyricsRendering();
}

function saveSettings() {
  chrome.storage.local.set({ dkaraokeSettings: settings });
}

function persistPlaybackState() {
  if (settings.defaultStateMode !== "keep") return;
  chrome.storage.local.set({
    dkaraokePlaybackState: {
      instrumental: stemEnabled.instrumental,
      vocals: stemEnabled.vocals,
      lyrics: lyricsEnabled,
    }
  });
}
function updateSettingsModalControls() {
  const modal = document.getElementById(SETTINGS_MODAL_ID);
  if (!modal) return;
  const latency = modal.querySelector("#dkaraoke-setting-latency");
  const lyricsLatency = modal.querySelector("#dkaraoke-setting-lyrics-latency");
  const timingMethod = modal.querySelector(`#${TIMING_METHOD_ID}`);
  const timingSource = modal.querySelector(`#${TIMING_SOURCE_ID}`);
  const timingSchedule = modal.querySelector(`#${TIMING_SCHEDULE_ID}`);
  const keep = modal.querySelector("#dkaraoke-default-keep");
  const reset = modal.querySelector("#dkaraoke-default-reset");
  const instrumental = modal.querySelector("#dkaraoke-default-instrumental");
  const vocals = modal.querySelector("#dkaraoke-default-vocals");
  const lyrics = modal.querySelector("#dkaraoke-default-lyrics");
  const debug = modal.querySelector(`#${DEBUG_ENABLED_ID}`);
  if (latency) latency.value = String(settings.latencyMs);
  if (lyricsLatency) lyricsLatency.value = String(settings.lyricsLatencyMs);
  if (timingMethod) timingMethod.value = settings.timingExtractionMethod;
  if (timingSource) timingSource.value = settings.timingExtractionSource;
  if (timingSchedule) {
    timingSchedule.value = settings.timingPipelineSchedule;
    timingSchedule.disabled = settings.timingExtractionSource !== "original";
  }
  if (keep) keep.checked = settings.defaultStateMode === "keep";
  if (reset) reset.checked = settings.defaultStateMode === "reset";
  if (instrumental) instrumental.checked = settings.defaultInstrumental;
  if (vocals) vocals.checked = settings.defaultVocals;
  if (lyrics) lyrics.checked = settings.defaultLyrics;
  if (debug) debug.checked = settings.debugEnabled;
  for (const input of [instrumental, vocals, lyrics].filter(Boolean)) {
    input.disabled = settings.defaultStateMode !== "reset";
  }
}

function makeSettingNumber(id, label, value, handler) {
  const field = document.createElement("label");
  field.className = "dkaraoke-setting-field";
  const text = document.createElement("span");
  text.textContent = label;
  const input = document.createElement("input");
  input.id = id;
  input.type = "number";
  input.min = "-1000";
  input.max = "1000";
  input.step = "5";
  input.value = String(value);
  input.addEventListener("change", () => handler(clampNumber(input.value, -1000, 1000, value)));
  field.append(text, input);
  return field;
}

function makeSettingSelect(id, label, options, value, normalize, handler) {
  const field = document.createElement("label");
  field.className = "dkaraoke-setting-field dkaraoke-setting-field-select";
  const text = document.createElement("span");
  text.textContent = label;
  const select = document.createElement("select");
  select.id = id;
  for (const [optionValue, optionLabel] of options) {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionLabel;
    select.appendChild(option);
  }
  select.value = value;
  select.addEventListener("change", () => handler(normalize(select.value)));
  field.append(text, select);
  return field;
}

function ensureSettingsModal() {
  let modal = document.getElementById(SETTINGS_MODAL_ID);
  if (modal) return modal;

  modal = document.createElement("dialog");
  modal.id = SETTINGS_MODAL_ID;
  modal.setAttribute("aria-label", "DKaraoKe settings");

  const header = document.createElement("div");
  header.className = "dkaraoke-modal-header";
  const title = document.createElement("strong");
  title.textContent = "Settings";
  const close = document.createElement("button");
  close.type = "button";
  close.textContent = "Close";
  close.addEventListener("click", () => modal.close());
  header.append(title, close);

  const body = document.createElement("div");
  body.className = "dkaraoke-settings-body";

  body.append(
    makeSettingNumber("dkaraoke-setting-latency", "Latency compensation (ms)", settings.latencyMs, (value) => {
      settings.latencyMs = value;
      saveSettings();
      syncCustomAudio(true);
      updateSettingsModalControls();
    }),
    makeSettingNumber("dkaraoke-setting-lyrics-latency", "Lyrics timing offset (ms)", settings.lyricsLatencyMs, (value) => {
      settings.lyricsLatencyMs = value;
      saveSettings();
      renderedLyricSegment = null;
      updateSettingsModalControls();
    })
  );

  const timing = document.createElement("fieldset");
  timing.className = "dkaraoke-settings-section";
  const timingLegend = document.createElement("legend");
  timingLegend.textContent = "Timing extraction";
  timing.append(
    timingLegend,
    makeSettingSelect(
      TIMING_METHOD_ID,
      "Method",
      [
        ["ctc", "Current (CTC forced alignment)"],
        ["silero-vad", "Silero VAD"],
      ],
      settings.timingExtractionMethod,
      normalizeTimingMethod,
      (value) => {
        settings.timingExtractionMethod = value;
        saveSettings();
        updateSettingsModalControls();
      },
    ),
    makeSettingSelect(
      TIMING_SOURCE_ID,
      "Audio source",
      [
        ["original", "Original audio"],
        ["vocal-stem", "Vocal stem"],
      ],
      settings.timingExtractionSource,
      normalizeTimingSource,
      (value) => {
        settings.timingExtractionSource = value;
        saveSettings();
        updateSettingsModalControls();
      },
    ),
    makeSettingSelect(
      TIMING_SCHEDULE_ID,
      "Press me order",
      [
        ["stems-first", "Stems first"],
        ["lyrics-first", "Lyrics first"],
        ["parallel", "Run together"],
      ],
      settings.timingPipelineSchedule,
      normalizeTimingSchedule,
      (value) => {
        settings.timingPipelineSchedule = value;
        saveSettings();
        updateSettingsModalControls();
      },
    )
  );

  const defaults = document.createElement("fieldset");
  defaults.className = "dkaraoke-settings-section dkaraoke-settings-defaults";
  const legend = document.createElement("legend");
  legend.textContent = "Default state";
  const keepLabel = document.createElement("label");
  const keepInput = document.createElement("input");
  keepInput.id = "dkaraoke-default-keep";
  keepInput.type = "radio";
  keepInput.name = "dkaraoke-default-mode";
  keepInput.value = "keep";
  keepInput.addEventListener("change", () => {
    settings.defaultStateMode = "keep";
    saveSettings();
    persistPlaybackState();
    updateSettingsModalControls();
  });
  keepLabel.append(keepInput, document.createTextNode("Keep across songs"));

  const resetLabel = document.createElement("label");
  const resetInput = document.createElement("input");
  resetInput.id = "dkaraoke-default-reset";
  resetInput.type = "radio";
  resetInput.name = "dkaraoke-default-mode";
  resetInput.value = "reset";
  resetInput.addEventListener("change", () => {
    settings.defaultStateMode = "reset";
    saveSettings();
    applyPlaybackState(defaultPlaybackState());
    updateSettingsModalControls();
  });
  resetLabel.append(resetInput, document.createTextNode("Always reset to:"));

  const resetOptions = document.createElement("div");
  resetOptions.className = "dkaraoke-reset-options";
  for (const [id, label, key] of [
    ["dkaraoke-default-instrumental", "Instrumental", "defaultInstrumental"],
    ["dkaraoke-default-vocals", "Vocals", "defaultVocals"],
    ["dkaraoke-default-lyrics", "Lyrics", "defaultLyrics"],
  ]) {
    const optionLabel = document.createElement("label");
    const input = document.createElement("input");
    input.id = id;
    input.type = "checkbox";
    input.addEventListener("change", () => {
      settings[key] = input.checked;
      saveSettings();
      if (settings.defaultStateMode === "reset") applyPlaybackState(defaultPlaybackState());
      updateSettingsModalControls();
    });
    optionLabel.append(input, document.createTextNode(label));
    resetOptions.appendChild(optionLabel);
  }

  defaults.append(legend, keepLabel, resetLabel, resetOptions);

  const diagnostics = document.createElement("fieldset");
  diagnostics.className = "dkaraoke-settings-section";
  const diagnosticsLegend = document.createElement("legend");
  diagnosticsLegend.textContent = "Diagnostics";
  const debugLabel = document.createElement("label");
  debugLabel.className = "dkaraoke-debug-toggle";
  const debugInput = document.createElement("input");
  debugInput.id = DEBUG_ENABLED_ID;
  debugInput.type = "checkbox";
  debugInput.addEventListener("change", () => {
    settings.debugEnabled = debugInput.checked;
    saveSettings();
    renderDebugPanel();
    updateSettingsModalControls();
  });
  debugLabel.append(debugInput, document.createTextNode("Debug console"));
  diagnostics.append(diagnosticsLegend, debugLabel);

  body.appendChild(timing);
  body.appendChild(defaults);
  body.appendChild(diagnostics);
  modal.append(header, body);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) modal.close();
  });
  document.body.appendChild(modal);
  updateSettingsModalControls();
  return modal;
}

function openSettingsModal() {
  const modal = ensureSettingsModal();
  updateSettingsModalControls();
  if (typeof modal.showModal === "function") modal.showModal();
  else modal.setAttribute("open", "");
}
