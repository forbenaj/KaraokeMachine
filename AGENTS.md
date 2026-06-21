# AGENTS.md

## 先讀
先讀：`README.md` → `content.js` → `background.js` → `host/dkaraoke_host.py` → `manifest.json`/`install.ps1`/`styles.css`.

## 真
DKaraoKe：Windows-first Chrome MV3 extension + Python native host。Chrome 直載此 dir。

`Karaokize` 流：
已有非空 `audio.mp3` + `instrumental.wav` + `vocals.wav` → 直 serve。
僅有 `audio.mp3` → 不重下，重跑 separation。
無 → `yt-dlp` 下 bestaudio → `ffmpeg` 轉 `audio.mp3` → RoFormer 產兩 WAV。

UI：`Instrumental`、`Vocals`。
一開 → 播該 stem。皆開 → YouTube 原音。皆關 → silence。

## 架構
```text
YouTube
  content.js
    -> chrome.runtime dkaraoke-karaokize
  background.js
    -> nativeMessaging com.dkaraoke.downloader
  host/dkaraoke_host.py
    -> yt-dlp -> ffmpeg -> RoFormer
    -> 127.0.0.1 token HTTP serve WAV
  background.js
    -> dkaraoke-status
  content.js
    -> hidden HTMLAudioElement sync to <video>