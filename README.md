# Karaoke Machine! (カラオケマシン！)

![Logo-EN](km-en.png)
![Logo](km_transparent.png)

Turn *YouTube* into a *Karaoke Machine*!

Karaokizes _any_ existing song, by removing the Vocals and displaying the lyrics on screen.

Karaoke Machine! is a Windows-first Chrome MV3 extension with a local Python backend. It adds instrumental/vocal playback and timed lyrics to YouTube while keeping YouTube's video as the master clock.

## Install

`install.ps1` creates `.venv-tools`, installs or updates `yt-dlp` with its YouTube JavaScript solver, validates Node.js and FFmpeg, and registers the native host for the extension. Missing Node.js or FFmpeg dependencies are installed with `winget`; pass `-SkipFfmpegInstall` only when `ffmpeg` and `ffprobe` are already on `PATH`.

From this directory, install the backend and the RoFormer/CTC-alignment runtime:

```powershell
.\install.ps1
.\setup-roformer.ps1                    # CPU
# or: .\setup-roformer.ps1 -TorchBuild cu124
```

CUDA builds `cu121` and `cu124` are supported. The setup creates `.venv-roformer`, checks out the pinned RoFormer source, installs matching `torch` and `torchaudio` builds for CTC forced alignment, installs Silero VAD timing support, and downloads a verified 913 MB separation checkpoint. Interrupted checkpoint downloads resume when the script is rerun.

Then load the extension:

1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Choose **Load unpacked** and select this directory.
4. Restart Chrome if it was open during installation, then open a YouTube watch page.

Chrome loads the extension directly from this directory. After changing extension files, use **Reload** on `chrome://extensions` and refresh YouTube. The fixed manifest key keeps the unpacked extension ID consistent with the registered native host.

## Use

Press **K** beside the YouTube logo to open or close the karaoke workspace. On wide screens it places playback controls to the left of the video and the lyrics editor to the right.

Whenever a song opens, Karaoke Machine! checks local results automatically:

1. Cached local CTC-aligned lyrics and timing are loaded first.
2. Cached LRCLIB lyrics and line timing are used if local aligned results do not exist.
3. If both stems already exist, playback immediately switches to the instrumental stem.
4. The **Monitor** shows a red jagged star and **Press me!** while stems are missing.

Pressing the **Monitor** prepares the audio stems and starts the lyrics pipeline. Karaoke Machine! searches LRCLIB when the editor has no lyrics yet, then extracts refined timings using the configured timing source and Press me order.

The audio and lyrics pipelines are independently scheduled. LRCLIB search can
run while audio is downloading or separating. If **Extract timings** is pressed
while Karaoke Machine! is still preparing the same song and the timing source is the
vocal stem, the timing job waits for the stem and starts automatically when it
becomes available. Original audio is the default timing source and can start
without depending on stem extraction. To avoid GPU/CPU contention, Press me
uses **Lyrics first** by default; **Stems first** and **Run together** are
available in settings.

### Playback Controls

The left section contains a playful visual monitor and two audio toggle buttons:

- **Instrumental:** play the synchronized instrumental stem.
- **Vocals:** play the synchronized vocal stem.
- **Settings:** adjust latency compensation, lyric timing offset, the timing extraction method/source, the Press me ordering for original-audio timing, and whether audio/lyrics toggles persist across songs or reset to chosen defaults.

If a song is already processing, later **Monitor** clicks are queued in the background. A floating queue button appears in the lower-left corner while work is active; open it to see the current song and waiting songs.

### Lyrics Editor

The right section contains the lyrics editor. Its compact control section sits below the editor:

- **Lyrics:** show or hide synchronized lyrics over the video.
- **Lyrics style:** choose Classic, Arcade, or Simple. Classic is the default and shows a three-line window with the current line centered and scrolling upward on line changes.
- **Lyrics file bar:** choose between saved lyric files for the current video, or press the file-plus button to create a new editable file.
- **Save:** write the current editor text into the active lyric file. If the text changes from the version that produced saved timings, the timings are cleared so stale synchronization is not shown as valid.
- **Search LRCLIB:** find lyrics and synchronized line timing for the current song.
- **Extract timings:** use the selected timing extraction method and audio source to time the current editor text. Original audio is the default and downloads only the source audio needed for timing. Vocal stem mode uses the prepared vocals stem. CTC forced alignment can produce word timing when the aligner exposes character spans; otherwise timed lines are shown without synthetic word timing. Silero VAD produces line-level timing.

Lyrics search, extraction, and timing messages appear in the lyrics header; the left monitor remains dedicated to audio preparation and playback.

YouTube remains responsible for play, pause, seeking, playback speed, volume, buffering, ads, and navigation. Karaoke Machine! follows those changes and corrects small timing drift. If local stem playback is interrupted, it falls back to the original YouTube audio.

