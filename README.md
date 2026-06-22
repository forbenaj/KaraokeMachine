# DKaraoKe for YouTube

DKaraoKe is a Windows-first Chrome MV3 extension with a local Python backend. It adds synchronized instrumental/vocal playback and word-timed lyrics to YouTube while keeping YouTube's video as the master clock.

## Install

`install.ps1` creates `.venv-tools`, installs or updates `yt-dlp` with its YouTube JavaScript solver, validates Node.js and FFmpeg, and registers the native host for the extension. Missing Node.js or FFmpeg dependencies are installed with `winget`; pass `-SkipFfmpegInstall` only when `ffmpeg` and `ffprobe` are already on `PATH`.

From this directory, install the backend and the RoFormer/Whisper runtime:

```powershell
.\install.ps1
.\setup-roformer.ps1                    # CPU
# or: .\setup-roformer.ps1 -TorchBuild cu124
```

CUDA builds `cu121` and `cu124` are supported. The setup creates `.venv-roformer`, checks out the pinned RoFormer source, installs `whisper-timestamped`, and downloads a verified 913 MB separation checkpoint. Interrupted checkpoint downloads resume when the script is rerun.

Then load the extension:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select this directory.
4. Restart Chrome if it was open during installation, then open a YouTube watch page.

Chrome loads the extension directly from this directory. After changing extension files, use **Reload** on `chrome://extensions` and refresh YouTube. The fixed manifest key keeps the unpacked extension ID consistent with the registered native host.

## Use

Press **K** beside the YouTube logo to open or close the karaoke workspace. On wide screens it places playback controls to the left of the video and the lyrics editor to the right.

Whenever a song opens, DKaraoKe checks local results automatically:

1. Cached Whisper lyrics and word timing are loaded first.
2. Cached LRCLIB lyrics and provisional timing are used if Whisper results do not exist.
3. If the MP3 and both stems already exist, playback immediately switches to the instrumental stem.
4. **Karaokize!** is enabled only while lyrics or stems are missing.

Pressing **Karaokize!** starts the missing work. If lyrics are absent, LRCLIB lookup runs alongside audio download/separation and its synchronized lyrics appear as soon as they arrive. Stems are published as soon as RoFormer finishes. Whisper then analyzes the vocal stem and automatically replaces LRCLIB's provisional timing with refined word timing.

### Playback Controls

The left section contains a playful visual monitor and two audio toggle buttons:

- **Instrumental:** play the synchronized instrumental stem.
- **Voice only:** play the synchronized vocal stem.

### Lyrics Editor

The right section contains the lyrics editor. Its compact control section sits below the editor:

- **Lyrics:** show or hide synchronized lyrics over the video.
- **Lyrics style:** choose the original arcade treatment or a simpler subtitle treatment.
- **Refresh lyrics:** rebuild Whisper timing for edited or pasted lyrics using the existing vocal stem.

Lyrics search, extraction, and timing messages appear in the lyrics header; the left monitor remains dedicated to audio preparation and playback.

YouTube remains responsible for play, pause, seeking, playback speed, volume, buffering, ads, and navigation. DKaraoKe follows those changes and corrects small timing drift. If local stem playback is interrupted, it falls back to the original YouTube audio.

## Processing and cache behavior

Each video is stored separately under:

```text
%LOCALAPPDATA%\DKaraoKe\downloads\<video-id>\
```

Important cached files include:

```text
audio.mp3
separated\mel_band_roformer\audio\instrumental.mp3
separated\mel_band_roformer\audio\vocals.mp3
lrclib_lyrics.json
lyrics.json
```

The pipeline resumes from the best available state:

- MP3 and both stems present: serve them without downloading or separating again.
- Only the MP3 present: rerun separation without redownloading.
- No MP3 present: download best audio with `yt-dlp`, convert it to MP3, then separate it.
- LRCLIB timing present: display it immediately while waiting for Whisper.
- Whisper timing present: use it as the timing authority.

The default Whisper model is `small` and downloads on its first timing run. Set `DKARAOKE_WHISPER_MODEL` before starting Chrome to select another model.

## Local backend and privacy

The extension communicates with the registered `com.dkaraoke.downloader` native host. The host serves stems only through random tokenized `127.0.0.1` URLs with CORS and HTTP Range support; it does not expose a public network service.

Downloads are attempted anonymously first. If YouTube requires authentication, relevant YouTube/Google cookies are written to a temporary Netscape-format file for that attempt and deleted afterward. Cookies, native-message payloads, and local audio-server tokens are not written to the log.

LRCLIB receives the detected song title, artist, and duration for matching. Audio processing and Whisper transcription run locally.

## Troubleshooting

The backend writes a rotating log, retaining up to four 5 MB files:

```text
%LOCALAPPDATA%\DKaraoKe\dkaraoke.log
```

Watch it while processing:

```powershell
Get-Content "$env:LOCALAPPDATA\DKaraoKe\dkaraoke.log" -Wait
```

Common recovery steps:

- **Native host unavailable:** rerun `.\install.ps1`, restart Chrome, and reload the extension.
- **RoFormer is not installed:** rerun `.\setup-roformer.ps1`; checkpoint downloads resume automatically.
- **FFmpeg not found:** ensure both `ffmpeg` and `ffprobe` are on `PATH`, then rerun `.\install.ps1`.
- **A prepared song behaves incorrectly:** remove only that video's cache directory and press **Karaokize!** again.
- **Edited lyrics cannot be refreshed:** prepare the stems first; refresh timing requires an existing vocal stem.

## Architecture

```text
YouTube
  content.js
    -> Chrome runtime messages
  background.js
    -> native messaging: com.dkaraoke.downloader
  host/dkaraoke_host.py
    -> yt-dlp -> FFmpeg -> Mel-Band RoFormer -> Whisper
    -> LRCLIB lookup and per-video cache
    -> tokenized 127.0.0.1 stem server
  content.js
    -> hidden HTMLAudioElement synchronized to YouTube <video>
```

RoFormer produces temporary stereo 44.1 kHz float WAV files. The host converts both stems to 192 kbps stereo MP3, verifies them, and then removes the WAV files. Existing cached WAV stems are migrated automatically when next used.

## Uninstall

Run the following to unregister the native host:

```powershell
.\uninstall.ps1
```

Then remove the unpacked extension from Chrome. Uninstalling does not delete the runtime folders or cached songs; remove those manually if they are no longer needed.
