"""나레이션 음성 합성 (기본: Microsoft Edge 무료 TTS)."""
from __future__ import annotations

import asyncio
import math
import struct
import wave
from pathlib import Path

from . import config

VOICES = [
    {"id": "ko-KR-SunHiNeural", "name": "선희", "desc": "여성 · 밝고 또렷한 쇼핑 톤"},
    {"id": "ko-KR-InJoonNeural", "name": "인준", "desc": "남성 · 차분하고 신뢰감 있는 톤"},
    {"id": "ko-KR-HyunsuMultilingualNeural", "name": "현수", "desc": "남성 · 자연스러운 대화 톤"},
]

PREVIEW_TEXT = "이거 하나면 진짜 끝이에요. 지금 바로 확인해 보세요!"


def rate_str(rate: int) -> str:
    return f"{'+' if rate >= 0 else ''}{int(rate)}%"


async def _edge(text: str, voice: str, rate: int, out: Path) -> None:
    import edge_tts

    communicate = edge_tts.Communicate(text, voice, rate=rate_str(rate))
    await communicate.save(str(out))


def _dummy(text: str, rate: int, out: Path) -> Path:
    """네트워크 없이 테스트할 때 쓰는 가짜 음성(글자 수에 비례한 길이의 낮은 톤)."""
    out = out.with_suffix(".wav")
    seconds = max(0.8, len(text.replace(" ", "")) * 0.14 / (1 + rate / 100))
    sr = 22050
    with wave.open(str(out), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        frames = bytearray()
        for i in range(int(sr * seconds)):
            frames += struct.pack("<h", int(1500 * math.sin(2 * math.pi * 220 * i / sr)))
        w.writeframes(bytes(frames))
    return out


def synthesize(text: str, voice: str, rate: int, out: Path) -> Path:
    """text를 음성 파일로 저장하고 실제 저장된 경로를 돌려줍니다."""
    out.parent.mkdir(parents=True, exist_ok=True)
    if config.TTS_BACKEND == "dummy":
        return _dummy(text, rate, out)
    out = out.with_suffix(".mp3")
    last_exc: Exception | None = None
    for _ in range(3):
        try:
            asyncio.run(_edge(text, voice, rate, out))
            if out.exists() and out.stat().st_size > 0:
                return out
        except Exception as exc:  # 네트워크 일시 오류 재시도
            last_exc = exc
    raise RuntimeError(f"음성 합성 실패({voice}): {last_exc}")
