const ROOT_CLASS = "dkaraoke-enabled";
const BACKGROUND_OK_CLASS = "dkaraoke-background-ok";
const BUTTON_ID = "dkaraoke-toggle";
const MENU_ID = "dkaraoke-menu";
const LEFT_PANEL_ID = "dkaraoke-left-panel";
const RIGHT_RAIL_ID = "dkaraoke-right-rail";
const RIGHT_PANEL_ID = "dkaraoke-right-panel";
const MONITOR_ID = "dkaraoke-monitor";
const MONITOR_TEXT_ID = "dkaraoke-monitor-text";
const STATUS_ID = "dkaraoke-process-status";
const PROGRESS_ID = "dkaraoke-process-progress";
const PROGRESS_FILL_ID = "dkaraoke-process-progress-fill";
const LYRICS_ID = "dkaraoke-lyrics";
const LYRICS_TEXT_ID = "dkaraoke-lyrics-text";
const LRCLIB_SEARCH_ID = "dkaraoke-search-lrclib";
const EXTRACT_TIMINGS_ID = "dkaraoke-extract-timings";
const LYRICS_STATUS_ID = "dkaraoke-lyrics-status";
const LYRICS_STYLE_ID = "dkaraoke-lyrics-style";
const LYRICS_OVERLAY_ID = "dkaraoke-lyrics-overlay";
const SETTINGS_BUTTON_ID = "dkaraoke-settings";
const SETTINGS_MODAL_ID = "dkaraoke-settings-modal";
const DEBUG_PANEL_ID = "dkaraoke-debug-panel";
const DEBUG_INDICATORS_ID = "dkaraoke-debug-indicators";
const DEBUG_LOG_ID = "dkaraoke-debug-log";
const DEBUG_ENABLED_ID = "dkaraoke-debug-enabled";
const TIMING_METHOD_ID = "dkaraoke-setting-timing-method";
const TIMING_SOURCE_ID = "dkaraoke-setting-timing-source";
const TIMING_SCHEDULE_ID = "dkaraoke-setting-timing-schedule";
const QUEUE_BUTTON_ID = "dkaraoke-queue-button";
const QUEUE_PANEL_ID = "dkaraoke-queue-panel";
const DEFAULT_LYRICS_STYLE = "classic";
const LYRICS_STYLES = new Set(["arcade", "classic", "simple"]);
const DEFAULT_TIMING_METHOD = "ctc";
const TIMING_METHODS = new Set(["ctc", "silero-vad"]);
const TIMING_METHOD_LABELS = {
  "ctc": "CTC forced alignment",
  "silero-vad": "Silero VAD",
};
const DEFAULT_TIMING_SOURCE = "original";
const TIMING_SOURCES = new Set(["original", "vocal-stem"]);
const TIMING_SOURCE_LABELS = {
  "original": "original audio",
  "vocal-stem": "vocal stem",
};
const DEFAULT_TIMING_SCHEDULE = "stems-first";
const TIMING_SCHEDULES = new Set(["stems-first", "lyrics-first", "parallel"]);
const TIMING_SCHEDULE_LABELS = {
  "stems-first": "after stems",
  "lyrics-first": "before stems",
  "parallel": "alongside stems",
};
const APP_NAME = "Karaoke Machine!";
const APP_NAME_JA = "カラオケマシン!";
const DEFAULT_LANGUAGE = "en";
const LANGUAGES = new Set(["en", "ja", "es"]);
const LANGUAGE_LABELS = {
  en: "English",
  ja: "日本語",
  es: "Español",
};
const STEMS = ["instrumental", "vocals"];
const DEFAULT_SETTINGS = {
  language: DEFAULT_LANGUAGE,
  latencyMs: 75,
  lyricsLatencyMs: 75,
  timingExtractionMethod: DEFAULT_TIMING_METHOD,
  timingExtractionSource: DEFAULT_TIMING_SOURCE,
  timingPipelineSchedule: DEFAULT_TIMING_SCHEDULE,
  defaultStateMode: "keep",
  defaultInstrumental: true,
  defaultVocals: false,
  defaultLyrics: true,
  debugEnabled: false,
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
let lyricsStyle = DEFAULT_LYRICS_STYLE;
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
let autoExtractAfterSearch = false;
let monitorObserver = null;
let debugLogEntries = [];
let debugLastSignature = "";
let debugQueueSignature = "";
const debugProcessJobs = new Map();
const debugCurrentPhaseByJob = new Map();
let finishedJobIds = new Set();
const monitorActivities = new Map();

const I18N = {
  en: {
    appName: APP_NAME,
    appNameFull: APP_NAME,
    controlsAria: "Karaoke playback controls",
    lyricsEditorAria: "Karaoke lyrics editor",
    controlsSectionAria: "Karaoke controls",
    separatedTracksAria: "Separated audio tracks",
    toggleModeAria: "Toggle Karaoke Machine mode",
    openModeTitle: "Open Karaoke Machine mode",
    closeModeTitle: "Close Karaoke Machine mode",
    studioTitle: "Karaoke Machine!",
    audioPreparation: "Audio preparation",
    instrumental: "Instrumental",
    vocals: "Vocals",
    lyrics: "Lyrics",
    lyricsUpper: "LYRICS",
    lyricsInitialStatus: "Search LRCLIB or enter lyrics, then extract timings.",
    searchLrclib: "Search LRCLIB",
    searchingLrclib: "Searching LRCLIB...",
    extractTimings: "Extract timings",
    extractingTimings: "Extracting timings...",
    lyricsPlaceholder: "LRCLIB lyrics will appear here. You can also paste or type lyrics.",
    lyricsStyle: "Lyrics style",
    styleClassic: "Classic",
    styleArcade: "Arcade",
    styleSimple: "Simple",
    readyToPrepare: "Ready to prepare this song.",
    karaokizeProgress: "Karaoke Machine progress",
    settings: "Settings",
    settingsAria: "Karaoke Machine settings",
    close: "Close",
    language: "Language",
    latencyCompensation: "Latency compensation (ms)",
    lyricsTimingOffset: "Lyrics timing offset (ms)",
    timingExtraction: "Timing extraction",
    method: "Method",
    currentCtc: "Current (CTC forced alignment)",
    sileroVad: "Silero VAD",
    audioSource: "Audio source",
    originalAudio: "Original audio",
    vocalStem: "Vocal stem",
    pressMeOrder: "Press me order",
    stemsFirst: "Stems first",
    lyricsFirst: "Lyrics first",
    runTogether: "Run together",
    defaultState: "Default state",
    keepAcrossSongs: "Keep across songs",
    alwaysResetTo: "Always reset to:",
    diagnostics: "Diagnostics",
    debugConsole: "Debug console",
    debugLogAria: "Karaoke Machine debug log",
    debugTitle: "Karaoke Machine debug",
    liveProcessTrace: "Live process trace",
    queue: "Queue",
    queueAria: "Karaoke Machine processing queue",
    youtubeSong: "YouTube song",
    processingSong: "Processing song",
    queued: "Queued",
    processing: "Processing",
    loading: "Loading...",
    pressMe: "Press me!",
    playing: "Playing",
    pause: "Pause",
    readyBang: "Ready!",
    pressMeTitle: "Press me to prepare this song.",
    preparationInProgress: "Karaoke Machine preparation is in progress.",
    alreadyPrepared: "This song is already prepared.",
    enableStemTitle: "Enable {stem}.",
    disableStemTitle: "Disable {stem}.",
    prepareForAudioTitle: "Prepare this song to enable separated audio.",
    hideLyricsTitle: "Hide synchronized lyrics.",
    showLyricsTitle: "Show synchronized lyrics.",
    addLyricsTitle: "Add or load lyrics, then prepare the song.",
    prepareBeforeSwitching: "Prepare this song before switching audio.",
    youtubeNotReady: "YouTube's player is not ready yet.",
    usingOriginalAudio: "Using original YouTube audio.",
    usingStem: "Using synchronized {stem}.",
    bothStemsOff: "Both stems are off.",
    separatedCouldNotStartRetry: "The separated audio could not start. Toggle a stem to try again.",
    separatedReadyToggle: "Separated audio is ready. Toggle a stem to switch from original audio.",
    separatedInterrupted: "Separated audio was interrupted. Using original YouTube audio.",
    separatedEndedEarly: "Separated audio ended early. Using original YouTube audio.",
    separatedAudioReadySync: "Separated audio ready. Synchronizing instrumental...",
    loadingSeparatedAudioPage: "Loading separated audio in the page...",
    separatedAudioLoadedPage: "Separated audio loaded in the page.",
    stemTrackFailedLoad: "The {stem} track failed to load.",
    stemTrackBackendFailed: "The {stem} track could not be loaded from the backend.",
    connecting: "Connecting...",
    connectingDownloader: "Connecting to the downloader...",
    couldNotStartDownloader: "Could not start the downloader.",
    couldNotStartTimingKaraokize: "Could not start lyric timing because Karaoke Machine failed to start.",
    cacheChecking: "Checking cache...",
    savedChecking: "Checking saved karaoke results...",
    cacheCheckFailedStillAvailable: "Could not check saved results. Karaoke Machine is still available.",
    savedLyricsSyncedReady: "Saved synchronized lyrics ready.",
    savedLyricsTextReady: "Saved lyrics text ready. Extract timings to show it.",
    cachedInstrumentalReady: "Cached instrumental ready.",
    savedLyricsReadyPrepareAudio: "Saved lyrics ready. Prepare audio.",
    prepareAudio: "Prepare audio.",
    lyricsTimingsExtracted: "Lyrics timings extracted.",
    couldNotExtractTimings: "Could not extract lyric timings.",
    lrclibLyricsLoaded: "LRCLIB lyrics loaded.",
    lrclibNoReliableMatch: "LRCLIB found no reliable match. You can enter lyrics manually.",
    lrclibSearchFailedManual: "LRCLIB search failed. You can enter lyrics manually.",
    lyricsAvailableRefining: "Lyrics available; refining timing after separation...",
    backendMissingTracks: "The backend did not return both separated audio tracks.",
    cachedSeparatedReady: "Cached separated audio ready.",
    cachedStemsLoading: "Cached stems ready. Loading synchronized audio...",
    separatedAudioReady: "Separated audio ready.",
    stemsLoading: "Stems ready. Loading synchronized audio...",
    stemsReady: "Stems ready.",
    checkedSavedResults: "Checked saved karaoke results.",
    separatingRoFormer: "Separating instrumental and vocals with RoFormer...",
    preparingRoFormer: "Preparing audio for RoFormer...",
    roformerSeparating: "RoFormer is separating vocals...",
    youtubeSignInRetry: "YouTube requested sign-in; retrying with Chrome cookies...",
    downloadingSourceAudio: "Downloading source audio...",
    downloadingOriginalTiming: "Downloading original audio for lyric timing...",
    aligningLyrics: "Aligning provided lyrics to the vocals...",
    detectingVocalActivity: "Detecting vocal activity with Silero VAD...",
    synchronizedLyricsReady: "Synchronized lyrics ready.",
    lyricsLoadedNoTimings: "Lyrics loaded without extracted timings.",
    downloadFailed: "Download failed.",
    processingLyrics: "Processing lyrics...",
    enterLyricsBeforeExtracting: "Enter or find lyrics before extracting timings.",
    startingTiming: "Starting lyric timing extraction...",
    extractingWith: "Extracting timings with {method} from {source}...",
    queuedTimingWithPrepare: "Queued lyric timing with Karaoke Machine...",
    willExtractTimings: "Will extract timings with {method} {schedule}...",
    willFindThenExtract: "Will find lyrics, then extract timings with {method} {schedule}...",
    karaokizeActive: "Karaoke Machine active",
    karaokizeIdle: "Karaoke Machine idle",
    navigationDetected: "YouTube navigation detected.",
    queueUpdated: "Queue updated",
    queueEmpty: "Queue empty",
    queuedTitle: "Queued: {title}",
    runningDownloadTitle: "Running download: {title}",
    runningSeparationTitle: "Running separation: {title}",
    runningConversionTitle: "Running conversion: {title}",
    connectingTitle: "Connecting: {title}",
    statusTitle: "{status}: {title}",
    processCache: "Cache",
    processQueue: "Queue",
    processKaraokize: "Karaoke Machine",
    processDownload: "Download",
    processSeparate: "Separate",
    processConvert: "Convert",
    processLrclib: "LRCLIB",
    processTiming: "Timing",
    processAudio: "Audio",
    active: "active",
    idle: "idle",
    event: "Event",
    phaseFinished: "{phase} finished.",
    timingMethodCtc: "CTC forced alignment",
    timingMethodSilero: "Silero VAD",
    timingSourceOriginal: "original audio",
    timingSourceVocal: "vocal stem",
    timingScheduleStemsFirst: "after stems",
    timingScheduleLyricsFirst: "before stems",
    timingScheduleParallel: "alongside stems",
    monitorDownloading: "Downloading...",
    monitorExtracting: "Extracting...",
    monitorQueued: "Queued...",
  },
  ja: {
    appName: APP_NAME_JA,
    appNameFull: `${APP_NAME} (${APP_NAME_JA})`,
    controlsAria: "カラオケ再生コントロール",
    lyricsEditorAria: "カラオケ歌詞エディター",
    controlsSectionAria: "カラオケコントロール",
    separatedTracksAria: "分離された音声トラック",
    toggleModeAria: "カラオケマシンモードを切り替え",
    openModeTitle: "カラオケマシンモードを開く",
    closeModeTitle: "カラオケマシンモードを閉じる",
    studioTitle: APP_NAME_JA,
    audioPreparation: "音声準備",
    instrumental: "インスト",
    vocals: "ボーカル",
    lyrics: "歌詞",
    lyricsUpper: "歌詞",
    lyricsInitialStatus: "LRCLIBで検索するか歌詞を入力して、タイミングを抽出します。",
    searchLrclib: "LRCLIB検索",
    searchingLrclib: "LRCLIBを検索中...",
    extractTimings: "タイミング抽出",
    extractingTimings: "タイミングを抽出中...",
    lyricsPlaceholder: "LRCLIBの歌詞がここに表示されます。歌詞を貼り付けたり入力したりもできます。",
    lyricsStyle: "歌詞スタイル",
    styleClassic: "クラシック",
    styleArcade: "アーケード",
    styleSimple: "シンプル",
    readyToPrepare: "この曲を準備できます。",
    karaokizeProgress: "カラオケマシンの進行状況",
    settings: "設定",
    settingsAria: "カラオケマシン設定",
    close: "閉じる",
    language: "言語",
    latencyCompensation: "遅延補正 (ms)",
    lyricsTimingOffset: "歌詞タイミング補正 (ms)",
    timingExtraction: "タイミング抽出",
    method: "方式",
    currentCtc: "現在 (CTC強制アライメント)",
    sileroVad: "Silero VAD",
    audioSource: "音声ソース",
    originalAudio: "元の音声",
    vocalStem: "ボーカルステム",
    pressMeOrder: "「押して」順序",
    stemsFirst: "ステムを先に",
    lyricsFirst: "歌詞を先に",
    runTogether: "同時に実行",
    defaultState: "既定の状態",
    keepAcrossSongs: "曲をまたいで保持",
    alwaysResetTo: "常に次にリセット:",
    diagnostics: "診断",
    debugConsole: "デバッグコンソール",
    debugLogAria: "カラオケマシンのデバッグログ",
    debugTitle: "カラオケマシン デバッグ",
    liveProcessTrace: "ライブ処理ログ",
    queue: "キュー",
    queueAria: "カラオケマシン処理キュー",
    youtubeSong: "YouTubeの曲",
    processingSong: "曲を処理中",
    queued: "待機中",
    processing: "処理中",
    loading: "読み込み中...",
    pressMe: "押して!",
    playing: "再生中",
    pause: "一時停止",
    readyBang: "準備完了!",
    pressMeTitle: "押すとこの曲を準備します。",
    preparationInProgress: "カラオケマシンで準備中です。",
    alreadyPrepared: "この曲は準備済みです。",
    enableStemTitle: "{stem}をオンにする。",
    disableStemTitle: "{stem}をオフにする。",
    prepareForAudioTitle: "分離音声を使うにはこの曲を準備してください。",
    hideLyricsTitle: "同期歌詞を隠す。",
    showLyricsTitle: "同期歌詞を表示する。",
    addLyricsTitle: "歌詞を追加または読み込んでから曲を準備してください。",
    prepareBeforeSwitching: "音声を切り替える前にこの曲を準備してください。",
    youtubeNotReady: "YouTubeプレーヤーはまだ準備できていません。",
    usingOriginalAudio: "元のYouTube音声を使用中です。",
    usingStem: "同期した{stem}を使用中です。",
    bothStemsOff: "両方のステムがオフです。",
    separatedCouldNotStartRetry: "分離音声を開始できませんでした。ステムを切り替えて再試行してください。",
    separatedReadyToggle: "分離音声の準備ができました。ステムを切り替えると元音声から変更できます。",
    separatedInterrupted: "分離音声が中断されました。元のYouTube音声を使用します。",
    separatedEndedEarly: "分離音声が早く終了しました。元のYouTube音声を使用します。",
    separatedAudioReadySync: "分離音声の準備完了。インストを同期中...",
    loadingSeparatedAudioPage: "ページ内で分離音声を読み込み中...",
    separatedAudioLoadedPage: "ページ内で分離音声を読み込みました。",
    stemTrackFailedLoad: "{stem}トラックの読み込みに失敗しました。",
    stemTrackBackendFailed: "{stem}トラックをバックエンドから読み込めませんでした。",
    connecting: "接続中...",
    connectingDownloader: "ダウンローダーに接続中...",
    couldNotStartDownloader: "ダウンローダーを開始できませんでした。",
    couldNotStartTimingKaraokize: "カラオケマシンの起動に失敗したため、歌詞タイミングを開始できませんでした。",
    cacheChecking: "キャッシュ確認中...",
    savedChecking: "保存済みのカラオケ結果を確認中...",
    cacheCheckFailedStillAvailable: "保存済み結果を確認できませんでした。カラオケマシンは引き続き使用できます。",
    savedLyricsSyncedReady: "保存済みの同期歌詞を使用できます。",
    savedLyricsTextReady: "保存済み歌詞テキストを使用できます。表示するにはタイミングを抽出してください。",
    cachedInstrumentalReady: "キャッシュ済みインストの準備完了。",
    savedLyricsReadyPrepareAudio: "保存済み歌詞があります。音声を準備してください。",
    prepareAudio: "音声を準備してください。",
    lyricsTimingsExtracted: "歌詞タイミングを抽出しました。",
    couldNotExtractTimings: "歌詞タイミングを抽出できませんでした。",
    lrclibLyricsLoaded: "LRCLIBの歌詞を読み込みました。",
    lrclibNoReliableMatch: "LRCLIBで信頼できる一致が見つかりませんでした。手動で歌詞を入力できます。",
    lrclibSearchFailedManual: "LRCLIB検索に失敗しました。手動で歌詞を入力できます。",
    lyricsAvailableRefining: "歌詞があります。分離後にタイミングを調整します...",
    backendMissingTracks: "バックエンドから両方の分離音声トラックが返されませんでした。",
    cachedSeparatedReady: "キャッシュ済み分離音声の準備完了。",
    cachedStemsLoading: "キャッシュ済みステムの準備完了。同期音声を読み込み中...",
    separatedAudioReady: "分離音声の準備完了。",
    stemsLoading: "ステムの準備完了。同期音声を読み込み中...",
    stemsReady: "ステムの準備完了。",
    checkedSavedResults: "保存済みカラオケ結果を確認しました。",
    separatingRoFormer: "RoFormerでインストとボーカルを分離中...",
    preparingRoFormer: "RoFormer用に音声を準備中...",
    roformerSeparating: "RoFormerがボーカルを分離中...",
    youtubeSignInRetry: "YouTubeがログインを要求しました。ChromeのCookieで再試行中...",
    downloadingSourceAudio: "元音声をダウンロード中...",
    downloadingOriginalTiming: "歌詞タイミング用の元音声をダウンロード中...",
    aligningLyrics: "入力された歌詞をボーカルに合わせています...",
    detectingVocalActivity: "Silero VADでボーカル活動を検出中...",
    synchronizedLyricsReady: "同期歌詞の準備完了。",
    lyricsLoadedNoTimings: "歌詞を読み込みましたが、タイミングは未抽出です。",
    downloadFailed: "ダウンロードに失敗しました。",
    processingLyrics: "歌詞を処理中...",
    enterLyricsBeforeExtracting: "タイミング抽出の前に歌詞を入力または検索してください。",
    startingTiming: "歌詞タイミング抽出を開始中...",
    extractingWith: "{source}から{method}でタイミングを抽出中...",
    queuedTimingWithPrepare: "カラオケマシンと一緒に歌詞タイミングをキューに追加しました...",
    willExtractTimings: "{method}で{schedule}タイミングを抽出します...",
    willFindThenExtract: "歌詞を検索してから、{method}で{schedule}タイミングを抽出します...",
    karaokizeActive: "カラオケマシン動作中",
    karaokizeIdle: "カラオケマシン待機中",
    navigationDetected: "YouTubeのナビゲーションを検出しました。",
    queueUpdated: "キューを更新しました",
    queueEmpty: "キューは空です",
    queuedTitle: "待機中: {title}",
    runningDownloadTitle: "ダウンロード中: {title}",
    runningSeparationTitle: "分離中: {title}",
    runningConversionTitle: "変換中: {title}",
    connectingTitle: "接続中: {title}",
    statusTitle: "{status}: {title}",
    processCache: "キャッシュ",
    processQueue: "キュー",
    processKaraokize: "カラオケマシン",
    processDownload: "ダウンロード",
    processSeparate: "分離",
    processConvert: "変換",
    processLrclib: "LRCLIB",
    processTiming: "タイミング",
    processAudio: "音声",
    active: "動作中",
    idle: "待機中",
    event: "イベント",
    phaseFinished: "{phase}完了。",
    timingMethodCtc: "CTC強制アライメント",
    timingMethodSilero: "Silero VAD",
    timingSourceOriginal: "元の音声",
    timingSourceVocal: "ボーカルステム",
    timingScheduleStemsFirst: "ステム後",
    timingScheduleLyricsFirst: "ステム前",
    timingScheduleParallel: "ステムと同時",
    monitorDownloading: "ダウンロード中...",
    monitorExtracting: "抽出中...",
    monitorQueued: "待機中...",
  },
  es: {
    appName: APP_NAME,
    appNameFull: APP_NAME,
    controlsAria: "Controles de reproducción de karaoke",
    lyricsEditorAria: "Editor de letras de karaoke",
    controlsSectionAria: "Controles de karaoke",
    separatedTracksAria: "Pistas de audio separadas",
    toggleModeAria: "Activar o desactivar Karaoke Machine",
    openModeTitle: "Abrir modo Karaoke Machine",
    closeModeTitle: "Cerrar modo Karaoke Machine",
    studioTitle: "Karaoke Machine!",
    audioPreparation: "Preparación de audio",
    instrumental: "Instrumental",
    vocals: "Voces",
    lyrics: "Letras",
    lyricsUpper: "LETRAS",
    lyricsInitialStatus: "Busca en LRCLIB o escribe la letra y luego extrae los tiempos.",
    searchLrclib: "Buscar en LRCLIB",
    searchingLrclib: "Buscando en LRCLIB...",
    extractTimings: "Extraer tiempos",
    extractingTimings: "Extrayendo tiempos...",
    lyricsPlaceholder: "Las letras de LRCLIB aparecerán aquí. También puedes pegarlas o escribirlas.",
    lyricsStyle: "Estilo de letras",
    styleClassic: "Clásico",
    styleArcade: "Arcade",
    styleSimple: "Simple",
    readyToPrepare: "Listo para preparar esta canción.",
    karaokizeProgress: "Progreso de Karaoke Machine",
    settings: "Configuración",
    settingsAria: "Configuración de Karaoke Machine",
    close: "Cerrar",
    language: "Idioma",
    latencyCompensation: "Compensación de latencia (ms)",
    lyricsTimingOffset: "Desfase de letras (ms)",
    timingExtraction: "Extracción de tiempos",
    method: "Método",
    currentCtc: "Actual (alineación forzada CTC)",
    sileroVad: "Silero VAD",
    audioSource: "Fuente de audio",
    originalAudio: "Audio original",
    vocalStem: "Pista vocal",
    pressMeOrder: "Orden de Presióname",
    stemsFirst: "Pistas primero",
    lyricsFirst: "Letras primero",
    runTogether: "Ejecutar juntos",
    defaultState: "Estado predeterminado",
    keepAcrossSongs: "Mantener entre canciones",
    alwaysResetTo: "Siempre restablecer a:",
    diagnostics: "Diagnóstico",
    debugConsole: "Consola de depuración",
    debugLogAria: "Registro de depuración de Karaoke Machine",
    debugTitle: "Depuración de Karaoke Machine",
    liveProcessTrace: "Traza de proceso en vivo",
    queue: "Cola",
    queueAria: "Cola de procesamiento de Karaoke Machine",
    youtubeSong: "Canción de YouTube",
    processingSong: "Procesando canción",
    queued: "En cola",
    processing: "Procesando",
    loading: "Cargando...",
    pressMe: "¡Presióname!",
    playing: "Reproduciendo",
    pause: "Pausa",
    readyBang: "¡Listo!",
    pressMeTitle: "Presiona para preparar esta canción.",
    preparationInProgress: "Karaoke Machine está preparando la canción.",
    alreadyPrepared: "Esta canción ya está preparada.",
    enableStemTitle: "Activar {stem}.",
    disableStemTitle: "Desactivar {stem}.",
    prepareForAudioTitle: "Prepara esta canción para activar el audio separado.",
    hideLyricsTitle: "Ocultar letras sincronizadas.",
    showLyricsTitle: "Mostrar letras sincronizadas.",
    addLyricsTitle: "Agrega o carga letras y luego prepara la canción.",
    prepareBeforeSwitching: "Prepara esta canción antes de cambiar el audio.",
    youtubeNotReady: "El reproductor de YouTube aún no está listo.",
    usingOriginalAudio: "Usando el audio original de YouTube.",
    usingStem: "Usando {stem} sincronizado.",
    bothStemsOff: "Ambas pistas están apagadas.",
    separatedCouldNotStartRetry: "No se pudo iniciar el audio separado. Cambia una pista para intentarlo de nuevo.",
    separatedReadyToggle: "El audio separado está listo. Cambia una pista para dejar el audio original.",
    separatedInterrupted: "El audio separado se interrumpió. Usando el audio original de YouTube.",
    separatedEndedEarly: "El audio separado terminó antes de tiempo. Usando el audio original de YouTube.",
    separatedAudioReadySync: "Audio separado listo. Sincronizando instrumental...",
    loadingSeparatedAudioPage: "Cargando audio separado en la página...",
    separatedAudioLoadedPage: "Audio separado cargado en la página.",
    stemTrackFailedLoad: "No se pudo cargar la pista {stem}.",
    stemTrackBackendFailed: "No se pudo cargar la pista {stem} desde el backend.",
    connecting: "Conectando...",
    connectingDownloader: "Conectando con el descargador...",
    couldNotStartDownloader: "No se pudo iniciar el descargador.",
    couldNotStartTimingKaraokize: "No se pudo iniciar el timing de letras porque Karaoke Machine no arrancó.",
    cacheChecking: "Revisando caché...",
    savedChecking: "Revisando resultados de karaoke guardados...",
    cacheCheckFailedStillAvailable: "No se pudieron revisar los resultados guardados. Karaoke Machine sigue disponible.",
    savedLyricsSyncedReady: "Letras sincronizadas guardadas listas.",
    savedLyricsTextReady: "Texto de letras guardado listo. Extrae los tiempos para mostrarlo.",
    cachedInstrumentalReady: "Instrumental en caché listo.",
    savedLyricsReadyPrepareAudio: "Letras guardadas listas. Prepara el audio.",
    prepareAudio: "Prepara el audio.",
    lyricsTimingsExtracted: "Tiempos de letras extraídos.",
    couldNotExtractTimings: "No se pudieron extraer los tiempos de letras.",
    lrclibLyricsLoaded: "Letras de LRCLIB cargadas.",
    lrclibNoReliableMatch: "LRCLIB no encontró una coincidencia confiable. Puedes escribir la letra manualmente.",
    lrclibSearchFailedManual: "Falló la búsqueda en LRCLIB. Puedes escribir la letra manualmente.",
    lyricsAvailableRefining: "Letras disponibles; refinando tiempos después de separar...",
    backendMissingTracks: "El backend no devolvió ambas pistas de audio separadas.",
    cachedSeparatedReady: "Audio separado en caché listo.",
    cachedStemsLoading: "Pistas en caché listas. Cargando audio sincronizado...",
    separatedAudioReady: "Audio separado listo.",
    stemsLoading: "Pistas listas. Cargando audio sincronizado...",
    stemsReady: "Pistas listas.",
    checkedSavedResults: "Resultados de karaoke guardados revisados.",
    separatingRoFormer: "Separando instrumental y voces con RoFormer...",
    preparingRoFormer: "Preparando audio para RoFormer...",
    roformerSeparating: "RoFormer está separando voces...",
    youtubeSignInRetry: "YouTube solicitó iniciar sesión; reintentando con cookies de Chrome...",
    downloadingSourceAudio: "Descargando audio fuente...",
    downloadingOriginalTiming: "Descargando audio original para tiempos de letras...",
    aligningLyrics: "Alineando la letra proporcionada con las voces...",
    detectingVocalActivity: "Detectando actividad vocal con Silero VAD...",
    synchronizedLyricsReady: "Letras sincronizadas listas.",
    lyricsLoadedNoTimings: "Letras cargadas sin tiempos extraídos.",
    downloadFailed: "La descarga falló.",
    processingLyrics: "Procesando letras...",
    enterLyricsBeforeExtracting: "Escribe o busca letras antes de extraer tiempos.",
    startingTiming: "Iniciando extracción de tiempos de letras...",
    extractingWith: "Extrayendo tiempos con {method} desde {source}...",
    queuedTimingWithPrepare: "Timing de letras en cola con Karaoke Machine...",
    willExtractTimings: "Se extraerán tiempos con {method} {schedule}...",
    willFindThenExtract: "Se buscarán letras y luego se extraerán tiempos con {method} {schedule}...",
    karaokizeActive: "Karaoke Machine activo",
    karaokizeIdle: "Karaoke Machine inactivo",
    navigationDetected: "Navegación de YouTube detectada.",
    queueUpdated: "Cola actualizada",
    queueEmpty: "Cola vacía",
    queuedTitle: "En cola: {title}",
    runningDownloadTitle: "Descargando: {title}",
    runningSeparationTitle: "Separando: {title}",
    runningConversionTitle: "Convirtiendo: {title}",
    connectingTitle: "Conectando: {title}",
    statusTitle: "{status}: {title}",
    processCache: "Caché",
    processQueue: "Cola",
    processKaraokize: "Karaoke Machine",
    processDownload: "Descarga",
    processSeparate: "Separación",
    processConvert: "Conversión",
    processLrclib: "LRCLIB",
    processTiming: "Timing",
    processAudio: "Audio",
    active: "activo",
    idle: "inactivo",
    event: "Evento",
    phaseFinished: "{phase} terminado.",
    timingMethodCtc: "alineación forzada CTC",
    timingMethodSilero: "Silero VAD",
    timingSourceOriginal: "audio original",
    timingSourceVocal: "pista vocal",
    timingScheduleStemsFirst: "después de las pistas",
    timingScheduleLyricsFirst: "antes de las pistas",
    timingScheduleParallel: "junto con las pistas",
    monitorDownloading: "Descargando...",
    monitorExtracting: "Extrayendo...",
    monitorQueued: "En cola...",
  },
};

const STATUS_TRANSLATIONS = {
  "Connecting to the downloader...": "connectingDownloader",
  "Cached stems ready. Loading synchronized audio...": "cachedStemsLoading",
  "Stems ready. Loading synchronized audio...": "stemsLoading",
  "Stems ready.": "stemsReady",
  "Checked saved karaoke results.": "checkedSavedResults",
  "Separating instrumental and vocals with RoFormer...": "separatingRoFormer",
  "Preparing audio for RoFormer...": "preparingRoFormer",
  "RoFormer is separating vocals...": "roformerSeparating",
  "YouTube requested sign-in; retrying with Chrome cookies...": "youtubeSignInRetry",
  "Downloading source audio...": "downloadingSourceAudio",
  "Downloading original audio for lyric timing...": "downloadingOriginalTiming",
  "Aligning provided lyrics to the vocals...": "aligningLyrics",
  "Detecting vocal activity with Silero VAD...": "detectingVocalActivity",
  "Queued behind another song.": "monitorQueued",
  "Waiting to start...": "queued",
  "Found cached separated stems.": "cachedSeparatedReady",
  "Legacy downloaded audio found. Extracting missing stems...": "monitorExtracting",
  "Preparing source audio for lyric timing...": "processingLyrics",
  "Searching LRCLIB for lyrics...": "searchingLrclib",
  "No lyrics were available for timing extraction.": "couldNotExtractTimings",
  "Enter lyrics before extracting lyric timings.": "enterLyricsBeforeExtracting",
  "Prepare this song before extracting lyric timings.": "prepareBeforeSwitching",
  "Karaokize this song before extracting lyric timings.": "prepareBeforeSwitching",
  "Waiting for Karaoke Machine! to prepare the vocal stem...": "processingLyrics",
  "Waiting for Karaokize to prepare the vocal stem...": "processingLyrics",
  "Timed out waiting for Karaoke Machine! to prepare the vocal stem.": "couldNotExtractTimings",
  "Timed out waiting for Karaokize to prepare the vocal stem.": "couldNotExtractTimings",
  "Karaoke Machine! did not produce a usable vocal stem.": "backendMissingTracks",
  "Karaokize did not produce a usable vocal stem.": "backendMissingTracks",
  "Using saved source audio for lyric timing...": "processingLyrics",
  "Using cached vocal stem for lyric timing...": "processingLyrics",
  "Compressing separated stems to MP3...": "monitorExtracting",
  "Download failed.": "downloadFailed",
  "LRCLIB search complete.": "lrclibLyricsLoaded",
};

function normalizeLanguage(value) {
  return LANGUAGES.has(value) ? value : DEFAULT_LANGUAGE;
}

function currentLanguage() {
  return normalizeLanguage(settings?.language);
}

function t(key, values = {}) {
  const dictionary = I18N[currentLanguage()] || I18N[DEFAULT_LANGUAGE];
  const fallback = I18N[DEFAULT_LANGUAGE][key] || key;
  return String(dictionary[key] || fallback).replace(/\{(\w+)\}/g, (_match, name) => {
    return Object.prototype.hasOwnProperty.call(values, name) ? String(values[name]) : `{${name}}`;
  });
}

function stemLabel(stem) {
  return stem === "vocals" ? t("vocals") : t("instrumental");
}

function timingMethodLabel(value) {
  if (normalizeTimingMethod(value) === "silero-vad") return t("timingMethodSilero");
  return t("timingMethodCtc");
}

function timingSourceLabel(value) {
  if (normalizeTimingSource(value) === "vocal-stem") return t("timingSourceVocal");
  return t("timingSourceOriginal");
}

function timingScheduleLabel(value) {
  const normalized = normalizeTimingSchedule(value);
  if (normalized === "lyrics-first") return t("timingScheduleLyricsFirst");
  if (normalized === "parallel") return t("timingScheduleParallel");
  return t("timingScheduleStemsFirst");
}

function localizeMessage(message) {
  const raw = String(message || "");
  const key = STATUS_TRANSLATIONS[raw];
  if (key) return t(key);
  let match = raw.match(/^Lyrics timings extracted with (.+) from (.+)\.$/);
  if (match) {
    return t("lyricsTimingsExtracted");
  }
  match = raw.match(/^(.+)\.\.\. (\d+(?:\.\d+)?%)$/);
  if (match) {
    const prefixKey = STATUS_TRANSLATIONS[`${match[1]}...`];
    return prefixKey ? `${t(prefixKey)} ${match[2]}` : raw;
  }
  match = raw.match(/^RoFormer is separating vocals\.\.\. (\d+)%/);
  if (match) return `${t("roformerSeparating")} ${match[1]}%`;
  return raw
    .replaceAll(APP_NAME, t("appName"))
    .replaceAll("DKaraoKe", t("appName"))
    .replaceAll("DKaraoke", t("appName"))
    .replaceAll("Karaokize", t("appName"));
}

function normalizeLyricsStyle(value) {
  return LYRICS_STYLES.has(value) ? value : DEFAULT_LYRICS_STYLE;
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

function getYouTubeVideo() {
  return document.querySelector("video.html5-main-video, #movie_player video");
}

function currentVideoId() {
  return new URL(location.href).searchParams.get("v") || "";
}

function currentSongTitle() {
  return document.querySelector("ytd-watch-metadata h1")?.textContent?.trim()
    || document.title.replace(/\s*-\s*YouTube\s*$/, "").trim();
}

function currentVideoDuration() {
  const duration = syncedVideo?.duration ?? getYouTubeVideo()?.duration;
  return Number.isFinite(duration) && duration > 0 ? duration : null;
}

function clampNumber(value, min, max, fallback) {
  const number = Number(value);
  if (!Number.isFinite(number)) return fallback;
  return Math.max(min, Math.min(max, number));
}
