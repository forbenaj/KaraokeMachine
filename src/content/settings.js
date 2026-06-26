function normalizeSettings(value = {}) {
  return {
    ...DEFAULT_SETTINGS,
    ...value,
    latencyMs: clampNumber(value.latencyMs, -1000, 1000, DEFAULT_SETTINGS.latencyMs),
    lyricsLatencyMs: clampNumber(value.lyricsLatencyMs, -1000, 1000, DEFAULT_SETTINGS.lyricsLatencyMs),
    defaultStateMode: value.defaultStateMode === "reset" ? "reset" : "keep",
    defaultInstrumental: value.defaultInstrumental !== false,
    defaultVocals: value.defaultVocals === true,
    defaultLyrics: value.defaultLyrics !== false,
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
  const keep = modal.querySelector("#dkaraoke-default-keep");
  const reset = modal.querySelector("#dkaraoke-default-reset");
  const instrumental = modal.querySelector("#dkaraoke-default-instrumental");
  const vocals = modal.querySelector("#dkaraoke-default-vocals");
  const lyrics = modal.querySelector("#dkaraoke-default-lyrics");
  if (latency) latency.value = String(settings.latencyMs);
  if (lyricsLatency) lyricsLatency.value = String(settings.lyricsLatencyMs);
  if (keep) keep.checked = settings.defaultStateMode === "keep";
  if (reset) reset.checked = settings.defaultStateMode === "reset";
  if (instrumental) instrumental.checked = settings.defaultInstrumental;
  if (vocals) vocals.checked = settings.defaultVocals;
  if (lyrics) lyrics.checked = settings.defaultLyrics;
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

  const defaults = document.createElement("fieldset");
  defaults.className = "dkaraoke-settings-defaults";
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
  body.appendChild(defaults);
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
