"""설명 그래픽: 문장이 나오는 동안 화면에 카드형 그래픽을 띄웁니다 (ASS 벡터 그림).

종류: point(포인트 카드) / check(체크리스트) / compare(전·후 비교) / big(큰 숫자·단어)
테마: basic(기본 흰 카드) / strong(강한 노란 카드) / glass(반투명 어두운 카드)
위치: bottom(아래) / center(가운데) / full(화면 전체를 어둡게 하고 가운데)
"""
from __future__ import annotations

from . import config
from .subtitles import COLORS, _esc, _fit_size, _ts

TYPES = {"point": "포인트", "check": "체크리스트", "compare": "전·후 비교", "big": "큰 숫자·단어"}
THEMES = {
    "basic": {"name": "기본", "box": "&H00FFFFFF", "box_a": "&H00&", "text": "&H00191717", "accent": "&H00ED3A7C", "sub": "&H00707070"},
    "strong": {"name": "강한 장면", "box": "&H0000D4FF", "box_a": "&H00&", "text": "&H00000000", "accent": "&H003B3BEF", "sub": "&H00303030"},
    "glass": {"name": "글래스 UI", "box": "&H00000000", "box_a": "&H50&", "text": "&H00FFFFFF", "accent": "&H00FA8BA7", "sub": "&H00D8D8D8"},
}
POSITIONS = {"bottom": "아래", "center": "가운데", "full": "화면 전체"}
AMOUNTS = {"none": "없음", "few": "조금", "some": "보통", "many": "많이"}


def styles_block(size: tuple[int, int]) -> str:
    f = config.FONT_NAME
    return (f"Style: Gfx,{f},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1\n"
            f"Style: GfxText,{f},40,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,8,0,0,0,1\n")


def _rr(w: int, h: int, r: int) -> str:
    r = max(2, min(r, w // 2, h // 2))
    return (f"m {r} 0 l {w - r} 0 b {w} 0 {w} 0 {w} {r} l {w} {h - r} b {w} {h} {w} {h} {w - r} {h} "
            f"l {r} {h} b 0 {h} 0 {h} 0 {h - r} l 0 {r} b 0 0 0 0 {r} 0")


def _box(t0: str, t1: str, x: int, y: int, w: int, h: int, r: int, color: str, alpha: str, layer: int = 3) -> str:
    return (f"Dialogue: {layer},{t0},{t1},Gfx,,0,0,0,,{{\\an7\\pos({x},{y})\\p1\\c{color}\\1a{alpha}\\fad(150,120)}}"
            f"{_rr(w, h, r)}{{\\p0}}")


def _text(t0: str, t1: str, x: int, y: int, fs: int, color: str, text: str, an: int = 8, layer: int = 5) -> str:
    return (f"Dialogue: {layer},{t0},{t1},GfxText,,0,0,0,,{{\\an{an}\\pos({x},{y})\\fs{fs}\\c{color}\\fad(150,120)"
            f"\\fscx92\\fscy92\\t(0,120,\\fscx100\\fscy100)}}{_esc(text)}")


def events(g: dict, start: float, end: float, size: tuple[int, int], theme: str, pos: str,
           number: int, sub_y: float) -> list[str]:
    """그래픽 하나의 ASS 이벤트들. sub_y: 자막이 놓인 높이(겹치지 않게 피함)."""
    kind = g.get("type") or "point"
    title = (g.get("title") or "").strip()
    items = [str(x).strip() for x in (g.get("items") or []) if str(x).strip()][:4]
    if not title and not items:
        return []
    th = THEMES.get(theme, THEMES["basic"])
    w, h = size
    k = w / 1080 if w <= h else h / 1080 * 0.9
    t0, t1 = _ts(start + 0.12), _ts(max(start + 0.5, end - 0.05))
    cw = int(w * 0.84)
    pad = int(34 * k)
    tfs = _fit_size(title, int((120 if kind == "big" else 64) * k), cw - pad * 2)
    ifs = int(48 * k)
    gap = int(ifs * 1.42)
    head = int(50 * k) if kind == "point" else 0
    if kind == "compare":
        body = int(ifs * 1.42 * 2 + 10 * k)
    else:
        body = gap * len(items)
    ch = pad * 2 + head + (int(tfs * 1.3) if title else 0) + body
    x = (w - cw) // 2
    if pos == "full" or pos == "center":
        cy = 0.5 if abs(sub_y - 0.5) > 0.12 else 0.64
    else:
        cy = 0.78 if sub_y < 0.62 else 0.47
    y = int(h * cy - ch / 2)
    out = []
    if pos == "full":
        out.append(_box(t0, t1, 0, 0, w, h, 0, "&H00000000", "&H70&", layer=0))
    out.append(_box(t0, t1, x, y, cw, ch, int(30 * k), th["box"], th["box_a"]))
    cx, cur = w // 2, y + pad
    if kind == "point":
        bw, bh = int(170 * k), int(40 * k)
        out.append(_box(t0, t1, cx - bw // 2, cur, bw, bh, bh // 2, th["accent"], "&H00&", layer=4))
        out.append(_text(t0, t1, cx, cur + int(4 * k), int(26 * k), "&H00FFFFFF", f"POINT {number}", layer=6))
        cur += head
    if title:
        color = th["accent"] if kind == "big" else th["text"]
        out.append(_text(t0, t1, cx, cur, tfs, color, title))
        cur += int(tfs * 1.3)
    if kind == "compare":
        colw = (cw - pad * 3) // 2
        labels = ["전", "후"]
        for i in range(2):
            lx = x + pad + i * (colw + pad)
            out.append(_box(t0, t1, lx, cur, colw, body, int(18 * k), th["accent"] if i else th["sub"], "&H30&", layer=4))
            out.append(_text(t0, t1, lx + colw // 2, cur + int(8 * k), int(30 * k), "&H00FFFFFF", labels[i], layer=6))
            txt = items[i] if i < len(items) else ""
            out.append(_text(t0, t1, lx + colw // 2, cur + int(52 * k), _fit_size(txt, ifs, colw - int(20 * k)), "&H00FFFFFF", txt, layer=6))
    else:
        for it in items:
            label = f"√ {it}" if kind == "check" else it
            out.append(_text(t0, t1, cx, cur, _fit_size(label, ifs, cw - pad * 2), th["sub"] if kind != "check" else th["text"], label))
            cur += gap
    return out


def auto_graphics(lines: list[str], amount: str) -> dict[int, dict]:
    """Claude 없이 쓸 때: 가운데 문장들에 포인트 카드를 고르게 배치."""
    ratio = {"none": 0, "few": 0.2, "some": 0.35, "many": 0.55}.get(amount, 0)
    n = len(lines)
    count = round(n * ratio)
    if count <= 0 or n < 3:
        return {}
    idx = [1 + round(i * (n - 2) / max(1, count)) for i in range(count)]
    out = {}
    for i in sorted(set(min(n - 2, j) for j in idx)):
        out[i] = {"type": "point", "title": lines[i].rstrip(".!?~ "), "items": []}
    return out
