"""드롭컷 전역 설정. 값은 환경변수(.env)로 바꿀 수 있습니다."""
from __future__ import annotations

import os
import platform
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


def _default_font() -> str:
    system = platform.system()
    if system == "Windows":
        return "Malgun Gothic"
    if system == "Darwin":
        return "Apple SD Gothic Neo"
    return "Noto Sans CJK KR"


WORKSPACE = Path(os.getenv("DROPCUT_WORKSPACE", ROOT / "workspace"))
FONTS_DIR = ROOT / "assets" / "fonts"
BGM_DIR = ROOT / "assets" / "bgm"

# Claude
MODEL = os.getenv("DROPCUT_MODEL", "claude-opus-5-5")
EFFORT = os.getenv("DROPCUT_EFFORT", "high")
LLM_BACKEND = os.getenv("DROPCUT_LLM", "claude")  # claude | mock

# 음성
TTS_BACKEND = os.getenv("DROPCUT_TTS", "edge")  # edge | dummy

# 영상
WIDTH = 1080
HEIGHT = 1920
FPS = 30
FONT_NAME = os.getenv("DROPCUT_FONT", _default_font())
ZOOM = float(os.getenv("DROPCUT_ZOOM", "1.06"))  # 원본 테두리/워터마크를 살짝 잘라내는 확대 비율
SENTENCE_GAP = float(os.getenv("DROPCUT_GAP", "0.12"))  # 문장 사이 쉼(초)
BGM_VOLUME = float(os.getenv("DROPCUT_BGM_VOLUME", "0.12"))
MAX_FRAMES = int(os.getenv("DROPCUT_MAX_FRAMES", "36"))  # 분석용으로 Claude에 보낼 최대 프레임 수

COUPANG_DISCLOSURE = "이 게시물은 쿠팡 파트너스 활동의 일환으로, 이에 따른 일정액의 수수료를 제공받습니다."
