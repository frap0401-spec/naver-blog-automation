"""원고 직접 입력 모드: 붙여넣은 원고를 해석하고 장면을 자동 배치합니다 (AI·API 결제 불필요)."""
from __future__ import annotations

import re

from .llm import Analysis, Line, Script

# 붙여넣기 형식 예시 (claude.ai 채팅에 이 형식으로 써 달라고 하면 그대로 붙여넣을 수 있음)
FORMAT_GUIDE = """상단1: 이거 모르면 손해
상단2: 강아지 급수기 끝판왕
제목: 물 갈아주기 귀찮은 집사 필수템
설명: 매일 물 갈아주기 힘드셨죠? 실제 사용 장면을 담았어요.
해시태그: 강아지, 반려견용품, 자동급수기
고정댓글: 제품 정보는 아래 링크에서 확인하세요!
---
아직도 물그릇 하루에 몇 번씩 갈아주세요?
이거 하나 놓고 나서 완전히 편해졌어요.
(나레이션 문장을 한 줄에 하나씩)"""

PROMPT_FOR_CHAT = """아래 상품으로 30~40초 쇼핑쇼츠 나레이션 원고를 써줘.
- 첫 문장은 스크롤을 멈추게 하는 강한 후킹
- 문장 7~10개, 한 문장은 25자 안팎의 짧은 구어체, 이모지·특수문자 금지
- 흐름: 후킹 → 공감 → 상품 등장 → 장점 2~3개 → 사용 장면 → 고정 댓글 링크 확인 유도
- 확인되지 않은 효능·수치·최저가 같은 표현 금지
- 링크는 넣지 말 것
- 반드시 아래 형식 그대로, 다른 말 없이 출력

상단1: (화면 위 고정 제목 첫 줄, 12자 이내)
상단2: (강조할 둘째 줄, 10자 이내)
제목: (업로드용 영상 제목, 40자 이내)
설명: (설명란 2~3문장)
해시태그: (쉼표로 구분 5~8개)
고정댓글: (구매 링크 안내 한 줄)
---
(나레이션 문장 한 줄에 하나씩)

상품: {product}
특징: {notes}"""

KEYS = {
    "상단1": "hook_line1", "상단 1": "hook_line1", "제목1": "hook_line1",
    "상단2": "hook_line2", "상단 2": "hook_line2", "제목2": "hook_line2",
    "제목": "title", "영상제목": "title", "영상 제목": "title",
    "설명": "description", "설명란": "description",
    "해시태그": "hashtags", "태그": "hashtags",
    "고정댓글": "pinned_comment", "고정 댓글": "pinned_comment",
}


def _clean_line(s: str) -> str:
    s = s.strip()
    s = re.sub(r"^\s*(?:\d+[.)]|[-*•])\s*", "", s)  # 번호·글머리표 제거
    return s.strip().strip('"').strip()


def parse(text: str, product_name: str) -> Script:
    fields: dict[str, str] = {}
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
            continue  # 안내 문구
        cleaned = _clean_line(s)
        if cleaned:
            lines.append(cleaned)
    if not lines:
        raise ValueError("나레이션 문장이 없습니다. 한 줄에 한 문장씩 적어 주세요.")

    name = product_name or "이 제품"
    tags = [t.strip().lstrip("#") for t in re.split(r"[,\s]+", fields.get("hashtags", "")) if t.strip().lstrip("#")]
    return Script(
        style="직접 입력",
        hook_line1=fields.get("hook_line1", ""),
        hook_line2=fields.get("hook_line2", name if product_name else ""),
        lines=[Line(text=t, video_index=0, start_sec=0.0, visual="") for t in lines],
        title=fields.get("title", lines[0][:40]),
        description=fields.get("description", f"{name} 실제 사용 장면을 담았어요."),
        hashtags=tags,
        pinned_comment=fields.get("pinned_comment", "제품 정보는 아래 링크에서 확인하세요!"),
    )


def auto_place(script: Script, durations: list[float]) -> Script:
    """원본 영상들을 이어 붙인 타임라인을 문장 길이(글자 수) 비율로 나눠 순서대로 배치합니다."""
    total = sum(durations)
    if total <= 0:
        return script
    weights = [max(1, len(ln.text.replace(" ", ""))) for ln in script.lines]
    wsum = sum(weights)
    pos = 0.0
    for ln, w in zip(script.lines, weights):
        t = pos % total
        for vi, d in enumerate(durations):
            if t < d or vi == len(durations) - 1:
                ln.video_index = vi
                ln.start_sec = round(min(t, max(0.0, d - 0.5)), 1)
                break
            t -= d
        pos += total * w / wsum
    return script


def build(text: str, product_name: str, durations: list[float]) -> Analysis:
    script = auto_place(parse(text, product_name), durations)
    name = product_name or "직접 입력한 상품"
    return Analysis(product_name=name, summary="직접 입력한 원고입니다. 문장별 장면을 확인해 주세요.",
                    selling_points=[], target="", scripts=[script])
