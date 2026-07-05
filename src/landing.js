(() => {
    const DEMO = {
    lyricsUrl: "demo/m46M9B4tfYk/lyrics.json",
    instrumentalUrl: "demo/m46M9B4tfYk/separated/mel_band_roformer/audio/instrumental.mp3",
    vocalsUrl: "demo/m46M9B4tfYk/separated/mel_band_roformer/audio/vocals.mp3"
    };

    const YOUTUBE_STATE = {
    UNSTARTED: -1,
    PLAYING: 1
    };
    const HARD_SYNC_SECONDS = 0.35;
    const SOFT_SYNC_SECONDS = 0.08;
    const MAX_RATE_CORRECTION = 0.04;
    const SYNC_INTERVAL_MS = 240;
    const DEMO_START_SECONDS = 45;

    const state = {
    instrumental: true,
    vocals: true,
    lyrics: true,
    lyricsReady: false,
    playerReady: false,
    youtubeState: YOUTUBE_STATE.UNSTARTED,
    activeSegmentIndex: -1
    };

    let player = null;
    let lyricsData = { text: "", segments: [] };
    let syncTimer = null;
    let lyricFrame = null;
    let renderedLyricSegment = null;
    let renderedClassicSegmentIndex = -1;
    let pendingTryMePlay = false;
    const classicGraphemeSegmenter = typeof Intl !== "undefined" && typeof Intl.Segmenter === "function"
    ? new Intl.Segmenter(undefined, { granularity: "grapheme" })
    : null;

    const buttons = document.querySelectorAll("[data-toggle]");
    const lyricsOverlay = document.getElementById("dkaraoke-lyrics-overlay");
    const silenceCurtain = document.getElementById("silence-curtain");
    const styleSelect = document.getElementById("lyric-style");
    const lyricsText = document.querySelector(".lyrics-body textarea");
    const lyricsName = document.querySelector(".lyrics-name input");
    const tryMeStar = document.getElementById("try-me-star");
    const stemAudio = {
    instrumental: new Audio(DEMO.instrumentalUrl),
    vocals: new Audio(DEMO.vocalsUrl)
    };

    for (const audio of Object.values(stemAudio)) {
    audio.preload = "auto";
    }

    function selectedStemCount() {
    return Number(state.instrumental) + Number(state.vocals);
    }

    function sourceMode() {
    const count = selectedStemCount();
    if (count === 2) return "original";
    if (count === 1) return "custom";
    return "silent";
    }

    function isPlayerPlaying() {
    return state.youtubeState === YOUTUBE_STATE.PLAYING;
    }

    function currentVideoTime() {
    if (!player || !state.playerReady || typeof player.getCurrentTime !== "function") return 0;
    const time = Number(player.getCurrentTime());
    return Number.isFinite(time) ? Math.max(0, time) : 0;
    }

    function currentPlaybackRate() {
    if (!player || !state.playerReady || typeof player.getPlaybackRate !== "function") return 1;
    const rate = Number(player.getPlaybackRate());
    return Number.isFinite(rate) && rate > 0 ? rate : 1;
    }

    function activeStemAudio() {
    if (sourceMode() !== "custom") return [];
    return Object.entries(stemAudio)
        .filter(([stem]) => state[stem])
        .map(([, audio]) => audio);
    }

    function pauseStemAudio() {
    stopSyncTimer();
    for (const audio of Object.values(stemAudio)) {
        audio.pause();
        audio.playbackRate = 1;
    }
    }

    function syncStemAudio(force = false) {
    const target = currentVideoTime();
    const rate = currentPlaybackRate();
    const activeAudio = new Set(activeStemAudio());

    for (const [stem, audio] of Object.entries(stemAudio)) {
        if (!activeAudio.has(audio)) {
        audio.pause();
        continue;
        }
        const duration = Number.isFinite(audio.duration) ? audio.duration : Infinity;
        const nextTime = Math.min(target, duration);
        const drift = audio.currentTime - nextTime;
        const absoluteDrift = Math.abs(drift);
        if (force || absoluteDrift >= HARD_SYNC_SECONDS) {
        audio.currentTime = nextTime;
        audio.playbackRate = rate;
        } else if (absoluteDrift >= SOFT_SYNC_SECONDS) {
        const correction = Math.max(-MAX_RATE_CORRECTION, Math.min(MAX_RATE_CORRECTION, -drift * 0.25));
        audio.playbackRate = Math.max(0.25, Math.min(4, rate * (1 + correction)));
        } else {
        audio.playbackRate = rate;
        }
    }
    }

    function startSyncTimer() {
    if (syncTimer !== null) return;
    syncTimer = window.setInterval(() => {
        if (sourceMode() !== "custom" || !isPlayerPlaying()) return;
        syncStemAudio();
    }, SYNC_INTERVAL_MS);
    }

    function stopSyncTimer() {
    if (syncTimer === null) return;
    window.clearInterval(syncTimer);
    syncTimer = null;
    }

    function playActiveStemAudio() {
    const activeAudio = activeStemAudio();
    if (!activeAudio.length || !isPlayerPlaying()) return;
    syncStemAudio(true);
    Promise.all(activeAudio.map((audio) => audio.play()))
        .then(startSyncTimer)
        .catch(() => {});
    }

    function setYouTubeMuted(muted) {
    if (!player || !state.playerReady) return;
    if (muted && typeof player.mute === "function") player.mute();
    if (!muted && typeof player.unMute === "function") player.unMute();
    }

    function applyAudioMode(options = {}) {
    const mode = sourceMode();
    if (mode === "original") {
        pauseStemAudio();
        setYouTubeMuted(options.keepYouTubeMuted === true);
    } else {
        setYouTubeMuted(true);
        if (mode === "silent") {
        pauseStemAudio();
        } else {
        syncStemAudio(true);
        playActiveStemAudio();
        }
    }
    renderState();
    }

    function normalizeSegment(segment, index) {
    const start = Number(segment?.start_time);
    const end = Number(segment?.end_time);
    return {
        id: segment?.id || `segment-${index}`,
        text: String(segment?.text || "").trim(),
        start_time: Number.isFinite(start) ? start : 0,
        end_time: Number.isFinite(end) ? end : Number.isFinite(start) ? start + 2 : 2,
        words: Array.isArray(segment?.words) ? segment.words.map((word, wordIndex) => {
        const wordStart = Number(word?.start_time);
        const wordEnd = Number(word?.end_time);
        return {
            id: word?.id || `word-${index}-${wordIndex}`,
            text: String(word?.text || ""),
            start_time: Number.isFinite(wordStart) ? wordStart : start,
            end_time: Number.isFinite(wordEnd) ? wordEnd : end
        };
        }).filter((word) => word.text) : []
    };
    }

    async function loadLyrics() {
    try {
        const response = await fetch(DEMO.lyricsUrl);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = await response.json();
        lyricsData = {
        ...data,
        text: String(data?.text || ""),
        segments: Array.isArray(data?.segments) ? data.segments.map(normalizeSegment) : []
        };
        state.lyricsReady = lyricsData.segments.length > 0;
        if (lyricsText) lyricsText.value = lyricsData.text || lyricsData.segments.map((segment) => segment.text).join("\n");
        if (lyricsName) lyricsName.value = `${lyricsData.label || "CTC"} timed lyrics`;
    } catch (_error) {
        state.lyricsReady = false;
        if (lyricsText) lyricsText.value = "Timed lyrics could not be loaded.";
        lyricsOverlay.replaceChildren(document.createTextNode("Timed lyrics could not be loaded."));
    }
    renderState();
    }

    function activeLyricSegmentIndex(time) {
    const segments = lyricsData.segments || [];
    let index = segments.findIndex((segment) =>
        time >= Number(segment.start_time) && time <= Number(segment.end_time)
    );
    if (index >= 0) return index;
    index = segments.findIndex((segment) =>
        time >= Number(segment.start_time) - 0.35 && time <= Number(segment.end_time) + 0.6
    );
    return index;
    }

    function classicLineText(segment) {
    if (typeof segment?.text === "string" && segment.text.trim()) return segment.text.trim();
    if (Array.isArray(segment?.words)) {
        const text = segment.words.map((word) => word?.text || "").join(" ").trim();
        if (text) return text;
    }
    return "\u00a0";
    }

    function lyricWords(segment) {
    return Array.isArray(segment?.words) ? segment.words : [];
    }

    function splitClassicLetters(text) {
    const value = String(text || "");
    if (!value) return [];
    if (classicGraphemeSegmenter) {
        return Array.from(classicGraphemeSegmenter.segment(value), (part) => part.segment);
    }
    return Array.from(value);
    }

    function getClassicWordSpan(word, fallbackStart, fallbackEnd) {
    const start = Number.isFinite(Number(word?.start_time)) ? Number(word.start_time) : fallbackStart;
    const end = Number.isFinite(Number(word?.end_time)) ? Number(word.end_time) : fallbackEnd;
    return {
        start: Math.max(0, start),
        end: Math.max(Math.max(0, start) + 0.02, end)
    };
    }

    function buildClassicWord(word, wordIndex) {
    const wordEl = document.createElement("span");
    wordEl.className = "dkaraoke-classic-word";
    wordEl.dataset.wordIndex = String(wordIndex);
    wordEl.dataset.wordText = String(word?.text || "");

    const span = getClassicWordSpan(word, 0, 0.02);
    wordEl.dataset.start = String(span.start);
    wordEl.dataset.end = String(span.end);

    const letters = splitClassicLetters(word?.text || "");
    if (!letters.length) {
        wordEl.textContent = word?.text || "";
        return wordEl;
    }

    const duration = Math.max(0.02, span.end - span.start);
    const step = duration / letters.length;
    letters.forEach((letter, letterIndex) => {
        const letterEl = document.createElement("span");
        letterEl.className = "dkaraoke-classic-letter";
        letterEl.textContent = letter;
        const letterStart = span.start + step * letterIndex;
        const letterEnd = letterIndex === letters.length - 1
        ? span.end
        : Math.min(span.end, letterStart + step);
        letterEl.dataset.start = String(letterStart);
        letterEl.dataset.end = String(letterEnd);
        wordEl.appendChild(letterEl);
    });
    return wordEl;
    }

    function buildClassicLine(segment, role, segmentIndex) {
    const line = document.createElement("div");
    line.className = `dkaraoke-classic-line is-${role}`;
    line.dataset.role = role;
    line.dataset.segmentIndex = String(segmentIndex);
    const words = lyricWords(segment);
    if (!segment || !words.length) {
        line.classList.add("is-empty");
        line.textContent = classicLineText(segment);
        return line;
    }

    words.forEach((word, index) => {
        line.appendChild(buildClassicWord(word, index));
        if (index < words.length - 1) {
        line.appendChild(document.createTextNode(" "));
        }
    });
    return line;
    }

    function buildClassicStack(segmentIndex) {
    const stack = document.createElement("div");
    stack.className = "dkaraoke-classic-stack";
    for (const [offset, position] of [[-1, "previous"], [0, "current"], [1, "next"]]) {
        stack.appendChild(buildClassicLine(lyricsData.segments[segmentIndex + offset], position, segmentIndex + offset));
    }
    return stack;
    }

    function restartClassicAdvanceAnimation() {
    lyricsOverlay.classList.remove("is-classic-advancing");
    void lyricsOverlay.offsetWidth;
    lyricsOverlay.classList.add("is-classic-advancing");
    }

    function updateClassicWordState(wordEl, word, lyricTime, role) {
    if (!wordEl || !word) return;
    const start = Number(wordEl.dataset.start) || 0;
    const end = Number(wordEl.dataset.end) || start + 0.02;
    const wordSung = lyricTime >= end;
    const wordCurrent = lyricTime >= start && lyricTime < end;

    wordEl.classList.toggle("is-sung", role === "previous" || wordSung);
    wordEl.classList.toggle("is-current", role === "current" && wordCurrent);

    const letterEls = wordEl.querySelectorAll(".dkaraoke-classic-letter");
    letterEls.forEach((letterEl) => {
        const letterStart = Number(letterEl.dataset.start) || start;
        const letterEnd = Number(letterEl.dataset.end) || end;
        const letterSung = lyricTime >= letterEnd;
        const letterCurrent = lyricTime >= letterStart && lyricTime < letterEnd;

        letterEl.classList.toggle("is-sung", role === "previous" || letterSung);
        letterEl.classList.toggle("is-current", role === "current" && letterCurrent);
    });
    }

    function updateClassicLineState(lineEl, segment, role, lyricTime) {
    if (!lineEl) return;
    lineEl.classList.toggle("is-previous", role === "previous");
    lineEl.classList.toggle("is-current", role === "current");
    lineEl.classList.toggle("is-next", role === "next");
    lineEl.classList.toggle("is-empty", !segment);
    lineEl.dataset.role = role;
    const words = lyricWords(segment);
    if (!segment || !words.length) return;

    const wordEls = lineEl.querySelectorAll(".dkaraoke-classic-word");
    wordEls.forEach((wordEl, index) => {
        updateClassicWordState(wordEl, words[index], lyricTime, role);
    });
    }

    function updateClassicOverlayState(lyricTime, segmentIndex) {
    const lineEls = lyricsOverlay.querySelectorAll(".dkaraoke-classic-line");
    if (!lineEls.length) return;
    lineEls.forEach((lineEl, offset) => {
        const role = offset === 0 ? "previous" : offset === 1 ? "current" : "next";
        const segment = lyricsData.segments[segmentIndex + offset - 1];
        updateClassicLineState(lineEl, segment, role, lyricTime);
    });
    }

    function renderClassicLyricsFrame(segmentIndex, lyricTime) {
    const currentSegment = segmentIndex >= 0 ? lyricsData.segments[segmentIndex] : null;
    if (!currentSegment) {
        lyricsOverlay.hidden = true;
        renderedClassicSegmentIndex = -1;
        state.activeSegmentIndex = -1;
        return;
    }

    lyricsOverlay.hidden = false;
    state.activeSegmentIndex = segmentIndex;
    if (renderedClassicSegmentIndex !== segmentIndex) {
        lyricsOverlay.replaceChildren(buildClassicStack(segmentIndex));
        renderedClassicSegmentIndex = segmentIndex;
        restartClassicAdvanceAnimation();
    }
    updateClassicOverlayState(lyricTime, segmentIndex);
    }

    function renderNonClassicLyricsFrame(segment, lyricTime) {
    if (!segment) {
        lyricsOverlay.hidden = true;
        renderedLyricSegment = null;
        state.activeSegmentIndex = -1;
        return;
    }

    lyricsOverlay.hidden = false;
    const words = lyricWords(segment);
    if (renderedLyricSegment !== segment) {
        const spans = words.length ? words.map((word) => {
        const span = document.createElement("span");
        span.textContent = `${word.text} `;
        return span;
        }) : [document.createElement("span")];
        if (!words.length) spans[0].textContent = classicLineText(segment);
        lyricsOverlay.replaceChildren(...spans);
        renderedLyricSegment = segment;
    }

    if (words.length) {
        words.forEach((word, index) => {
        const element = lyricsOverlay.children[index];
        if (!element) return;
        element.classList.toggle("is-sung", lyricTime >= word.end_time);
        element.classList.toggle("is-current", lyricTime >= word.start_time && lyricTime < word.end_time);
        });
    } else if (lyricsOverlay.firstElementChild) {
        lyricsOverlay.firstElementChild.classList.toggle("is-sung", false);
        lyricsOverlay.firstElementChild.classList.toggle("is-current", true);
    }
    }

    function resetLyricRenderCache() {
    renderedLyricSegment = null;
    renderedClassicSegmentIndex = -1;
    lyricsOverlay.classList.remove("is-classic-advancing");
    }

    function renderLyricFrame() {
    lyricFrame = window.requestAnimationFrame(renderLyricFrame);
    if (!state.lyrics || !state.lyricsReady) {
        lyricsOverlay.hidden = true;
        return;
    }

    const time = currentVideoTime();
    const index = activeLyricSegmentIndex(time);
    const segment = index >= 0 ? lyricsData.segments[index] : null;
    if (styleSelect.value === "classic") {
        renderedLyricSegment = null;
        renderClassicLyricsFrame(index, time);
    } else {
        renderedClassicSegmentIndex = -1;
        lyricsOverlay.classList.remove("is-classic-advancing");
        state.activeSegmentIndex = index;
        renderNonClassicLyricsFrame(segment, time);
    }
    }

    function renderState() {
    buttons.forEach((button) => {
        const key = button.dataset.toggle;
        button.setAttribute("aria-pressed", String(Boolean(state[key])));
    });

    lyricsOverlay.dataset.style = styleSelect.value;
    lyricsOverlay.hidden = !state.lyrics || !state.lyricsReady || state.activeSegmentIndex < 0;
    silenceCurtain.hidden = sourceMode() !== "silent";
    }

    function hideTryMeStar() {
    if (!tryMeStar) return;
    tryMeStar.classList.add("is-playing");
    tryMeStar.disabled = true;
    }

    function onPlayerReady() {
    state.playerReady = true;
    if (typeof player?.seekTo === "function") player.seekTo(DEMO_START_SECONDS, true);
    renderState();
    applyAudioMode();
    if (Number(player?.getPlayerState?.()) === YOUTUBE_STATE.PLAYING) hideTryMeStar();
    if (pendingTryMePlay) playDemo();
    }

    function onPlayerStateChange(event) {
    state.youtubeState = Number(event?.data);
    if (isPlayerPlaying()) {
        hideTryMeStar();
        playActiveStemAudio();
    } else {
        stopSyncTimer();
        for (const audio of Object.values(stemAudio)) audio.pause();
    }
    renderState();
    }

    function onPlaybackRateChange() {
    syncStemAudio(true);
    }

    function playDemo() {
    pendingTryMePlay = true;
    if (!player || !state.playerReady || typeof player.playVideo !== "function") return;
    pendingTryMePlay = false;
    player.playVideo();
    hideTryMeStar();
    }

    buttons.forEach((button) => {
    button.addEventListener("click", () => {
        const key = button.dataset.toggle;
        state[key] = !state[key];
        if (key === "lyrics") {
        resetLyricRenderCache();
        state.activeSegmentIndex = -2;
        }
        applyAudioMode();
    });
    });

    styleSelect.addEventListener("change", () => {
    lyricsOverlay.dataset.style = styleSelect.value;
    resetLyricRenderCache();
    state.activeSegmentIndex = -2;
    renderState();
    });

    tryMeStar?.addEventListener("click", playDemo);

    window.onYouTubeIframeAPIReady = () => {
    player = new YT.Player("youtube-player", {
        events: {
        onReady: onPlayerReady,
        onStateChange: onPlayerStateChange,
        onPlaybackRateChange
        }
    });
    };

    function loadYouTubeApi() {
    if (window.YT?.Player) {
        window.onYouTubeIframeAPIReady();
        return;
    }
    const script = document.createElement("script");
    script.src = "https://www.youtube.com/iframe_api";
    document.head.appendChild(script);
    }

    loadLyrics();
    renderLyricFrame();
    renderState();
    loadYouTubeApi();

    window.addEventListener("pagehide", () => {
    pauseStemAudio();
    if (lyricFrame !== null) window.cancelAnimationFrame(lyricFrame);
    });
})();