## Processing and cache behavior

Each video is stored separately under:

```text
%LOCALAPPDATA%\DKaraoKe\downloads\<video-id>\
```

Important cached files include:

```text
separated\mel_band_roformer\audio\instrumental.mp3
separated\mel_band_roformer\audio\vocals.mp3
lrclib_lyrics.json
lyrics.json
lyrics_files.json
lyrics_custom_<id>.json
```

The downloaded source audio is temporary. `yt-dlp` keeps the best available
audio in its original container, RoFormer consumes it, and the source is deleted
as soon as the stems are ready. The pipeline resumes from the best available
state:

- Both stems present: serve them without downloading or separating again.
- Legacy `audio.mp3` present but stems missing: use it once for separation, then delete it.
- Stems missing: download best audio with `yt-dlp` without an intermediate MP3 conversion, separate it, then delete the temporary source.
- LRCLIB line timing present: display it immediately.
- Local CTC, Silero VAD, or legacy Whisper timing present: use it as the timing authority.
- Custom lyric files are listed from `lyrics_files.json` and can be edited independently of the two legacy lyric caches.

The first CTC timing extraction downloads TorchAudio's MMS forced-alignment checkpoint into the standard Torch cache for the active user profile. Silero VAD is installed by `setup-roformer.ps1` and detects vocal activity locally.

## Local backend and privacy

The extension communicates with the registered `com.dkaraoke.downloader` native host. The host serves stems only through random tokenized `127.0.0.1` URLs with CORS and HTTP Range support; it does not expose a public network service.

Downloads are attempted anonymously first. If YouTube requires authentication, relevant YouTube/Google cookies are written to a temporary Netscape-format file for that attempt and deleted afterward. Cookies, native-message payloads, and local audio-server tokens are not written to the log.

LRCLIB receives the visible YouTube page title, a parsed artist when the title uses an `Artist - Song` pattern, and the local player duration for matching. The lyrics pipeline does not inspect YouTube metadata through `yt-dlp`. Audio processing, CTC forced alignment, and Silero VAD run locally.

## Troubleshooting

The backend writes a daily rotating log. The live file stays at:

```text
%LOCALAPPDATA%\DKaraoKe\dkaraoke.log
```

Old logs are kept for 30 days with date suffixes such as `dkaraoke.log.2026-06-26`.

Watch it while processing:

```powershell
Get-Content "$env:LOCALAPPDATA\DKaraoKe\dkaraoke.log" -Wait
```

Karaoke Machine! also appends warnings, errors, and recoverable oddities to a
human-readable diagnostics journal:

```text
%LOCALAPPDATA%\DKaraoKe\dkaraoke-diagnostics.log
```

Each line has a timestamp, severity, source, event, message, and safe context
such as job ID, video ID, or phase. The journal records every warning/error
diagnostic Karaoke Machine! emits; it is not limited to the visible debug panel or to
the most recent entries. Cookies, native-message payloads, and local
audio-server tokens are redacted.

Common recovery steps:

- **Native host unavailable:** rerun `.\install.ps1`, restart Chrome, and reload the extension.
- **RoFormer is not installed:** rerun `.\setup-roformer.ps1`; checkpoint downloads resume automatically.
- **FFmpeg not found:** ensure both `ffmpeg` and `ffprobe` are on `PATH`, then rerun `.\install.ps1`.
- **A prepared song behaves incorrectly:** remove only that video's cache directory and press the **Monitor** again.
- **Timings cannot be extracted:** try the default original-audio source, or prepare stems first when using vocal-stem timing. If Silero VAD is unavailable, rerun `.\setup-roformer.ps1`.

## Architecture

```text
YouTube
  src/content/
    -> Chrome runtime messages
  background.js
    -> native messaging: com.dkaraoke.downloader
  host/dkaraoke_host.py
    -> yt-dlp -> temporary source -> Mel-Band RoFormer -> CTC forced alignment
    -> LRCLIB lookup and per-video cache
    -> concurrent job dispatch; timing jobs may wait on same-video stems
    -> tokenized 127.0.0.1 stem server
  src/content/
    -> hidden HTMLAudioElement synchronized to YouTube <video>
```

RoFormer normalizes the temporary source to stereo 44.1 kHz float WAV, then
produces temporary WAV stems. The host converts both stems to 192 kbps stereo
MP3, verifies them, and removes both the WAV stems and downloaded source.
Existing cached WAV stems are migrated automatically when next used.

## Uninstall

Run the following to unregister the native host:

```powershell
.\uninstall.ps1
```

Then remove the unpacked extension from Chrome. Uninstalling does not delete the runtime folders or cached songs; remove those manually if they are no longer needed.
