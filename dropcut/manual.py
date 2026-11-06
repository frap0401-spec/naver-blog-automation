"""원고 직접 입력 보조: 붙여넣은 원고 해석, AI 없이 장면 자동 배치, claude.ai 채팅용 요청문."""
from __future__ import annotations

import re

PROMPT_FOR_CHAT = """아래 상품으로 30초 쇼핑쇼츠 나레이션 원고를 써줘.
- 첫 문장은 스크롤을 멈추게 하는 강한 후킹
- 문장 7~9개, 한 문장은 25자 안팎의 짧은 구어체, 이모지·특수문자 금지
- 흐름: 후킹 → 공감 → 상품 등장 → 장점 2~3개 → 사용 장면 → 댓글로 링크 받기 유도
- 확인되지 않은 효능·수치·최저가 같은 표현 금지
- 반드시 아래 형식 그대로, 다른 말 없이 출력

상단1: (화면 가운데 큰 문구 첫 줄, 10자 안팎)
상단2: (둘째 줄, 10자 안팎)
라벨: (문구 위 작은 빨간 라벨, 8자 이내)
---
(나레이션 문장 한 줄에 하나씩)

상품: {product}
특징: {notes}"""

KEYS = {
    "상단1": "hook1", "상단 1": "hook1", "제목1": "hook1",
    "상단2": "hook2", "상단 2": "hook2", "제목2": "hook2",
    "라벨": "badge", "뱃지": "badge",
    "제목": "title", "영상제목": "title",
    "설명": "description", "해시태그": "hashtags", "고정댓글": "pinned",
}


def parse(text: str) -> dict:
    """'상단1: ...' 같은 머리 항목과 나레이션 문장을 나눕니다."""
    fields: dict = {}
    lines: list[str] = []
    for raw in text.replace("\r", "").split("\n"):
        s = raw.strip()
        if not s or set(s) <= {"-", "=", "─"}:
            continue
        m = re.match(r"^\[?([가-힣 0-9]{1,6})\]?\s*[:：]\s*(.*)$", s)
        if m and m.group(1).strip() in KEYS:
            fields[KEYS[m.group(1).strip()]] = m.group(2).strip()
            continue
        if s.startswith("(") and s.endswith(")"):
            continue
        s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", s).strip().strip('"').strip()
        if s:
            lines.append(s)
    fields["lines"] = lines
    return fields


def auto_place(lens: list[float], durations: list[float]) -> list[tuple[int, float]]:
    """원본들을 이어 붙인 타임라인을 문장 길이 비율로 나눠 순서대로 배치합니다."""
    total = sum(durations)
    out = []
    if total <= 0:
        return [(0, 0.0) for _ in lens]
    lsum = sum(lens) or 1
    pos = 0.0
    for ln in lens:
        t = pos % total
        for vi, d in enumerate(durations):
            if t < d or vi == len(durations) - 1:
                out.append((vi, round(min(t, max(0.0, d - ln)), 2)))
                break
            t -= d
        pos += total * ln / lsum if lsum > total else ln
    return out
