# AGENTS.md

## 先讀
先讀：`README.md` → `src/content/` → `background.js` → `host/dkaraoke_host.py` → `manifest.json`/`install.ps1`/`styles/`。

## 真
DKaraoKe：Windows-first Chrome MV3 extension + Python native host。Chrome 直載此 dir。

`Karaokize` 流：
已有非空 `instrumental.mp3` + `vocals.mp3` → 直 serve。
僅有舊 `audio.mp3` → 不重下，重跑 separation，成功後刪除。
無 stems → `yt-dlp` 下原格式 bestaudio 到 temp → RoFormer 產兩 WAV → 轉兩 MP3 → 刪 source/WAV。

UI：`Instrumental`、`Vocals`。
一開 → 播該 stem。皆開 → YouTube 原音。皆關 → silence。

## assets
Chrome icons 留在 `icons/`。
content script 可取用 SVG 在 `assets/extension/`，需同步 `manifest.json` `web_accessible_resources`。
README/landing 品牌圖在 `assets/brand/`，截圖在 `assets/screenshots/`。

## 架構
```text
YouTube
  src/content/
    -> chrome.runtime dkaraoke-karaokize
  background.js
    -> nativeMessaging com.dkaraoke.downloader
  host/dkaraoke_host.py
    -> yt-dlp -> ffmpeg -> RoFormer
    -> 127.0.0.1 token HTTP serve MP3 stems
  background.js
    -> dkaraoke-status
  src/content/
    -> hidden HTMLAudioElement sync to <video>
```
