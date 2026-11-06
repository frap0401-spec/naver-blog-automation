"""나레이션 음성 합성.

- 무료: Microsoft Edge TTS (한국어 기본 목소리 3명 × 톤 변형)
- 유료(선택): ElevenLabs — .env 에 ELEVENLABS_API_KEY 를 넣으면 내 계정의 목소리가 모두 목록에 뜹니다.

목소리 ID 형식: "edge:<이름>:<피치>" 또는 "el:<voice_id>"
"""
from __future__ import annotations

import asyncio
import math
import os
import struct
import threading
import time
import wave
from pathlib import Path

from . import config

EDGE_VOICES = [
    # (id, 이름, 설명)
    ("edge:ko-KR-SunHiNeural:+0Hz", "선희", "여성 · 밝고 또렷한 쇼핑 톤"),
    ("edge:ko-KR-SunHiNeural:+12Hz", "선희 · 하이톤", "여성 · 발랄하고 귀여운 톤"),
    ("edge:ko-KR-SunHiNeural:-8Hz", "선희 · 차분", "여성 · 낮고 차분한 리뷰 톤"),
    ("edge:ko-KR-InJoonNeural:+0Hz", "인준", "남성 · 신뢰감 있는 톤"),
    ("edge:ko-KR-InJoonNeural:-10Hz", "인준 · 저음", "남성 · 굵고 묵직한 톤"),
    ("edge:ko-KR-InJoonNeural:+8Hz", "인준 · 경쾌", "남성 · 밝고 빠른 광고 톤"),
    ("edge:ko-KR-HyunsuMultilingualNeural:+0Hz", "현수", "남성 · 자연스러운 대화 톤"),
    ("edge:ko-KR-HyunsuMultilingualNeural:-8Hz", "현수 · 차분", "남성 · 부드러운 설명 톤"),
]

PREVIEW_TEXT = "이거 하나면 진짜 끝이에요. 지금 바로 확인해 보세요!"

ELEVEN_KEY = os.getenv("ELEVENLABS_API_KEY", "").strip()
ELEVEN_MODEL = os.getenv("ELEVENLABS_MODEL", "eleven_multilingual_v2")

_el_cache: tuple[float, list[dict]] = (0.0, [])
_el_lock = threading.Lock()


def _eleven_client():
    from elevenlabs.client import ElevenLabs

    return ElevenLabs(api_key=ELEVEN_KEY)


def eleven_voices() -> list[dict]:
    """ElevenLabs 계정의 목소리 목록(10분 캐시). 키가 없거나 실패하면 빈 목록."""
    global _el_cache
    if not ELEVEN_KEY:
        return []
    with _el_lock:
        age = time.time() - _el_cache[0]
        if (_el_cache[1] and age < 600) or (not _el_cache[1] and age < 60):  # 실패는 1분간 재시도 안 함
            return _el_cache[1]
        voices: list[dict] = []
        try:
            client = _eleven_client()
            token = None
            for _ in range(5):
                res = client.voices.search(page_size=100, next_page_token=token)
                for v in res.voices:
                    labels = v.labels or {}
                    desc = " · ".join(x for x in (labels.get("gender"), labels.get("age"), labels.get("accent"),
                                                  labels.get("descriptive") or labels.get("description")) if x)
                    voices.append({"id": f"el:{v.voice_id}", "name": v.name or v.voice_id,
                                   "desc": desc or (v.category or ""), "provider": "ElevenLabs"})
                if not res.has_more or not res.next_page_token:
                    break
                token = res.next_page_token
        except Exception as exc:
            print("[드롭컷] ElevenLabs 목소리 목록을 불러오지 못했습니다:", exc)
            _el_cache = (time.time(), [])
            return []
        _el_cache = (time.time(), voices)
        return voices


def all_voices() -> list[dict]:
    edge = [{"id": i, "name": n, "desc": d, "provider": "기본(무료)"} for i, n, d in EDGE_VOICES]
    return edge + eleven_voices()


def default_voice() -> str:
    return EDGE_VOICES[0][0]


def is_known(voice: str) -> bool:
    if voice.startswith("ko-KR-"):  # 예전 버전 작업 호환
        return True
    return any(v["id"] == voice for v in all_voices()) or voice.startswith("el:") and bool(ELEVEN_KEY)


def _rate_str(rate: int) -> str:
    return f"{'+' if rate >= 0 else ''}{int(rate)}%"


def _parse_edge(voice: str) -> tuple[str, str]:
    parts = voice.split(":")
    if parts[0] == "edge":
        parts = parts[1:]
    name = parts[0]
    pitch = parts[1] if len(parts) > 1 else "+0Hz"
    return name, pitch


async def _edge(text: str, voice: str, rate: int, out: Path) -> None:
    import edge_tts

    name, pitch = _parse_edge(voice)
    await edge_tts.Communicate(text, name, rate=_rate_str(rate), pitch=pitch).save(str(out))


def _eleven(text: str, voice_id: str, rate: int, out: Path) -> None:
    from elevenlabs.types.voice_settings import VoiceSettings

    speed = min(1.2, max(0.7, 1 + rate / 100))  # ElevenLabs 속도 범위 0.7~1.2
    kwargs = {}
    if ELEVEN_MODEL.startswith(("eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_v3")):
        kwargs["language_code"] = "ko"  # 언어 지정을 지원하는 모델만
    audio = _eleven_client().text_to_speech.convert(
        voice_id,
        text=text,
        model_id=ELEVEN_MODEL,
        output_format="mp3_44100_128",
        voice_settings=VoiceSettings(stability=0.45, similarity_boost=0.8, style=0.15, speed=speed),
        **kwargs,
    )
    with open(out, "wb") as f:
        for chunk in audio:
            f.write(chunk)


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
    for attempt in range(3):
        try:
            if voice.startswith("el:"):
                if not ELEVEN_KEY:
                    raise RuntimeError(".env에 ELEVENLABS_API_KEY가 없습니다.")
                _eleven(text, voice[3:], rate, out)
            else:
                asyncio.run(_edge(text, voice, rate, out))
            if out.exists() and out.stat().st_size > 0:
                return out
        except Exception as exc:  # 네트워크 일시 오류 재시도
            last_exc = exc
            if "401" in str(exc) or "quota" in str(exc).lower():
                break
            time.sleep(1 + attempt)
    raise RuntimeError(f"음성 합성 실패({voice}): {last_exc}")
