# Karaoke Machine! (カラオケマシン！)

![Logo-EN](assets/brand/km-en.png)
![Logo](assets/brand/km_transparent.png)

Turn *YouTube* into a *Karaoke Machine*!

Karaokizes _any_ existing song, by removing the Vocals and displaying the lyrics on screen.

Karaoke Machine! is a Windows-first Chrome MV3 extension with a local Python backend. It adds instrumental/vocal playback and timed lyrics to YouTube while keeping YouTube's video as the master clock.

![Karaoke Machine screenshot](assets/screenshots/pp.png)

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

## Installer build

The Windows setup wizard is built with [Inno Setup 6](https://jrsoftware.org/isinfo.php). It copies the extension and native host files to:

```text
%LOCALAPPDATA%\Programs\DKaraoKe
```

Then it runs `scripts\setup-wizard.ps1`, which writes `%LOCALAPPDATA%\DKaraoKe\config.json`, runs `install.ps1`, and optionally runs `setup-roformer.ps1`.

Build prerequisites:

- Inno Setup 6
- PowerShell
- Python 3.10+
- `winget` recommended for installing Node.js and FFmpeg when missing

Build the installer from the repo root:

```powershell
ISCC.exe installer\installer.iss
```

The output installer is:

```text
installer\Output\DKaraoKeSetup.exe
```

Chrome extension loading is still manual because Chrome does not allow a normal local installer to silently load an unpacked extension. After setup, open `chrome://extensions`, enable **Developer mode**, click **Load unpacked**, and select the installed DKaraoKe folder.

## Hardware and processing expectations

Karaoke Machine! can run on CPU, but audio separation and local lyric timing are machine-learning workloads. A CUDA-capable NVIDIA GPU is strongly recommended for regular use.

This is my PC:

```text
CPU: Intel Core i7-13620H, 10 cores / 16 logical processors
RAM: 16 GB
GPU: NVIDIA GeForce RTX 3050 6GB Laptop GPU
Driver: NVIDIA 595.79 (`nvidia-smi` CUDA Version 13.2)
Runtime: PyTorch 2.5.1+cu124, TorchAudio 2.5.1+cu124, torch CUDA 12.4
```

Larger GPUs, especially 8 GB VRAM or more, are preferable for long tracks or when running lyric timing in parallel with stem separation.


Recommended hardware:

- **Best experience:** recent NVIDIA GPU with CUDA support, 6 GB VRAM minimum tested, 8 GB+ VRAM preferred, 16 GB+ system RAM, SSD storage, and the `cu124` Torch build when the driver supports it.
- **CPU-only fallback:** supported through `.\setup-roformer.ps1` without `-TorchBuild`, but expect separation and CTC timing to be much slower. Long songs may approach the built-in timeouts.
- **Disk:** reserve several GB for `.venv-roformer`, `.stem-models`, the 913 MB RoFormer checkpoint, Torch/TorchAudio wheels, temporary source audio, temporary WAV stems, and per-song MP3 caches.

Where the load happens:

- **RoFormer stem separation:** uses `--device auto`, so it chooses CUDA when `torch.cuda.is_available()` is true and falls back to CPU otherwise. Audio is normalized to stereo 44.1 kHz float WAV, processed with chunk size `352800` and overlap `2`, then converted to 192 kbps MP3 stems.
- **CTC lyric timing:** TorchAudio MMS forced alignment also chooses CUDA automatically when available. It can produce word timing when alignment spans are available.
- **Silero VAD timing:** lighter than CTC; it reads 16 kHz audio and sets Torch to one CPU thread. It produces line-level vocal-activity timing, not word-level CTC alignment.
- **FFmpeg and yt-dlp:** use CPU, disk, and network. Downloaded source audio is temporary and is removed after stems or timing audio are produced.

Concurrency warnings:

- The download/stem queue runs one song at a time, but original-audio lyric timing can be scheduled before separation (**Lyrics first**) or alongside separation (**Run together**).
- **Lyrics first** is the safer default on 6 GB GPUs because RoFormer and CTC both use CUDA when available. **Run together** can be faster on larger GPUs, but can also cause CUDA out-of-memory errors or heavy UI/system slowdown.
- Timeouts are intentionally long: yt-dlp downloads may run up to 2 hours, RoFormer up to 6 hours, and CTC/Silero lyric timing up to 2 hours. Chrome-side job guards are longer than the backend limits so slow local processing can report its own failure.

## Use

Press **K** beside the YouTube logo to open or close the karaoke workspace.

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

The setup wizard can choose a different stems/downloads folder. That choice is saved in:

```text
%LOCALAPPDATA%\DKaraoKe\config.json
```

If the config file is missing or invalid, DKaraoKe falls back to `%LOCALAPPDATA%\DKaraoKe\downloads`.

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

## Future

This is still a beta. I uploaded the project as soon as I had something working reasonably fine, so there are a lot of things to improve, but also a lot of things that straight up don't work correctly.

Some known issues:

- **CTC Forced Alignment** is _not_ perfect, and it will often produce wrong timings or fail entirely if the song is too long. Even beefier state-of-the-art methods will often do whatever they want. CTC is a good middle ground (better than VAD, which is also implemented). We will need a **lyrics editor** so any bad timing can be corrected.

- **Audio separation** has been less of an issue, but any model will have the drawback of being _too slow_. I imagine a model that can stream the audio as it's being extracted, which I don't even know if is possible. Something like that would work wonders, making it possible to have the video ready almost immediately.

- **Lyrics search** is a scoring mess and has **not** been thoroughly tested.

**Bugs**:
Not responsive yet. Small screens show the karaoke sections below the comments and below one another, so they're big as hell and actually not reachable. To fix the it, place them horizontally below the above-the-fold section.
Bar still loading after everything is done.
The monitor should only show the status for the *current open song* if there is any.


I'll keep updating this list as I find the time.
