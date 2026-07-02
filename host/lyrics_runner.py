import json
import os
import re
import sys
import unicodedata
from contextlib import redirect_stdout
from pathlib import Path

os.environ.setdefault("PYTORCH_CUDA_ALLOC_CONF", "expandable_segments:True")

WORD_RE = re.compile(r"\S+")
ANNOTATION_LINE_RE = re.compile(r"^\s*[\[(][^)\]]+[\])]\s*$")
UNSUPPORTED_CHAR_RE = re.compile(r"[^a-z']+")
APOSTROPHES = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u02bc": "'",
    "`": "'",
})


def split_words(text):
    return WORD_RE.findall(text or "")


def normalize_alignment_word(text):
    value = unicodedata.normalize("NFKD", str(text or "").translate(APOSTROPHES))
    value = "".join(character for character in value if not unicodedata.combining(character))
    return UNSUPPORTED_CHAR_RE.sub("", value.casefold()).strip("'")


def score_token_spans(spans):
    total = sum(max(1, int(span.end) - int(span.start)) for span in spans)
    if total <= 0:
        return None
    return sum(float(getattr(span, "score", 0.0)) * max(1, int(span.end) - int(span.start)) for span in spans) / total


def clamp_span(start_time, end_time, total_duration):
    start = max(0.0, float(start_time))
    end = max(start + 0.02, float(end_time))
    if total_duration > 0:
        end = min(end, total_duration)
        start = min(start, max(0.0, end - 0.02))
    return round(start, 3), round(end, 3)


def interpolate_line_timing(line_index, mapped_lines):
    before_item = next(((position, mapped_lines[position]) for position in range(line_index - 1, -1, -1) if position in mapped_lines), None)
    after_item = next(((position, mapped_lines[position]) for position in range(line_index + 1, max(mapped_lines.keys(), default=-1) + 1) if position in mapped_lines), None)
    before = before_item[1] if before_item else None
    after = after_item[1] if after_item else None
    if before and after:
        gap = after["start_time"] - before["end_time"]
        slots = after_item[0] - before_item[0]
        step = gap / max(1, slots)
        start_time = before["end_time"] + step * (line_index - before_item[0] - 1)
        return start_time, start_time + step
    if before:
        start_time = before["end_time"] + 0.4 * (line_index - before_item[0] - 1)
        return start_time, start_time + 0.4
    if after:
        end_time = after["start_time"] - 0.4 * (after_item[0] - line_index - 1)
        return max(0.0, end_time - 0.4), end_time
    raise RuntimeError("CTC forced alignment could not align the provided lyric lines.")


def build_word_timings_from_spans(line_spans, spec, word_specs, seconds_per_frame, total_duration):
    if not line_spans:
        return []
    cursor = 0
    words = []
    for word_index in spec["word_indices"]:
        word = word_specs[word_index]
        token_count = len(word["normalized"])
        if token_count <= 0:
            return []
        word_spans = line_spans[cursor:cursor + token_count]
        if len(word_spans) != token_count:
            return []
        cursor += token_count
        start_time, end_time = clamp_span(
            word_spans[0].start * seconds_per_frame,
            word_spans[-1].end * seconds_per_frame,
            total_duration,
        )
        entry = {
            "id": f"ctc-word-{word_index}",
            "text": word["text"],
            "start_time": start_time,
            "end_time": end_time,
        }
        confidence = score_token_spans(word_spans)
        if confidence is not None:
            entry["confidence"] = round(confidence, 4)
        words.append(entry)
    if cursor != len(line_spans):
        return []
    return words


def build_segments(token_spans, line_specs, word_specs, alignment_entries, waveform_frames, emission_frames, sample_rate):
    seconds_per_frame = waveform_frames / emission_frames / sample_rate
    total_duration = waveform_frames / sample_rate
    mapped_lines = {}
    mapped_line_spans = {}
    for entry, spans in zip(alignment_entries, token_spans):
        if entry["kind"] != "line":
            continue
        if not spans:
            continue
        previous_gap = entry.get("previous_gap")
        next_gap = entry.get("next_gap")
        start_time = spans[0].start * seconds_per_frame
        end_time = spans[-1].end * seconds_per_frame
        if previous_gap is not None:
            gap_end = token_spans[previous_gap][-1].end * seconds_per_frame
            start_time = min(start_time, gap_end)
        if next_gap is not None:
            gap_end = token_spans[next_gap][-1].end * seconds_per_frame
            end_time = max(end_time, gap_end)
        mapped_lines[entry["line_index"]] = {
            "start_time": start_time,
            "end_time": end_time,
        }
        mapped_line_spans[entry["line_index"]] = spans
    if not mapped_lines:
        raise RuntimeError("CTC forced alignment could not align the provided lyric lines.")

    segments = []
    for line_index, spec in enumerate(line_specs):
        if not spec["word_indices"]:
            continue
        timing = mapped_lines.get(line_index)
        if timing is None:
            line_start, line_end = interpolate_line_timing(line_index, mapped_lines)
        else:
            line_start, line_end = timing["start_time"], timing["end_time"]
        line_start, line_end = clamp_span(line_start, line_end, total_duration)
        words = build_word_timings_from_spans(
            mapped_line_spans.get(line_index),
            spec,
            word_specs,
            seconds_per_frame,
            total_duration,
        )
        segments.append({
            "id": f"ctc-segment-{line_index}",
            "text": spec["text"],
            "words": words,
            "start_time": line_start,
            "end_time": line_end,
        })
    return segments


