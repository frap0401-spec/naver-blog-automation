"""어색한 컷 자동 보정.

원본 영상마다 한 번 훑어서
  - 장면 전환(원본 편집점)
  - 검은 화면
  - 멈춘 화면(정지된 프레임)
을 찾아 두고, 문장마다 잘라 쓸 구간이 이런 곳에 걸리면 가장 가까운 깨끗한 구간으로 옮깁니다.
원래 구간에 문제가 없으면 그대로 씁니다.

어색하다고 보는 것:
  - 구간 시작·끝 0.5초 안에 장면 전환이 있어 한순간 다른 장면이 번쩍 보이는 경우
  - 검은 화면이 섞인 경우
  - 1초 넘게 화면이 멈춘 경우
구간 한가운데의 장면 전환은 원본 편집 그대로라 자연스러우므로 허용합니다.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import media

EDGE = 0.5        # 시작·끝에서 이 시간 안의 장면 전환은 '번쩍임'으로 봄
FREEZE_MIN = 1.0  # 이보다 길게 멈춘 화면만 문제로 봄


@dataclass
class Issues:
    cuts: list[float] = field(default_factory=list)
    black: list[tuple[float, float]] = field(default_factory=list)
    freeze: list[tuple[float, float]] = field(default_factory=list)


def scan(src: Path, cache: Path) -> Issues:
    if cache.exists():
        d = json.loads(cache.read_text(encoding="utf-8"))
        return Issues(d["cuts"], [tuple(x) for x in d["black"]], [tuple(x) for x in d["freeze"]])
    proc = subprocess.run(
        [media.ffmpeg_bin(), "-hide_banner", "-i", str(src), "-an", "-vf",
         "scale=320:-2,blackdetect=d=0.1:pix_th=0.10,freezedetect=n=-50dB:d=0.6,"
         "select='gt(scene\\,0.3)',showinfo", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    log = proc.stderr
    cuts = sorted({round(float(t), 2) for t in re.findall(r"showinfo.*?pts_time:([\d.]+)", log)})
    black = [(float(a), float(b)) for a, b in re.findall(r"black_start:([\d.]+) black_end:([\d.]+)", log)]
    starts = [float(x) for x in re.findall(r"freeze_start: ([\d.]+)", log)]
    ends = [float(x) for x in re.findall(r"freeze_end: ([\d.]+)", log)]
    info_dur = media.probe(src).duration
    freeze = []
    for i, a in enumerate(starts):
        b = ends[i] if i < len(ends) else info_dur  # 끝까지 멈춘 경우
        if b - a >= FREEZE_MIN:
            freeze.append((a, b))
    issues = Issues(cuts, black, freeze)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(asdict(issues)), encoding="utf-8")
    return issues


def _overlap(a: float, b: float, spans: list[tuple[float, float]]) -> float:
    return sum(max(0.0, min(b, y) - max(a, x)) for x, y in spans)


def problems(issues: Issues, a: float, d: float) -> list[str]:
    """[a, a+d] 구간의 문제 목록(없으면 빈 목록)."""
    b = a + d
    out = []
    if _overlap(a, b, issues.black) > 0.05:
        out.append("검은 화면")
    if _overlap(a, b, issues.freeze) > 0.3:
        out.append("멈춘 화면")
    for c in issues.cuts:
        if a + 0.04 < c < a + min(EDGE, d / 3) or b - min(EDGE, d / 3) < c < b - 0.04:
            out.append("순간 장면 전환")
            break
    return out


def _score(issues: Issues, a: float, d: float) -> float:
    b = a + d
    s = 100 * _overlap(a, b, issues.black) + 30 * _overlap(a, b, issues.freeze)
    for c in issues.cuts:
        edge = min(EDGE, d / 3)
        if a + 0.04 < c < a + edge or b - edge < c < b - 0.04:
            s += 20
    return s


def best_start(issues: Issues, duration: float, start: float, length: float) -> tuple[float, list[str]]:
    """문제가 없으면 start 그대로, 있으면 가장 가까운 깨끗한 시작점을 돌려줍니다.
    반환: (시작 시각, 원래 구간에서 발견한 문제 목록)"""
    latest = max(0.0, duration - length)
    start = min(max(0.0, start), latest)
    found = problems(issues, start, length)
    if not found or length >= duration:
        return start, found

    # 후보: 원래 위치 주변 촘촘히 + 장면 전환 직후 + 문제 구간 직후/직전
    cands = {start}
    step = 0.1
    k = 1
    while start - k * step >= 0 or start + k * step <= latest:
        for c in (start - k * step, start + k * step):
            if 0 <= c <= latest:
                cands.add(round(c, 2))
        k += 1
        if k * step > duration:
            break
    for c in issues.cuts:
        cands.update({c + 0.05, c - length - 0.05})
    for x, y in issues.black + issues.freeze:
        cands.update({y + 0.05, x - length - 0.05})
    cands = [min(max(0.0, c), latest) for c in cands]

    best = min(cands, key=lambda c: (_score(issues, c, length), abs(c - start)))
    if _score(issues, best, length) >= _score(issues, start, length):
        return start, found  # 더 나은 곳이 없으면 그대로
    return round(best, 2), found
