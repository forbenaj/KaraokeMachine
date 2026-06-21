import json
import os
import sys
import uuid
from contextlib import redirect_stdout


def main():
    try:
        import whisper_timestamped as whisper
        import torch
    except ImportError:
        raise SystemExit("whisper-timestamped is not installed; rerun setup-roformer.ps1")

    audio_path = sys.argv[1]
    model_name = os.environ.get("DKARAOKE_WHISPER_MODEL", "small")
    device = "cuda" if torch.cuda.is_available() else "cpu"
    # stdout is the machine-readable channel consumed by dkaraoke_host.py.
    # Whisper and its dependencies occasionally print status messages there,
    # so move their chatter to stderr and leave stdout as JSON only.
    with redirect_stdout(sys.stderr):
        model = whisper.load_model(model_name, device=device)
        result = whisper.transcribe_timestamped(model, audio_path, verbose=False)
    segments = []
    for raw_segment in result.get("segments", []):
        words = [{
            "id": str(uuid.uuid4()),
            "text": word.get("text", "").strip(),
            "start_time": float(word.get("start", 0)),
            "end_time": float(word.get("end", 0)),
            "confidence": word.get("confidence"),
        } for word in raw_segment.get("words", []) if word.get("text", "").strip()]
        if words:
            segments.append({
                "id": str(uuid.uuid4()),
                "text": raw_segment.get("text", "").strip(),
                "words": words,
                "start_time": words[0]["start_time"],
                "end_time": words[-1]["end_time"],
            })
    print(json.dumps({"segments": segments}, ensure_ascii=False))


if __name__ == "__main__":
    main()
