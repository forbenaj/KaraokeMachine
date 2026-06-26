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
3. If both stems already exist, playback immediately switches to the instrumental stem.
4. **Karaokize!** is enabled only while stems are missing.

Pressing **Karaokize!** prepares only the audio stems. Lyrics are separate, explicit processes in the lyrics editor: search LRCLIB for text, then extract refined word timings from the prepared vocal stem.

The audio and lyrics pipelines are independently scheduled. LRCLIB search can
run while audio is downloading or separating. If **Extract timings** is pressed
while Karaokize is still preparing the same song, the timing job waits for the
vocal stem and starts automatically when it becomes available.

### Playback Controls

The left section contains a playful visual monitor and two audio toggle buttons:

- **Instrumental:** play the synchronized instrumental stem.
- **Vocals:** play the synchronized vocal stem.
- **Settings:** adjust latency compensation, lyric timing offset, and whether audio/lyrics toggles persist across songs or reset to chosen defaults.

If a song is already processing, later **Karaokize!** requests are queued in the background. A floating queue button appears in the lower-left corner while work is active; open it to see the current song and waiting songs.

### Lyrics Editor

The right section contains the lyrics editor. Its compact control section sits below the editor:

- **Lyrics:** show or hide synchronized lyrics over the video.
- **Lyrics style:** choose the original arcade treatment or a simpler subtitle treatment.
- **Search LRCLIB:** find lyrics and provisional synchronized timing for the current song.
- **Extract timings:** use Whisper on the existing vocal stem to build refined word timing for the current editor text.

Lyrics search, extraction, and timing messages appear in the lyrics header; the left monitor remains dedicated to audio preparation and playback.

YouTube remains responsible for play, pause, seeking, playback speed, volume, buffering, ads, and navigation. DKaraoKe follows those changes and corrects small timing drift. If local stem playback is interrupted, it falls back to the original YouTube audio.

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
```

The downloaded source audio is temporary. `yt-dlp` keeps the best available
audio in its original container, RoFormer consumes it, and the source is deleted
as soon as the stems are ready. The pipeline resumes from the best available
state:

- Both stems present: serve them without downloading or separating again.
- Legacy `audio.mp3` present but stems missing: use it once for separation, then delete it.
- Stems missing: download best audio with `yt-dlp` without an intermediate MP3 conversion, separate it, then delete the temporary source.
- LRCLIB timing present: display it immediately.
- Whisper timing present: use it as the timing authority.

The default Whisper model is `small` and downloads on its first timing run. Set `DKARAOKE_WHISPER_MODEL` before starting Chrome to select another model.

## Local backend and privacy

The extension communicates with the registered `com.dkaraoke.downloader` native host. The host serves stems only through random tokenized `127.0.0.1` URLs with CORS and HTTP Range support; it does not expose a public network service.

Downloads are attempted anonymously first. If YouTube requires authentication, relevant YouTube/Google cookies are written to a temporary Netscape-format file for that attempt and deleted afterward. Cookies, native-message payloads, and local audio-server tokens are not written to the log.

LRCLIB receives the detected song title, artist, and duration for matching. Audio processing and Whisper transcription run locally.

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

Common recovery steps:

- **Native host unavailable:** rerun `.\install.ps1`, restart Chrome, and reload the extension.
- **RoFormer is not installed:** rerun `.\setup-roformer.ps1`; checkpoint downloads resume automatically.
- **FFmpeg not found:** ensure both `ffmpeg` and `ffprobe` are on `PATH`, then rerun `.\install.ps1`.
- **A prepared song behaves incorrectly:** remove only that video's cache directory and press **Karaokize!** again.
- **Timings cannot be extracted:** prepare the stems first; timing extraction requires an existing vocal stem.

## Architecture

```text
YouTube
  src/content/
    -> Chrome runtime messages
  background.js
    -> native messaging: com.dkaraoke.downloader
  host/dkaraoke_host.py
    -> yt-dlp -> temporary source -> Mel-Band RoFormer -> Whisper
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
