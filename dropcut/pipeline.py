"""작업(Job) 단위 파이프라인: 올리기 → 원고 고르기 → 목소리 고르기 → 만들기 → 내보내기."""
from __future__ import annotations

import json
import shutil
import threading
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, llm, manual, media, smartcut, subtitles, tts


@dataclass
class Job:
    id: str
    product_name: str = ""
    notes: str = ""
    link: str = ""
    mode: str = "ai"  # ai | manual
    script_text: str = ""
    sources: list[str] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)
    status: str = "created"  # created|analyzing|scripts_ready|rendering|done|error
    progress: float = 0.0
    message: str = ""
    analysis: dict | None = None
    chosen: dict | None = None
    voice: str = field(default_factory=tts.default_voice)
    rate: int = 10
    bgm: str = ""
    cleanup: dict = field(default_factory=dict)
    smart_cut: bool = True
    fixes: list = field(default_factory=list)  # {"0": {"mode": "crop", "box": [x,y,w,h]}}
    error: str = ""
    duration: float = 0.0

    @property
    def dir(self) -> Path:
        return config.WORKSPACE / self.id

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "job.json").write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    def update(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.save()


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def get(job_id: str) -> Job | None:
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    path = config.WORKSPACE / job_id / "job.json"
    if path.exists() and job_id.isalnum():
        job = Job(**json.loads(path.read_text(encoding="utf-8")))
        if job.status in ("analyzing", "rendering"):  # 서버 재시작으로 중단된 작업
            job.status, job.error = "error", "서버가 재시작되어 작업이 중단되었습니다. 다시 시도해 주세요."
        with _lock:
            _jobs[job_id] = job
        return job
    return None


def create(files: list[tuple[str, bytes]], product_name: str, notes: str, link: str,
           mode: str = "ai", script_text: str = "") -> Job:
    if mode == "manual":
        manual.parse(script_text, product_name)  # 형식 오류는 업로드 전에 바로 알림
    job = Job(id=uuid.uuid4().hex[:12], product_name=product_name.strip(), notes=notes.strip(), link=link.strip(),
              mode="manual" if mode == "manual" else "ai", script_text=script_text.strip())
    src_dir = job.dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for i, (name, data) in enumerate(files):
        ext = Path(name).suffix.lower() or ".mp4"
        path = src_dir / f"video{i}{ext}"
        path.write_bytes(data)
        job.sources.append(str(path.relative_to(job.dir)))
    job.save()
    with _lock:
        _jobs[job.id] = job
    return job


def _bg(job: Job, fn) -> None:
    def runner():
        try:
            fn(job)
        except Exception as exc:
            traceback.print_exc()
            job.update(status="error", error=str(exc), message="")

    threading.Thread(target=runner, daemon=True).start()


# 1) 올리기 → 분석/원고 생성 -------------------------------------------------

def start_analysis(job: Job) -> None:
    job.update(status="analyzing", progress=0.05, message="영상 확인 중", error="")
    _bg(job, _analyze)


def _analyze(job: Job) -> None:
    infos = [media.probe(job.dir / s) for s in job.sources]
    job.update(durations=[round(i.duration, 2) for i in infos], progress=0.15, message="장면 추출 중")

    if job.mode == "manual":
        result = manual.build(job.script_text, job.product_name, job.durations)
        job.update(status="scripts_ready", progress=1.0, message="", analysis=result.model_dump())
        return

    total = sum(i.duration for i in infos)
    every = max(1.0, total / config.MAX_FRAMES)
    frame_dir = job.dir / "frames"
    shutil.rmtree(frame_dir, ignore_errors=True)
    frames: list[tuple[int, float, Path]] = []
    for vi, s in enumerate(job.sources):
        for t, p in media.extract_frames(job.dir / s, frame_dir, every, f"v{vi}"):
            if t <= infos[vi].duration:
                frames.append((vi, t, p))
    frames = frames[: config.MAX_FRAMES + len(job.sources)]

    job.update(progress=0.35, message="AI가 상품을 분석하고 원고를 쓰는 중 (1~2분)")
    result = llm.analyze(frames, job.durations, job.product_name, job.notes)
    if not job.product_name:
        job.product_name = result.product_name
    job.cleanup = suggest_cleanup(result.text_regions)
    job.update(status="scripts_ready", progress=1.0, message="", analysis=result.model_dump())


def suggest_cleanup(regions: list[llm.TextRegion]) -> dict:
    """AI가 찾은 원본 글자 영역으로 영상별 지우기 설정을 미리 채웁니다."""
    out: dict = {}
    for r in regions:
        key = str(r.video_index)
        # 영상마다 가장 큰 영역 하나만 사용
        if key in out and out[key]["box"][2] * out[key]["box"][3] >= r.w * r.h:
            continue
        band = r.w >= 0.5 and (r.y + r.h >= 0.75 or r.y <= 0.25)
        out[key] = {"mode": "crop" if band else "blur", "box": [round(v, 3) for v in (r.x, r.y, r.w, r.h)]}
    return out


def set_cleanup(job: Job, cleanup: dict) -> None:
    clean: dict = {}
    for key, val in (cleanup or {}).items():
        if not str(key).isdigit() or int(key) >= len(job.sources) or not isinstance(val, dict):
            continue
        mode = val.get("mode", "")
        box = val.get("box") or []
        if mode in ("crop", "blur", "erase") and len(box) == 4:
            clean[str(int(key))] = {"mode": mode, "box": [round(min(1, max(0, float(v))), 4) for v in box]}
    job.update(cleanup=clean)


# 2) 원고 고르기 --------------------------------------------------------------

def choose_script(job: Job, script: dict) -> None:
    parsed = llm.Script.model_validate(script)
    parsed.lines = [ln for ln in parsed.lines if ln.text.strip()]
    if not parsed.lines:
        raise ValueError("나레이션 문장이 비어 있습니다.")
    n = len(job.durations)
    for ln in parsed.lines:
        ln.video_index = min(max(0, ln.video_index), n - 1)
        ln.start_sec = min(max(0.0, ln.start_sec), max(0.0, job.durations[ln.video_index] - 0.3))
    job.update(chosen=parsed.model_dump())


# 3) 목소리 고르기 + 4) 만들기 ------------------------------------------------

def start_render(job: Job, voice: str, rate: int, bgm: str, smart_cut: bool | None = None) -> None:
    if smart_cut is not None:
        job.smart_cut = bool(smart_cut)
    if not job.chosen:
        raise ValueError("원고를 먼저 골라 주세요.")
    if bgm and not (config.BGM_DIR / bgm).is_file():
        bgm = ""
    job.update(status="rendering", progress=0.0, message="나레이션 녹음 중", voice=voice, rate=int(rate), bgm=bgm, error="")
    _bg(job, _render)


def _render(job: Job) -> None:
    script = llm.Script.model_validate(job.chosen)
    work = job.dir / "render"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    infos = [media.probe(job.dir / s) for s in job.sources]
    n = len(script.lines)

    # 문장별 음성 → 길이 측정 → 프레임 단위로 맞춘 구간 길이
    seg_lens, speech_lens, wavs = [], [], []
    for i, ln in enumerate(script.lines):
        raw = tts.synthesize(ln.text, job.voice, job.rate, work / f"tts_{i:02d}")
        speech = media.probe(raw).duration
        total = media.frame_quantize(speech + config.SENTENCE_GAP)
        wav = work / f"a_{i:02d}.wav"
        media.to_wav(raw, wav, total)
        seg_lens.append(total)
        speech_lens.append(speech)
        wavs.append(wav)
        job.update(progress=0.3 * (i + 1) / n)

    # 어색한 컷 자동 보정: 문제가 있는 구간만 가까운 깨끗한 구간으로 옮김
    starts = [ln.start_sec for ln in script.lines]
    fixes: list[str] = []
    if job.smart_cut:
        job.update(message="어색한 컷 찾는 중", progress=0.3)
        scans: dict[int, smartcut.Issues] = {}
        for i, ln in enumerate(script.lines):
            vi = ln.video_index
            if vi not in scans:
                scans[vi] = smartcut.scan(job.dir / job.sources[vi], job.dir / "scan" / f"v{vi}.json")
            new, found = smartcut.best_start(scans[vi], infos[vi].duration, ln.start_sec, seg_lens[i])
            if found:
                starts[i] = new
                moved = f"{ln.start_sec:.1f}초 → {new:.1f}초" if abs(new - ln.start_sec) >= 0.05 else "옮길 곳이 없어 그대로"
                fixes.append(f"{i + 1}번 문장(영상{vi + 1}): {', '.join(found)} · {moved}")

    # 컷 편집
    job.update(message="컷 편집 중", fixes=fixes)
    segs = []
    for i, ln in enumerate(script.lines):
        seg = work / f"v_{i:02d}.mp4"
        src = job.dir / job.sources[ln.video_index]
        media.make_segment(src, infos[ln.video_index], starts[i], seg_lens[i], seg,
                           job.cleanup.get(str(ln.video_index)))
        segs.append(seg)
        job.update(progress=0.3 + 0.4 * (i + 1) / n)

    job.update(message="자막·나레이션 합성 중", progress=0.72)
    media.concat(segs, work / "video.mp4")
    media.concat(wavs, work / "narration.wav")

    cues, t = [], 0.0
    for i, ln in enumerate(script.lines):
        cues += subtitles.cues_for_sentence(ln.text, t, speech_lens[i])
        t += seg_lens[i]
    total = t
    (work / "subs.ass").write_text(subtitles.build_ass(script.hook_line1, script.hook_line2, cues, total), encoding="utf-8")

    out_dir = job.dir / "out"
    out_dir.mkdir(exist_ok=True)
    bgm = config.BGM_DIR / job.bgm if job.bgm else None
    media.final_render(work, work / "video.mp4", work / "narration.wav", work / "subs.ass", work / "final.mp4", bgm)
    shutil.move(str(work / "final.mp4"), out_dir / "shorts.mp4")

    # 5) 내보내기용 부가 파일
    (out_dir / "subtitles.srt").write_text(subtitles.build_srt(cues), encoding="utf-8")
    (out_dir / "upload.txt").write_text(upload_text(job, script), encoding="utf-8")
    job.update(status="done", progress=1.0, message="", duration=round(total, 2))


def description_text(job: Job, script: llm.Script) -> str:
    parts = [script.description.strip()]
    if job.link:
        parts.append(f"👉 구매 링크: {job.link}")
    if script.hashtags:
        parts.append(" ".join(f"#{h}" for h in script.hashtags))
    if job.link:
        parts.append(config.COUPANG_DISCLOSURE)
    return "\n\n".join(p for p in parts if p)


def pinned_text(job: Job, script: llm.Script) -> str:
    text = script.pinned_comment.strip()
    if job.link:
        text += f"\n{job.link}\n\n{config.COUPANG_DISCLOSURE}"
    return text


def upload_text(job: Job, script: llm.Script) -> str:
    narration = "\n".join(ln.text for ln in script.lines)
    return (
        f"[제목]\n{script.title}\n\n"
        f"[설명]\n{description_text(job, script)}\n\n"
        f"[고정 댓글]\n{pinned_text(job, script)}\n\n"
        f"[나레이션 원고]\n{narration}\n"
    )


def list_bgm() -> list[str]:
    if not config.BGM_DIR.exists():
        return []
    return sorted(p.name for p in config.BGM_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg"))
