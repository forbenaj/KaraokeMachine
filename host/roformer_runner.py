"""Safe standalone runner for KimberleyJensen's vocal Mel-Band RoFormer."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf
import torch
import yaml
from ml_collections import ConfigDict


def normalize_audio(source: Path, destination: Path) -> None:
    command = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(source), "-vn", "-ar", "44100", "-ac", "2",
        "-c:a", "pcm_f32le", str(destination),
    ]
    subprocess.run(command, check=True)


def load_model(repo: Path, config_path: Path, checkpoint: Path, device: torch.device):
    sys.path.insert(0, str(repo))
    from utils import get_model_from_config  # type: ignore[import-not-found]

    with config_path.open(encoding="utf-8") as source:
        config = ConfigDict(yaml.load(source, Loader=yaml.FullLoader))
    model = get_model_from_config("mel_band_roformer", config)
    state = torch.load(checkpoint, map_location="cpu", weights_only=True)
    model.load_state_dict(state)
    model.eval().to(device)
    return model, config


def choose_device(requested: str) -> torch.device:
    if requested == "auto":
        requested = "cuda" if torch.cuda.is_available() else "cpu"
    if requested == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested, but this PyTorch environment cannot use it.")
    return torch.device(requested)


def separate_track(model, config, normalized: Path, output_dir: Path, device: torch.device) -> None:
    from utils import demix_track  # type: ignore[import-not-found]

    mix, sample_rate = sf.read(normalized, dtype="float32", always_2d=True)
    if sample_rate != 44100 or mix.shape[1] != 2:
        raise RuntimeError("Normalized input is not stereo 44.1 kHz audio.")
    mixture = torch.from_numpy(mix.T.copy())
    result, _ = demix_track(config, model, mixture, device)
    vocals = np.asarray(result["vocals"].T, dtype=np.float32)
    instrumental = np.asarray(mix - vocals, dtype=np.float32)
    np.nan_to_num(vocals, copy=False)
    np.nan_to_num(instrumental, copy=False)
    output_dir.mkdir(parents=True, exist_ok=True)
    sf.write(output_dir / "vocals.wav", vocals, 44100, subtype="FLOAT")
    sf.write(output_dir / "instrumental.wav", instrumental, 44100, subtype="FLOAT")


def get_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DKaraoKe Mel-Band RoFormer runner")
    parser.add_argument("tracks", nargs="+", type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--checkpoint", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device", choices=("auto", "cuda", "cpu"), default="auto")
    parser.add_argument("--num-overlap", type=int, default=2)
    parser.add_argument("--chunk-size", type=int, default=352800)
    return parser


def main(argv=None) -> int:
    args = get_parser().parse_args(argv)
    config_path = args.repo / "configs" / "config_vocals_mel_band_roformer.yaml"
    for path, label in ((args.repo, "repository"), (config_path, "config"), (args.checkpoint, "checkpoint")):
        if not path.exists():
            raise FileNotFoundError(f"RoFormer {label} not found: {path}")
    if args.num_overlap < 1:
        raise ValueError("num_overlap must be at least 1.")
    if args.chunk_size < 44100:
        raise ValueError("chunk_size must be at least 44100 samples (one second).")

    device = choose_device(args.device)
    print(f"Loading Mel-Band RoFormer on {device}...")
    model, config = load_model(args.repo, config_path, args.checkpoint, device)
    config.inference.num_overlap = args.num_overlap
    config.inference.chunk_size = args.chunk_size
    print(f"RoFormer ready: chunk={args.chunk_size}, overlap={args.num_overlap}")

    with tempfile.TemporaryDirectory(prefix="dkaraoke-roformer-") as temporary:
        temporary_root = Path(temporary)
        for index, track in enumerate(args.tracks, 1):
            if not track.is_file():
                raise FileNotFoundError(f"Input file not found: {track}")
            print(f"[{index}/{len(args.tracks)}] Normalizing {track.name}...")
            normalized = temporary_root / f"{index}.wav"
            normalize_audio(track, normalized)
            print(f"[{index}/{len(args.tracks)}] Separating vocals...")
            separate_track(model, config, normalized, args.output / track.stem, device)
            print(f"[{index}/{len(args.tracks)}] Complete: {track.stem}")
            if device.type == "cuda":
                torch.cuda.empty_cache()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
