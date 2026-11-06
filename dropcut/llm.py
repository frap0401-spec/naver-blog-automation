"""Claude 연동.

1) write()        : 영상·사진을 보고 원고 3안 + 썸네일 문구 + 업로드 글(제목·설명·답글·DM·검색어)
2) pick_scenes()  : 완성된 원고(문장별 음성 길이 포함)에 맞춰 문장마다 쓸 장면을 고름
"""
from __future__ import annotations

import base64
from pathlib import Path

from pydantic import BaseModel, Field

from . import config

# ---------------------------------------------------------------- 1) 원고 쓰기


class ThumbCopy(BaseModel):
    badge: str = Field(description="문구 위 작은 빨간 라벨. 예: 직접 써봤더니, 집사 필수템 (8자 이내)")
    line1: str = Field(description="썸네일 문구 첫 줄(흰색), 10자 안팎. 강조할 말은 [ ]로 감싸기")
    line2: str = Field(description="썸네일 문구 둘째 줄(노란색), 10자 안팎")


class ScriptDraft(BaseModel):
    style: str = Field(description="원고 콘셉트 이름. 예: 산책 폭주 해결형, 올인원 기능형, 귀여움형")
    thumb_copies: list[ThumbCopy] = Field(description="이 원고에 어울리는 썸네일 문구 후보 정확히 3개")
    lines: list[str] = Field(description="나레이션 문장들. 한 문장은 25자 안팎의 짧은 구어체")


class TextRegion(BaseModel):
    video_index: int = Field(description="원본 영상 번호(0부터)")
    kind: str = Field(description="자막 / 워터마크 / 로고 / 기타 글자")
    x: float = Field(description="영역 왼쪽 위치, 화면 너비 대비 0~1")
    y: float = Field(description="영역 위쪽 위치, 화면 높이 대비 0~1")
    w: float = Field(description="영역 너비, 0~1")
    h: float = Field(description="영역 높이, 0~1")


class Analysis(BaseModel):
    product_name: str
    summary: str = Field(description="영상으로 파악한 상품 설명 2~3문장")
    who: list[str] = Field(description="누가 사나: 타깃 고객 3개")
    when: list[str] = Field(description="언제 쓰나: 사용 상황 2~3개")
    why: list[str] = Field(description="왜 사나: 구매 이유·장점 3개")
    scripts: list[ScriptDraft] = Field(description="콘셉트가 서로 다른 원고 정확히 3개")
    titles: list[str] = Field(description="업로드용 제목 후보 5개, 40자 이내")
    description: str = Field(description="설명란 본문 3~5문장. 링크·대가성 문구는 넣지 말 것")
    reply: str = Field(description="'링크 주세요' 같은 댓글에 달 답글 문구")
    dm: str = Field(description="인스타 DM 자동 응답 문구")
    keywords: list[str] = Field(description="검색어·해시태그용 키워드 8~12개, # 없이")
    text_regions: list[TextRegion] = Field(description="원본 영상에 이미 박혀 있는 자막·글자·워터마크 영역. 없으면 빈 목록")


WRITE_SYSTEM = """당신은 한국 쇼핑쇼츠(유튜브 쇼츠·인스타 릴스·네이버 클립) 전문 카피라이터입니다.
상품 원본 영상·사진의 장면(영상 속 중국어·영어 글자 포함)을 보고 구매 전환이 잘 되는 쇼츠 원고와 업로드 글을 씁니다.

원고 규칙:
- 첫 문장은 스크롤을 멈추게 하는 강한 후킹(공감되는 불편함, 의외의 사실, 반전).
- 한 문장은 25자 안팎의 짧은 구어체. 이모지·특수문자·영어 약어 금지(TTS가 어색하게 읽음).
- 흐름: 후킹 → 공감 → 상품 등장 → 화면에 보이는 장점 2~3개 → 사용 장면 → 댓글로 링크 받기 유도.
- 화면에서 확인할 수 없는 효능·수치·인증(의학적 효과, 최저가, 1위 등)을 지어내지 말 것.
- 3개 원고는 콘셉트가 확실히 달라야 함.

썸네일 문구: 화면 가운데에 크게 박히는 문구. 짧고 세게. 강조할 단어는 [ ]로 감쌈. 예: line1 "[리드줄 고리] 두 개", line2 "안전 손잡이까지".

원본 글자 찾기: 영상에 이미 박혀 있는 자막·워터마크·채널 로고가 있으면 text_regions에 영상별로 넉넉한 사각형 하나씩. 상품 자체에 인쇄된 글자는 제외.
"""

LENGTHS = {15: "15초 안팎, 문장 4~5개", 30: "30초 안팎, 문장 7~9개", 45: "45초 안팎, 문장 10~13개"}


def _image_block(path: Path) -> dict:
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def _frames_content(frames: list[tuple[int, float, Path]], durations: list[float]) -> list[dict]:
    content: list[dict] = []
    for vi, d in enumerate(durations):
        content.append({"type": "text", "text": f"영상 {vi}: 길이 {d:.1f}초"})
    for vi, t, path in frames:
        content.append({"type": "text", "text": f"[영상 {vi} · {t:.1f}초]"})
        content.append(_image_block(path))
    return content


