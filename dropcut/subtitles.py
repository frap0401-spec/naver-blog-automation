"""ASS 자막 생성: 상단 고정 문구(라벨 + 2줄 제목) + 나레이션 자막.

문구 안에서 [대괄호]로 감싼 말은 강조색(노란색)으로 바뀝니다.  예) "[리드줄 고리] 두 개"
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from . import config


@dataclass
class Cue:
    start: float
    end: float
    text: str


# 스타일 프리셋: 위치는 화면 높이 대비 비율, 크기는 화면 너비 1080 기준 px
STYLES = {
    "insta": {
        "name": "인스타그램 · 가운데 큰 문구",
        "badge_y": 0.17, "t1_y": 0.2, "t_gap": 0.066, "t1": 110, "t2": 110,
        "t1_color": "white", "t2_color": "yellow", "title_box": False,
        "sub_y": 0.50, "sub": 66, "sub_color": "yellow", "sub_box": False, "outline": 7,
    },
    "classic": {
        "name": "기본 · 위 제목 + 아래 자막",
        "badge_y": 0.045, "t1_y": 0.075, "t_gap": 0.058, "t1": 92, "t2": 108,
        "t1_color": "white", "t2_color": "yellow", "title_box": False,
        "sub_y": 0.74, "sub": 80, "sub_color": "white", "sub_box": False, "outline": 7,
    },
    "box": {
        "name": "깔끔 박스 · 검정 띠 글자",
        "badge_y": 0.06, "t1_y": 0.09, "t_gap": 0.06, "t1": 84, "t2": 84,
        "t1_color": "white", "t2_color": "yellow", "title_box": True,
        "sub_y": 0.76, "sub": 66, "sub_color": "white", "sub_box": True, "outline": 0,
    },
    "minimal": {
        "name": "자막만 · 제목 없이",
        "badge_y": 0, "t1_y": 0, "t_gap": 0, "t1": 0, "t2": 0,
        "t1_color": "white", "t2_color": "yellow", "title_box": False,
        "sub_y": 0.72, "sub": 78, "sub_color": "white", "sub_box": False, "outline": 7,
    },
}

COLORS = {"white": "&H00FFFFFF", "yellow": "&H0000E1FF", "red": "&H003B30FF", "black": "&H00000000"}


def split_chunks(text: str, max_chars: int = 13) -> list[str]:
    """한 화면에 보기 좋게 문장을 어절 단위로 나눕니다."""
    words = strip_marks(text).split()
    chunks: list[str] = []
    cur = ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and len(cand) > max_chars:
            chunks.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        chunks.append(cur)
    return chunks or [text]


def strip_marks(text: str) -> str:
    return text.replace("[", "").replace("]", "")


def cues_for_sentence(text: str, start: float, speech_dur: float) -> list[Cue]:
    """문장 음성 길이를 글자 수 비율로 나눠 자막 조각에 시간을 배분합니다."""
    chunks = split_chunks(text)
    weights = [max(1, len(c.replace(" ", ""))) for c in chunks]
    total = sum(weights)
    cues, t = [], start
    for c, wgt in zip(chunks, weights):
        d = speech_dur * wgt / total
        cues.append(Cue(t, t + d, c))
        t += d
    return cues


def _ts(sec: float) -> str:
    cs = int(round(sec * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _units(text: str) -> float:
    """글자 폭 추정(글꼴 크기 1 기준): 한글·한자 1.0, 영문·숫자 0.6, 공백 0.3."""
    total = 0.0
    for ch in strip_marks(text):
        if ch == " ":
            total += 0.3
        elif ord(ch) < 0x1100:
            total += 0.6
        else:
            total += 1.0
    return total


def _fit_size(text: str, base: int, max_width: int) -> int:
    width = _units(text) * base * 1.02
    return max(36, int(base * max_width / width)) if width > max_width else base


def _esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


def _rich(text: str, base_color: str) -> str:
    """[강조] 부분만 노란색으로."""
    base = COLORS[base_color]
    hi = COLORS["yellow"] if base_color != "yellow" else COLORS["white"]
    out = []
    for part in re.split(r"(\[[^\]]*\])", text):
        if part.startswith("[") and part.endswith("]"):
            out.append(f"{{\\c{hi}}}{_esc(part[1:-1])}{{\\c{base}}}")
        elif part:
            out.append(_esc(part))
    return "".join(out)


def build_ass(title1: str, title2: str, cues: list[Cue], total: float,
              size: tuple[int, int] = (1080, 1920), style: str = "insta", badge: str = "") -> str:
    st = STYLES.get(style, STYLES["insta"])
    w, h = size
    k = w / 1080 if w <= h else h / 1080 * 0.9  # 가로 화면은 글자를 조금 작게
    f = config.FONT_NAME
    ol = max(0, round(st["outline"] * k))
    box_style = 3 if st["title_box"] else 1
    sub_box = 3 if st["sub_box"] else 1
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title,{f},{round(st['t1'] * k) or 10},&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,-1,0,0,0,100,100,-1,0,{box_style},{ol if not st['title_box'] else 14},3,8,30,30,0,1
Style: Badge,{f},{round(44 * k)},&H00FFFFFF,&H00FFFFFF,{COLORS['red']},{COLORS['red']},-1,0,0,0,100,100,0,0,3,10,0,8,30,30,0,1
Style: Sub,{f},{round(st['sub'] * k)},&H00FFFFFF,&H00FFFFFF,&H00000000,&H90000000,-1,0,0,0,100,100,-1,0,{sub_box},{ol if not st['sub_box'] else 12},2,8,40,40,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    end = _ts(total + 1)
    cx = w // 2
    maxw = w - int(100 * k)
    if st["t1"]:
        if badge.strip():
            lines.append(f"Dialogue: 2,{_ts(0)},{end},Badge,,0,0,0,,{{\\pos({cx},{int(h * st['badge_y'])})}}{_esc(badge.strip())}")
        y = int(h * st["t1_y"]) + (int(30 * k) if badge.strip() else 0)
        for i, (text, key) in enumerate(((title1, "t1"), (title2, "t2"))):
            if not text.strip():
                continue
            color = st[f"{key}_color"]
            fs = _fit_size(text, round(st[key] * k), maxw)
            lines.append(
                f"Dialogue: 1,{_ts(0)},{end},Title,,0,0,0,,"
                f"{{\\pos({cx},{y})\\fs{fs}\\c{COLORS[color]}}}{_rich(text, color)}"
            )
            y += int(h * st["t_gap"] * (fs / max(1, round(st[key] * k))) + 0.5) if i == 0 else 0
    sub_color = COLORS[st["sub_color"]]
    sub_base = round(st["sub"] * k)
    for c in cues:
        fs = _fit_size(c.text, sub_base, w - int(140 * k))
        pop = f"{{\\pos({cx},{int(h * st['sub_y'])})\\fs{fs}\\c{sub_color}\\fscx88\\fscy88\\t(0,90,\\fscx100\\fscy100)}}"
        lines.append(f"Dialogue: 0,{_ts(c.start)},{_ts(c.end)},Sub,,0,0,0,,{pop}{_esc(c.text)}")
    return header + "\n".join(lines) + "\n"


def build_srt(cues: list[Cue]) -> str:
    def ts(sec: float) -> str:
        ms = int(round(sec * 1000))
        h, ms = divmod(ms, 3600000)
        m, ms = divmod(ms, 60000)
        s, ms = divmod(ms, 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    return "\n".join(f"{i}\n{ts(c.start)} --> {ts(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1))
