"""컷·자막 자동 편집: 직접 찍은 말하는 영상에서 말 없는 부분·군말을 잘라내고 받아쓴 자막을 붙입니다.

1) 소리 크기로 말하는 구간 찾기 (ffmpeg silencedetect)
2) 받아쓰기 (faster-whisper, 처음 한 번 모델을 내려받음)
3) 군말(음, 어, 그…)만 있는 구간은 기본으로 빼기
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from . import config, media

WHISPER_MODEL = os.getenv("DROPCUT_WHISPER", "small")
STT_BACKEND = os.getenv("DROPCUT_STT", "whisper")  # whisper | dummy

FILLERS = {"음", "어", "그", "아", "저", "에", "으", "음음", "어어", "그니까", "뭐지", "흠"}

# 얼마나 촘촘하게 자를지: (조용함 기준 dB, 최소 침묵 길이 초, 앞뒤 여유 초)
CUT_LEVELS = {
    "loose": (-38, 0.8, 0.18),   # 길게 남기기
    "normal": (-35, 0.5, 0.12),
    "tight": (-32, 0.3, 0.08),   # 바짝 자르기
}


def extract_audio(src: Path, out: Path) -> None:
    media.run(["-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(out)])


def speech_ranges(wav: Path, duration: float, level: str = "normal") -> list[tuple[float, float]]:
    db, min_sil, pad = CUT_LEVELS.get(level, CUT_LEVELS["normal"])
    proc = subprocess.run(
        [media.ffmpeg_bin(), "-hide_banner", "-i", str(wav), "-af", f"silencedetect=noise={db}dB:d={min_sil}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    starts = [float(x) for x in re.findall(r"silence_start: (-?[\d.]+)", proc.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", proc.stderr)]
    silences = []
    for i, s in enumerate(starts):
        e = ends[i] if i < len(ends) else duration
        silences.append((max(0.0, s), min(duration, e)))
    speech, t = [], 0.0
    for s, e in silences:
        if s - t > 0.05:
            speech.append((t, s))
        t = e
    if duration - t > 0.05:
        speech.append((t, duration))
    # 앞뒤 여유 + 가까운 구간 합치기 + 너무 짧은 구간 버리기
    padded = [(max(0.0, s - pad), min(duration, e + pad)) for s, e in speech]
    merged: list[list[float]] = []
    for s, e in padded:
        if merged and s - merged[-1][1] < 0.2:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(round(s, 3), round(e, 3)) for s, e in merged if e - s >= 0.25]


def transcribe(wav: Path) -> list[dict]:
    """[{"start", "end", "word"}] 단어별 시각."""
    if STT_BACKEND == "dummy":
        return []
    from faster_whisper import WhisperModel

    model = WhisperModel(WHISPER_MODEL, device="auto", compute_type="int8")
    segments, _ = model.transcribe(str(wav), language="ko", word_timestamps=True, vad_filter=False,
                                   condition_on_previous_text=False)
    words = []
    for seg in segments:
        for w in seg.words or []:
            text = w.word.strip()
            if text:
                words.append({"start": round(w.start, 3), "end": round(w.end, 3), "word": text})
    return words


def _dummy_words(ranges: list[tuple[float, float]]) -> list[dict]:
    sample = "안녕하세요 오늘은 제가 직접 써본 제품을 소개해 드릴게요 이게 생각보다 정말 편하더라고요".split()
    words, k = [], 0
    for s, e in ranges:
        n = max(1, int((e - s) / 0.45))
        step = (e - s) / n
        for i in range(n):
            words.append({"start": round(s + i * step, 3), "end": round(s + (i + 1) * step - 0.05, 3), "word": sample[k % len(sample)]})
            k += 1
    return words


def is_filler(text: str) -> bool:
    toks = [re.sub(r"[^가-힣a-zA-Z]", "", t) for t in text.split()]
    toks = [t for t in toks if t]
    return bool(toks) and all(t in FILLERS for t in toks)


def build_pieces(ranges: list[tuple[float, float]], words: list[dict], drop_fillers: bool) -> list[dict]:
    pieces = []
    for s, e in ranges:
        ws = [w for w in words if s - 0.05 <= (w["start"] + w["end"]) / 2 <= e + 0.05]
        text = " ".join(w["word"] for w in ws).strip()
        filler = drop_fillers and words and (not text or is_filler(text))
        pieces.append({"start": s, "end": e, "text": text, "keep": not filler,
                       "note": "군말" if filler and text else ("말소리 없음" if filler else "")})
    return pieces


def analyze(src: Path, work: Path, duration: float, level: str, drop_fillers: bool, on_msg=None) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    wav = work / "voice16k.wav"
    if on_msg:
        on_msg("소리 살펴보는 중")
    extract_audio(src, wav)
    ranges = speech_ranges(wav, duration, level)
    if on_msg:
        on_msg("말 받아쓰는 중 (처음에는 받아쓰기 모델을 내려받느라 몇 분 걸릴 수 있어요)")
    words = _dummy_words(ranges) if STT_BACKEND == "dummy" else transcribe(wav)
    return {"pieces": build_pieces(ranges, words, drop_fillers), "words": words, "level": level}


def piece_cues(piece: dict, words: list[dict], offset: float, max_chars: int = 13) -> list[tuple[float, float, str]]:
    """잘린 구간 하나의 자막: 받아쓴 단어 시각을 새 타임라인으로 옮겨 한 줄씩 묶습니다.
    사용자가 문장을 고쳤으면 고친 문장을 구간 길이에 고르게 나눕니다."""
    s, e = piece["start"], piece["end"]
    ws = [w for w in words if s - 0.05 <= (w["start"] + w["end"]) / 2 <= e + 0.05]
    auto_text = " ".join(w["word"] for w in ws).strip()
    text = (piece.get("text") or "").strip()
    cues = []
    if ws and text == auto_text:
        line, ls, le = "", None, None
        for w in ws:
            cand = f"{line} {w['word']}".strip()
            if line and len(cand) > max_chars:
                cues.append((ls, le, line))
                line, ls = w["word"], None
            else:
                line = cand
            ls = w["start"] if ls is None else ls
            le = w["end"]
        if line:
            cues.append((ls, le, line))
        return [(max(0.0, a - s) + offset, min(e, b + 0.15) - s + offset, t) for a, b, t in cues]
    if not text:
        return []
    from .subtitles import split_chunks

    chunks = split_chunks(text, max_chars)
    total = sum(len(c) for c in chunks) or 1
    t, out = offset, []
    for c in chunks:
        d = (e - s) * len(c) / total
        out.append((t, t + d, c))
        t += d
    return out


def make_piece(src: Path, info: media.ProbeInfo, start: float, end: float, out: Path,
               size: tuple[int, int], extra_vf: str = "") -> None:
    """원래 소리를 살린 채로 구간 하나를 잘라 화면 비율에 맞춥니다."""
    d = media.frame_quantize(end - start)
    layout = media._video_filter(info, *size)
    vf = f"[0:v]{layout}{(',' + extra_vf) if extra_vf else ''}[v]"
    args = ["-ss", f"{start:.3f}", "-i", str(src), "-t", f"{d:.3f}", "-filter_complex", vf, "-map", "[v]"]
    if info.has_audio:
        args += ["-map", "0:a:0", "-af", f"apad,atrim=0:{d:.3f},afade=t=in:d=0.02,afade=t=out:st={max(0, d - 0.03):.3f}:d=0.03"]
    else:
        args += ["-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", "-map", "1:a", "-shortest"]
    args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-r", str(config.FPS),
             "-c:a", "pcm_s16le", "-ar", "44100", "-ac", "1", str(out.with_suffix(".mkv"))]
    media.run(args)