def _call(system: str, content: list[dict], schema):
    import anthropic

    client = anthropic.Anthropic()
    with client.beta.messages.stream(
        model=config.MODEL,
        max_tokens=32000,
        system=system,
        thinking={"type": "adaptive"},
        output_config={"effort": config.EFFORT},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        messages=[{"role": "user", "content": content}],
        output_format=schema,
    ) as stream:
        response = stream.get_final_message()
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude가 이 요청을 처리하지 않았습니다. 다른 영상으로 시도해 주세요.")
    if response.stop_reason == "max_tokens":
        raise RuntimeError("결과가 너무 길어 중간에 잘렸습니다. 다시 시도해 주세요.")
    if response.parsed_output is None:
        raise RuntimeError("결과를 해석하지 못했습니다. 다시 시도해 주세요.")
    return response.parsed_output


def write(frames, durations: list[float], product: str, request: str, length: int) -> Analysis:
    if config.LLM_BACKEND == "mock":
        return _mock_write(durations, product, length)
    content = _frames_content(frames, durations)
    req = f"위 장면을 보고 상품을 분석한 뒤 원고 3안과 업로드 글을 써 주세요.\n길이: {LENGTHS.get(length, LENGTHS[30])}"
    if product:
        req += f"\n상품명: {product}"
    if request:
        req += f"\n추가 요청: {request}"
    content.append({"type": "text", "text": req})
    a: Analysis = _call(WRITE_SYSTEM, content, Analysis)
    n = len(durations)
    a.text_regions = [r for r in a.text_regions if 0 <= r.video_index < n and r.w > 0.01 and r.h > 0.01]
    a.keywords = [k.lstrip("#").replace(" ", "") for k in a.keywords if k.strip()]
    return a


# ---------------------------------------------------------------- 2) 장면 고르기


class SceneChoice(BaseModel):
    line_index: int
    video_index: int = Field(description="쓸 원본 영상 번호(0부터)")
    start_sec: float = Field(description="그 영상에서 시작할 시각(초)")
    second_video_index: int = Field(description="문장이 길어 장면 하나로 지루하면 이어 붙일 두 번째 영상 번호, 필요 없으면 -1")
    second_start_sec: float = Field(description="두 번째 장면 시작 시각(초), 없으면 0")
    reason: str = Field(description="이 장면을 고른 이유 한 문장")


class ScenePlan(BaseModel):
    choices: list[SceneChoice]


SCENE_SYSTEM = """당신은 쇼핑쇼츠 영상 편집자입니다. 나레이션 문장마다 그 말과 가장 잘 맞는 원본 장면을 고릅니다.
- 프레임 라벨 [영상 n · t초]를 보고 video_index와 start_sec을 정함. 문장 길이(초)만큼 그 장면이 이어져도 어색하지 않은 지점에서 시작.
- 첫 문장에는 상품이 가장 또렷하게 보이는 장면.
- 같은 장면을 연속으로 쓰지 말고 다양한 장면을 섞음.
- 문장이 3초를 넘으면 두 번째 장면을 이어 붙여도 됨(second_video_index). 아니면 -1.
"""


def pick_scenes(frames, durations: list[float], lines: list[str], lens: list[float]) -> list[SceneChoice]:
    if config.LLM_BACKEND == "mock":
        return []
    content = _frames_content(frames, durations)
    listing = "\n".join(f"{i}. ({lens[i]:.1f}초) {t}" for i, t in enumerate(lines))
    content.append({"type": "text", "text": f"나레이션 문장(번호. (길이) 문장):\n{listing}\n\n문장마다 장면을 골라 주세요."})
    plan: ScenePlan = _call(SCENE_SYSTEM, content, ScenePlan)
    return plan.choices


# ---------------------------------------------------------------- 테스트용


def _mock_write(durations: list[float], product: str, length: int) -> Analysis:
    name = product or "이 제품"
    base = [
        "아직도 이렇게 불편하게 쓰고 계세요?",
        f"그래서 제가 {name} 써봤는데요.",
        "생각보다 훨씬 간단해서 놀랐어요.",
        "한 번만 쓰면 바로 차이가 느껴져요.",
        "디자인도 깔끔해서 어디 둬도 예뻐요.",
        "가격 부담도 크지 않은 편이고요.",
        "제품 링크는 댓글에 남겨 주세요!",
    ]
    n = {15: 4, 30: 7, 45: 7}.get(length, 7)
    lines = base[: n - 1] + [base[-1]]
    scripts = [
        ScriptDraft(style=s, lines=lines, thumb_copies=[
            ThumbCopy(badge="직접 써봤더니", line1="[이거] 모르면 손해", line2=f"{name} 끝판왕"),
            ThumbCopy(badge="살림 필수템", line1="이거 하나로", line2="다 돼요"),
            ThumbCopy(badge="", line1="[진짜] 미쳤다", line2="이 가격 실화?"),
        ]) for s in ("공감형", "문제해결형", "반전형")
    ]
    return Analysis(
        product_name=name, summary="테스트용 분석 결과입니다.",
        who=["바쁜 직장인", "1인 가구", "선물 고민하는 사람"], when=["매일 아침", "외출 전"],
        why=["간편함", "깔끔한 디자인", "부담 없는 가격"], scripts=scripts,
        titles=[f"{name} 이거 하나로 끝났습니다", f"{name} 써보고 놀란 이유", "이거 모르면 손해", "살림 필수템 추천", "가성비 끝판왕"],
        description=f"{name} 실제 사용 장면을 담았어요.", reply="링크는 고정 댓글에 있어요!",
        dm="안녕하세요! 문의하신 제품 링크 보내드려요.", keywords=["쇼핑", "추천템", "살림템", "가성비"],
        text_regions=[TextRegion(video_index=0, kind="자막", x=0.05, y=0.78, w=0.9, h=0.12)] if durations else [],
    )
