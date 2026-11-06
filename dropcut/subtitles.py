"""ASS 자막 생성: 상단 후킹 제목(흰색+노란색) + 하단 나레이션 자막."""
from __future__ import annotations

from dataclasses import dataclass

from . import config


@dataclass
class Cue:
    start: float
    end: float
    text: str


def split_chunks(text: str, max_chars: int = 13) -> list[str]:
    """한 화면에 보기 좋게 문장을 어절 단위로 나눕니다."""
    words = text.split()
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
    for ch in text:
        if ch == " ":
            total += 0.3
        elif ord(ch) < 0x1100:
            total += 0.6
        else:
            total += 1.0
    return total


def _fit(text: str, base: int, max_width: int) -> str:
    """한 줄에 다 들어가도록 필요하면 글자 크기를 줄이는 태그."""
    size = base
    width = _units(text) * base * 1.02
    if width > max_width:
        size = max(40, int(base * max_width / width))
    return f"\\fs{size}" if size != base else ""


def _esc(text: str) -> str:
    return text.replace("\\", "＼").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(title1: str, title2: str, cues: list[Cue], total: float) -> str:
    f = config.FONT_NAME
    w, h = config.WIDTH, config.HEIGHT
    # 색상 형식: &HAABBGGRR
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Title1,{f},104,&H00FFFFFF,&H00FFFFFF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,8,3,8,40,40,150,1
Style: Title2,{f},124,&H0000F0FF,&H0000F0FF,&H00000000,&H64000000,-1,0,0,0,100,100,0,0,1,9,3,8,40,40,272,1
Style: Sub,{f},86,&H00FFFFFF,&H00FFFFFF,&H00000000,&H78000000,-1,0,0,0,100,100,0,0,1,6,2,2,60,60,430,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    end = _ts(total + 1)
    maxw = w - 100
    if title1:
        lines.append(f"Dialogue: 1,{_ts(0)},{end},Title1,,0,0,0,,{{{_fit(title1, 104, maxw)}}}{_esc(title1)}")
    if title2:
        lines.append(f"Dialogue: 1,{_ts(0)},{end},Title2,,0,0,0,,{{{_fit(title2, 124, maxw)}}}{_esc(title2)}")
    for c in cues:
        # 살짝 커지며 나타나는 팝 효과
        pop = "{" + _fit(c.text, 86, w - 140) + r"\fscx88\fscy88\t(0,90,\fscx100\fscy100)}"
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
