"""Claude로 상품 영상을 분석하고 쇼핑쇼츠 원고 3종을 만듭니다."""
from __future__ import annotations

import base64
from pathlib import Path

from pydantic import BaseModel, Field

from . import config


class Line(BaseModel):
    text: str = Field(description="나레이션 한 문장. TTS로 읽기 좋은 짧은 구어체")
    video_index: int = Field(description="이 문장 동안 보여줄 원본 영상 번호(0부터)")
    start_sec: float = Field(description="그 영상에서 컷을 시작할 시각(초)")
    visual: str = Field(description="이 컷에서 보이는 장면 설명")


class Script(BaseModel):
    style: str = Field(description="원고 스타일 이름. 예: 공감형, 문제해결형, 반전형")
    hook_line1: str = Field(description="화면 상단 고정 제목 첫째 줄(흰색), 12자 이내")
    hook_line2: str = Field(description="화면 상단 고정 제목 둘째 줄(노란색 강조), 10자 이내")
    lines: list[Line]
    title: str = Field(description="업로드용 영상 제목. 클릭을 부르는 40자 이내")
    description: str = Field(description="영상 설명란 본문. 링크·대가성 문구는 넣지 말 것")
    hashtags: list[str] = Field(description="# 없이 해시태그 단어 5~8개")
    pinned_comment: str = Field(description="고정 댓글 문구(구매 링크 안내). 링크 자체는 넣지 말 것")


class Analysis(BaseModel):
    product_name: str
    summary: str = Field(description="영상으로 파악한 상품 설명 2~3문장")
    selling_points: list[str]
    target: str = Field(description="주요 타깃 고객")
    scripts: list[Script] = Field(description="서로 다른 스타일의 원고 정확히 3개")


SYSTEM = """당신은 한국 쇼핑쇼츠(유튜브 쇼츠·인스타 릴스·네이버 클립) 전문 편집자이자 카피라이터입니다.
상품 원본 영상의 프레임을 보고, 구매 전환이 잘 되는 30~45초 세로 쇼츠의 나레이션 원고와 컷 편집 계획을 만듭니다.

원고 작성 규칙:
- 첫 문장(0~3초)은 스크롤을 멈추게 하는 강한 후킹: 공감되는 불편함, 의외의 사실, 반전 중 하나.
- 문장은 7~11개. 한 문장은 25자 안팎의 짧은 구어체. 이모지·특수문자·영어 약어는 TTS가 어색하게 읽으므로 쓰지 않음.
- 흐름: 후킹 → 문제/상황 공감 → 상품 등장 → 핵심 장점 2~3개(화면에 보이는 것 위주) → 사용 장면 → 행동 유도(고정 댓글/설명란 링크 확인).
- 화면에서 확인할 수 없는 효능·수치·인증(의학적 효과, 최저가, 1위 등)을 지어내지 말 것.
- 3개 원고는 스타일이 확실히 달라야 함(예: 공감형 / 문제해결형 / 반전·호기심형).

컷 편집 규칙:
- 각 문장마다 그 내용을 가장 잘 보여주는 장면을 프레임 목록에서 골라 video_index와 start_sec을 지정.
- 프레임 라벨의 [영상 n · t초]를 그대로 활용. 같은 장면을 연속으로 쓰지 말고 다양한 장면을 섞을 것.
- 상품이 가장 잘 보이는 장면을 후킹과 상품 등장 문장에 배치.
"""


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def analyze(frames: list[tuple[int, float, Path]], durations: list[float], product_name: str, notes: str) -> Analysis:
    if config.LLM_BACKEND == "mock":
        return _mock(frames, durations, product_name)

    import anthropic

    content: list[dict] = []
    for vi, d in enumerate(durations):
        content.append({"type": "text", "text": f"영상 {vi}: 길이 {d:.1f}초"})
    for vi, t, path in frames:
        content.append({"type": "text", "text": f"[영상 {vi} · {t:.1f}초]"})
        content.append(_image_block(path))
    req = "위 프레임을 보고 상품을 분석한 뒤, 쇼핑쇼츠 원고 3개와 컷 편집 계획을 만들어 주세요."
    if product_name:
        req += f"\n상품명: {product_name}"
    if notes:
        req += f"\n판매자 메모(장점·특징·강조할 점): {notes}"
    content.append({"type": "text", "text": req})

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=config.MODEL,
        max_tokens=32000,
        system=SYSTEM,
        thinking={"type": "adaptive"},
        output_config={"effort": config.EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
        output_format=Analysis,
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 요청을 처리하지 않았습니다. 다른 영상으로 시도해 주세요.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("원고가 너무 길어 중간에 잘렸습니다. 다시 시도해 주세요.")
    result = response.parsed_output
    if result is None:
        raise RuntimeError("원고 결과를 해석하지 못했습니다. 다시 시도해 주세요.")
    return _sanitize(result, durations)


def _sanitize(a: Analysis, durations: list[float]) -> Analysis:
    n = len(durations)
    for s in a.scripts:
        s.hashtags = [h.lstrip("#").replace(" ", "") for h in s.hashtags if h.strip()]
        for ln in s.lines:
            ln.video_index = min(max(0, ln.video_index), n - 1)
            ln.start_sec = min(max(0.0, ln.start_sec), max(0.0, durations[ln.video_index] - 0.5))
    return a


def _mock(frames: list[tuple[int, float, Path]], durations: list[float], product_name: str) -> Analysis:
    """API 키 없이 화면/렌더링을 테스트하기 위한 가짜 결과."""
    name = product_name or "이 제품"
    texts = [
        "아직도 이렇게 불편하게 쓰고 계세요?",
        f"그래서 제가 {name} 써봤는데요.",
        "생각보다 훨씬 간단해서 놀랐어요.",
        "한 번만 쓰면 바로 차이가 느껴져요.",
        "디자인도 깔끔해서 어디 둬도 예뻐요.",
        "가격 부담도 크지 않은 편이고요.",
        "자세한 정보는 고정 댓글에서 확인하세요!",
    ]
    picks = frames or [(0, 0.0, Path())]
    scripts = []
    for k, style in enumerate(["공감형", "문제해결형", "반전형"]):
        lines = [
            Line(text=t, video_index=picks[(i + k) % len(picks)][0], start_sec=picks[(i + k) % len(picks)][1], visual="")
            for i, t in enumerate(texts)
        ]
        scripts.append(Script(
            style=style, hook_line1="이거 모르면 손해", hook_line2=f"{name} 끝판왕",
            lines=lines, title=f"{name} 이거 하나로 끝났습니다",
            description=f"{name} 실제 사용 장면을 담았어요.", hashtags=["쇼핑", "추천템", "살림템"],
            pinned_comment="제품 정보는 아래 링크에서 확인하세요!",
        ))
    return _sanitize(Analysis(product_name=name, summary="테스트용 분석 결과입니다.",
                              selling_points=["간편함", "디자인"], target="누구나", scripts=scripts), durations)
