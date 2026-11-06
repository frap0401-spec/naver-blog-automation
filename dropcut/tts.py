"""나레이션 음성 합성.

- 무료: Microsoft Edge TTS (한국어 기본 목소리 3명 × 톤 변형)
- 유료(선택): 타입캐스트(TYPECAST_API_KEY), 클로바 보이스(NCP_CLOVA_CLIENT_ID/SECRET), ElevenLabs(ELEVENLABS_API_KEY)
  .env 에 키를 넣으면 그 서비스의 목소리가 목록에 뜹니다.

목소리 ID 형식: "edge:<이름>:<피치>" / "tc:<voice_id>:<모델>" / "cv:<speaker>" / "el:<voice_id>"
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


# ---------------------------------------------------------------- Typecast (타입캐스트)
# 공식 SDK(typecast-python) 사용. 키: https://typecast.ai/developers 에서 발급

TYPECAST_KEY = os.getenv("TYPECAST_API_KEY", "").strip()
TYPECAST_EMOTION = os.getenv("TYPECAST_EMOTION", "normal")  # normal / happy / toneup / tonedown ...
_tc_cache: tuple[float, list[dict]] = (0.0, [])
_tc_lock = threading.Lock()
_TC_MODEL_ORDER = ["ssfm-v31", "ssfm-v30", "ssfm-v21"]
_KOR = {"male": "남성", "female": "여성", "child": "아이", "teenager": "10대", "young_adult": "청년",
        "middle_age": "중년", "elder": "노년"}


def typecast_voices() -> list[dict]:
    global _tc_cache
    if not TYPECAST_KEY:
        return []
    # 직접 정한 목소리만 쓰고 싶으면: TYPECAST_VOICES=tc_xxx:이름,tc_yyy:이름
    custom = os.getenv("TYPECAST_VOICES", "").strip()
    if custom:
        items = [(c.split(":") + [""])[:2] for c in custom.split(",") if c.strip()]
        return [{"id": f"tc:{vid.strip()}:{os.getenv('TYPECAST_MODEL', 'ssfm-v30')}", "name": n or vid, "desc": "직접 지정",
                 "provider": "타입캐스트"} for vid, n in items]
    with _tc_lock:
        age = time.time() - _tc_cache[0]
        if (_tc_cache[1] and age < 600) or (not _tc_cache[1] and age < 60):
            return _tc_cache[1]
        voices: list[dict] = []
        try:
            from typecast import Typecast

            for v in Typecast(api_key=TYPECAST_KEY).voices_v3():
                models = [str(getattr(m.version, "value", m.version)) for m in v.models]
                model = next((m for m in _TC_MODEL_ORDER if m in models), models[0] if models else "ssfm-v21")
                name = v.voice_name.kor or v.voice_name.eng
                g = getattr(v.gender, "value", v.gender) if v.gender else ""
                a = getattr(v.age, "value", v.age) if v.age else ""
                desc = " · ".join(x for x in (_KOR.get(g, g), _KOR.get(a, a), ", ".join((v.use_cases or [])[:2])) if x)
                voices.append({"id": f"tc:{v.voice_id}:{model}", "name": name, "desc": desc, "provider": "타입캐스트"})
        except Exception as exc:
            print("[드롭컷] 타입캐스트 목소리 목록을 불러오지 못했습니다:", exc)
            _tc_cache = (time.time(), [])
            return []
        _tc_cache = (time.time(), voices)
        return voices


def _typecast(text: str, voice: str, rate: int, out: Path) -> None:
    from typecast import Typecast
    from typecast.models.tts import Output, PresetPrompt, Prompt, TTSRequest

    _, voice_id, model = (voice.split(":") + ["ssfm-v21"])[:3]
    prompt = Prompt(emotion_preset=TYPECAST_EMOTION if TYPECAST_EMOTION in ("normal", "happy", "sad", "angry") else "normal") \
        if model == "ssfm-v21" else PresetPrompt(emotion_preset=TYPECAST_EMOTION)
    res = Typecast(api_key=TYPECAST_KEY).text_to_speech(TTSRequest(
        voice_id=voice_id, text=text, model=model, language="kor", prompt=prompt,
        output=Output(audio_tempo=round(min(2.0, max(0.5, 1 + rate / 100)), 2), audio_format="mp3"),
    ))
    out.write_bytes(res.audio_data)


# ---------------------------------------------------------------- CLOVA Voice (네이버 클라우드)
# 클로바 더빙은 따로 공개된 연결 방법이 없어서, 같은 네이버 음성을 제공하는 NAVER Cloud Platform 'CLOVA Voice - Premium'으로 연결합니다.
# 키: 네이버 클라우드 콘솔 > AI·NAVER API > Application 등록(CLOVA Voice 선택) 후 Client ID / Client Secret

CLOVA_ID = os.getenv("NCP_CLOVA_CLIENT_ID", "").strip()
CLOVA_SECRET = os.getenv("NCP_CLOVA_CLIENT_SECRET", "").strip()
CLOVA_URL = os.getenv("NCP_CLOVA_URL", "https://naveropenapi.apigw.ntruss.com/tts-premium/v1/tts")
_CLOVA_DEFAULT = [
    ("nara", "아라", "여성 · 차분한 안내 톤"),
    ("nyejin", "예진", "여성 · 밝고 또렷한 톤"),
    ("njiyun", "지윤", "여성 · 부드러운 톤"),
    ("nminsang", "민상", "남성 · 신뢰감 있는 톤"),
    ("nsinu", "신우", "남성 · 차분한 톤"),
    ("njinho", "진호", "남성 · 힘 있는 톤"),
    ("nkyuwon", "규원", "남성 · 밝은 톤"),
    ("nhajun", "하준", "아이 · 남자아이"),
    ("ndain", "다인", "아이 · 여자아이"),
]


def clova_voices() -> list[dict]:
    if not (CLOVA_ID and CLOVA_SECRET):
        return []
    custom = os.getenv("NCP_CLOVA_SPEAKERS", "").strip()  # 예: nara:아라:여성,nminsang:민상:남성
    items = [tuple((c.split(":") + ["", ""])[:3]) for c in custom.split(",") if c.strip()] if custom else _CLOVA_DEFAULT
    return [{"id": f"cv:{sid.strip()}", "name": n or sid, "desc": d, "provider": "클로바 보이스"} for sid, n, d in items]


def _clova(text: str, speaker: str, rate: int, out: Path) -> None:
    import httpx

    speed = max(-5, min(5, round(-rate / 10)))  # CLOVA: -5(빠르게) ~ 5(느리게), 0이 보통
    res = httpx.post(
        CLOVA_URL,
        headers={"X-NCP-APIGW-API-KEY-ID": CLOVA_ID, "X-NCP-APIGW-API-KEY": CLOVA_SECRET},
        data={"speaker": speaker, "text": text, "volume": "0", "speed": str(speed), "pitch": "0", "format": "mp3"},
        timeout=60,
    )
    if res.status_code != 200:
        raise RuntimeError(f"CLOVA Voice 오류 {res.status_code}: {res.text[:300]}")
    out.write_bytes(res.content)


# ---------------------------------------------------------------- 목록

def all_voices() -> list[dict]:
    edge = [{"id": i, "name": n, "desc": d, "provider": "기본(무료)"} for i, n, d in EDGE_VOICES]
    return edge + typecast_voices() + clova_voices() + eleven_voices()


def default_voice() -> str:
    return EDGE_VOICES[0][0]


def is_known(voice: str) -> bool:
    if voice.startswith("ko-KR-"):  # 예전 버전 작업 호환
        return True
    if voice.startswith("el:"):
        return bool(ELEVEN_KEY)
    if voice.startswith("tc:"):
        return bool(TYPECAST_KEY)
    if voice.startswith("cv:"):
        return bool(CLOVA_ID and CLOVA_SECRET)
    return any(v["id"] == voice for v in all_voices())


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
            elif voice.startswith("tc:"):
                if not TYPECAST_KEY:
                    raise RuntimeError(".env에 TYPECAST_API_KEY가 없습니다.")
                _typecast(text, voice, rate, out)
            elif voice.startswith("cv:"):
                if not (CLOVA_ID and CLOVA_SECRET):
                    raise RuntimeError(".env에 NCP_CLOVA_CLIENT_ID / NCP_CLOVA_CLIENT_SECRET가 없습니다.")
                _clova(text, voice[3:], rate, out)
            else:
                asyncio.run(_edge(text, voice, rate, out))
            if out.exists() and out.stat().st_size > 0:
                return out
        except Exception as exc:  # 네트워크 일시 오류 재시도
            last_exc = exc
            msg = str(exc).lower()
            if any(k in msg for k in ("401", "402", "403", "quota", "unauthorized", "payment", "credit")):
                break  # 키·잔액 문제는 다시 시도해도 안 됨
            time.sleep(1 + attempt)
    raise RuntimeError(f"음성 합성 실패({voice}): {last_exc}")
