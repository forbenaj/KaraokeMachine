import json
import sys
from contextlib import redirect_stdout
from pathlib import Path


def main():
    try:
        import torch
        from silero_vad import get_speech_timestamps, load_silero_vad, read_audio
    except ImportError:
        raise SystemExit("silero-vad is not installed; rerun setup-roformer.ps1")

    if len(sys.argv) != 2:
        raise SystemExit("usage: silero_vad_runner.py AUDIO_PATH")
    audio_path = Path(sys.argv[1])
    if not audio_path.is_file() or audio_path.stat().st_size <= 0:
        raise SystemExit(f"vocals stem is missing or empty: {audio_path}")

    torch.set_num_threads(1)
    # stdout is consumed as JSON by the native host; package/model status goes
    # to stderr so callers never have to parse around progress chatter.
    with redirect_stdout(sys.stderr):
        model = load_silero_vad()
        wav = read_audio(str(audio_path), sampling_rate=16000)
        speech_timestamps = get_speech_timestamps(
            wav,
            model,
            sampling_rate=16000,
            threshold=0.1,
            return_seconds=True,
            min_silence_duration_ms=350,
            speech_pad_ms=80,
        )

    print(json.dumps({"speech_timestamps": speech_timestamps}, ensure_ascii=False))


if __name__ == "__main__":
    main()
