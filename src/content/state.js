const ROOT_CLASS = "dkaraoke-enabled";
const BUTTON_ID = "dkaraoke-toggle";
const LOGO_ID = "dkaraoke-logo";
const MENU_ID = "dkaraoke-menu";
const LEFT_PANEL_ID = "dkaraoke-left-panel";
const RIGHT_RAIL_ID = "dkaraoke-right-rail";
const RIGHT_PANEL_ID = "dkaraoke-right-panel";
const MONITOR_ID = "dkaraoke-monitor";
const MONITOR_TEXT_ID = "dkaraoke-monitor-text";
const STATUS_ID = "dkaraoke-process-status";
const PROGRESS_ID = "dkaraoke-process-progress";
const PROGRESS_FILL_ID = "dkaraoke-process-progress-fill";
const KARAOKIZE_ID = "dkaraoke-karaokize";
const LYRICS_ID = "dkaraoke-lyrics";
const LYRICS_TEXT_ID = "dkaraoke-lyrics-text";
const LRCLIB_SEARCH_ID = "dkaraoke-search-lrclib";
const EXTRACT_TIMINGS_ID = "dkaraoke-extract-timings";
const LYRICS_STATUS_ID = "dkaraoke-lyrics-status";
const LYRICS_STYLE_ID = "dkaraoke-lyrics-style";
const LYRICS_OVERLAY_ID = "dkaraoke-lyrics-overlay";
const SETTINGS_BUTTON_ID = "dkaraoke-settings";
const SETTINGS_MODAL_ID = "dkaraoke-settings-modal";
const QUEUE_BUTTON_ID = "dkaraoke-queue-button";
const QUEUE_PANEL_ID = "dkaraoke-queue-panel";
const STEMS = ["instrumental", "vocals"];
const DEFAULT_SETTINGS = {
  latencyMs: 75,
  lyricsLatencyMs: 75,
  defaultStateMode: "keep",
  defaultInstrumental: true,
  defaultVocals: false,
  defaultLyrics: true,
};
const DEFAULT_PLAYBACK_STATE = {
  instrumental: true,
  vocals: false,
  lyrics: true,
};
const SYNC_MONITOR_INTERVAL_MS = 250;
const SOFT_SYNC_THRESHOLD_SECONDS = 0.03;
const HARD_SYNC_THRESHOLD_SECONDS = 0.15;
const MAX_RATE_CORRECTION = 0.05;
const MIN_AUDIO_PLAYBACK_RATE = 0.25;
const MAX_AUDIO_PLAYBACK_RATE = 4;

let enabled = false;
let syncQueued = false;
let mountAttempts = 0;
let processing = false;
let cacheCheckJobId = null;
let cacheCheckComplete = false;
let karaokizeAvailable = false;
let activeJobId = null;
let activeJobStemsReady = false;
let customAudio = {};
let customAudioReady = false;
let sourceMode = "original";
let stemEnabled = { instrumental: true, vocals: false };
let syncedVideo = null;
let videoEvents = null;
let adObserver = null;
let originalMuted = false;
let adActive = false;
let playBlocked = false;
let syncMonitorId = null;
let customAudioInterruptionTimer = null;
let lyricsEnabled = true;
let lyricsStyle = "arcade";
let settings = { ...DEFAULT_SETTINGS };
let queueItems = [];
let queuePanelOpen = false;
let lyricsReady = false;
let lyricsText = "";
let lyricSegments = [];
let youtubeLyrics = { text: "", segments: [], source: "none" };
let lyricsSearchJobId = null;
let lyricAnimationId = null;
let renderedLyricSegment = null;
let timingsProcessing = false;
let timingsJobId = null;
let monitorObserver = null;
const monitorActivities = new Map();

function getYouTubeVideo() {
  return document.querySelector("video.html5-main-video, #movie_player video");
}

function currentVideoId() {
  return new URL(location.href).searchParams.get("v") || "";
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}