def main():
    try:
        import torch
        import torchaudio
    except ImportError:
        raise SystemExit("torchaudio is not installed; rerun setup-roformer.ps1")

    if len(sys.argv) != 2:
        raise SystemExit("usage: lyrics_runner.py AUDIO_PATH")
    audio_path = Path(sys.argv[1])
    if not audio_path.is_file() or audio_path.stat().st_size <= 0:
        raise SystemExit(f"vocals stem is missing or empty: {audio_path}")
    lyrics_text = sys.stdin.read()
    if not lyrics_text.strip():
        raise SystemExit("lyrics text is required on stdin")

    line_specs = []
    word_specs = []
    for raw_line in lyrics_text.splitlines():
        line_text = raw_line.strip()
        if not line_text:
            continue
        words = split_words(line_text)
        if not words:
            continue
        line_spec = {"text": line_text, "word_indices": []}
        skip_alignment = bool(ANNOTATION_LINE_RE.fullmatch(line_text))
        for word_text in words:
            normalized = "" if skip_alignment else normalize_alignment_word(word_text)
            word_specs.append({"text": word_text, "normalized": normalized})
            line_spec["word_indices"].append(len(word_specs) - 1)
        line_specs.append(line_spec)
    dictionary = torchaudio.pipelines.MMS_FA.get_dict()
    alignable_line_indices = []
    for line_index, spec in enumerate(line_specs):
        token_ids = []
        for word_index in spec["word_indices"]:
            token_ids.extend(dictionary[character] for character in word_specs[word_index]["normalized"])
        spec["token_ids"] = token_ids
        if token_ids:
            alignable_line_indices.append(line_index)
    if not alignable_line_indices:
        raise SystemExit("lyrics text does not contain any alignable lines")
    alignment_entries = [{"kind": "gap"}]
    for line_index in alignable_line_indices:
        gap_index = len(alignment_entries) - 1
        alignment_entries.append({
            "kind": "line",
            "line_index": line_index,
            "previous_gap": gap_index,
            "next_gap": gap_index + 2,
        })
        alignment_entries.append({"kind": "gap"})
    token_sequences = [[dictionary["*"]] if entry["kind"] == "gap" else line_specs[entry["line_index"]]["token_ids"] for entry in alignment_entries]

    device = "cuda" if torch.cuda.is_available() else "cpu"
    # stdout is the machine-readable channel consumed by dkaraoke_host.py.
    # TorchAudio and checkpoint download helpers may print status messages
    # there, so move their chatter to stderr and leave stdout as JSON only.
    with redirect_stdout(sys.stderr):
        bundle = torchaudio.pipelines.MMS_FA
        model = bundle.get_model().to(device)
        model.eval()
        aligner = bundle.get_aligner()
        waveform, sample_rate = torchaudio.load(str(audio_path))
        if waveform.ndim != 2:
            raise SystemExit("vocals stem could not be decoded into a waveform")
        if waveform.size(0) > 1:
            waveform = waveform.mean(dim=0, keepdim=True)
        if sample_rate != bundle.sample_rate:
            waveform = torchaudio.functional.resample(waveform, sample_rate, bundle.sample_rate)
            sample_rate = bundle.sample_rate
        with torch.inference_mode():
            emission, _ = model(waveform.to(device))
            token_spans = aligner(emission[0], token_sequences)

    segments = build_segments(
        token_spans,
        line_specs,
        word_specs,
        alignment_entries,
        waveform.size(1),
        emission.size(1),
        sample_rate,
    )
    print(json.dumps({"segments": segments}, ensure_ascii=False))


if __name__ == "__main__":
    main()
