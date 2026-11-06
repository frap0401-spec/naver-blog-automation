"""프로젝트(Job) 단위 작업 흐름.

올리기 → (원고·업로드 글 쓰기) → 만들기[목소리 → 영상 살펴보기 → 장면 고르기 → 이어 붙이기 → 자막·문구 → 미리보기]
→ 편집(문장·장면 수정) → 다시 만들기 → 내보내기
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import traceback
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import config, llm, manual, media, smartcut, subtitles, tts

STAGES = ["목소리 만들기", "영상 살펴보기", "장면 고르기 (Claude)", "장면 이어 붙이기", "자막·문구 만들기", "미리보기 준비"]


@dataclass
class Job:
    id: str
    created: float = field(default_factory=time.time)
    title: str = ""
    link: str = ""
    sources: list = field(default_factory=list)   # [{"name", "path", "kind": "video"|"photo"}]
    durations: list = field(default_factory=list)
    status: str = "draft"   # draft | done | error
    task: str = ""          # "" | writing | making
    stage: int = -1
    started: float = 0.0
    elapsed: float = 0.0
    progress: float = 0.0
    message: str = ""
    error: str = ""
    analysis: dict | None = None
    length: int = 30
    request: str = ""
    script: dict = field(default_factory=lambda: {"hook1": "", "hook2": "", "badge": "", "lines": []})
    voice: str = field(default_factory=tts.default_voice)
    rate: int = 5
    ratio: str = "9:16"
    style: str = "insta"
    bgm: str = ""
    smart_cut: bool = True
    cleanup: dict = field(default_factory=dict)
    fixes: list = field(default_factory=list)
    duration: float = 0.0
    seg_lens: list = field(default_factory=list)
    upload: dict = field(default_factory=dict)

    @property
    def dir(self) -> Path:
        return config.WORKSPACE / self.id

    def save(self) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / "job.json.tmp"
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.dir / "job.json")

    def update(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self, k, v)
        self.save()


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def _load(path: Path) -> Job | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if data.get("sources") and isinstance(data["sources"][0], str):
        return None  # 예전 버전 작업은 건너뜀
    known = Job.__dataclass_fields__.keys()
    return Job(**{k: v for k, v in data.items() if k in known})


def get(job_id: str) -> Job | None:
    if not job_id.isalnum():
        return None
    with _lock:
        if job_id in _jobs:
            return _jobs[job_id]
    job = _load(config.WORKSPACE / job_id / "job.json")
    if job:
        if job.task:  # 프로그램 재시작으로 중단된 작업
            job.task, job.stage = "", -1
            if job.status != "done":
                job.status, job.error = "error", "프로그램이 다시 시작되어 작업이 중단되었습니다. 다시 시도해 주세요."
        with _lock:
            _jobs[job_id] = job
    return job


def list_jobs() -> list[dict]:
    out = []
    if not config.WORKSPACE.exists():
        return out
    for d in config.WORKSPACE.iterdir():
        if not (d / "job.json").exists():
            continue
        job = get(d.name)
        if not job:
            continue
        out.append({
            "id": job.id, "title": job.title or "제목 없음", "status": job.status, "task": job.task,
            "created": job.created, "duration": job.duration, "sources": len(job.sources),
            "has_cover": (job.dir / "out" / "cover.jpg").exists(),
        })
    return sorted(out, key=lambda x: -x["created"])


def delete(job: Job) -> None:
    with _lock:
        _jobs.pop(job.id, None)
    shutil.rmtree(job.dir, ignore_errors=True)


# ---------------------------------------------------------------- 파일

def create(title: str = "", link: str = "") -> Job:
    job = Job(id=uuid.uuid4().hex[:12], title=title.strip(), link=link.strip())
    job.save()
    with _lock:
        _jobs[job.id] = job
    return job


def add_files(job: Job, files: list[tuple[str, bytes]]) -> None:
    src_dir = job.dir / "src"
    src_dir.mkdir(parents=True, exist_ok=True)
    for name, data in files:
        ext = Path(name).suffix.lower() or ".mp4"
        stem = uuid.uuid4().hex[:8]
        raw = src_dir / f"{stem}{ext}"
        raw.write_bytes(data)
        if ext in media.IMAGE_EXT:
            vid = src_dir / f"{stem}.mp4"
            media.photo_to_video(raw, vid)
            entry = {"name": name, "path": str(vid.relative_to(job.dir)), "kind": "photo"}
            path = vid
        else:
            entry = {"name": name, "path": str(raw.relative_to(job.dir)), "kind": "video"}
            path = raw
        info = media.probe(path)
        if info.duration <= 0:
            raise ValueError(f"영상 길이를 읽을 수 없습니다: {name}")
        job.sources.append(entry)
        job.durations.append(round(info.duration, 2))
    _invalidate_frames(job)
    job.save()


def remove_file(job: Job, index: int) -> None:
    if not 0 <= index < len(job.sources):
        return
    job.sources.pop(index)
    job.durations.pop(index)
    for ln in job.script.get("lines", []):
        clips = [c for c in ln.get("clips", []) if c["v"] != index]
        for c in clips:
            if c["v"] > index:
                c["v"] -= 1
        ln["clips"] = clips
    job.cleanup = {str(int(k) - (int(k) > index)): v for k, v in job.cleanup.items() if int(k) != index}
    _invalidate_frames(job)
    job.save()


def _invalidate_frames(job: Job) -> None:
    shutil.rmtree(job.dir / "frames", ignore_errors=True)


def _frames(job: Job) -> list[tuple[int, float, Path]]:
    """Claude에게 보여줄 장면들(한 번 뽑으면 재사용)."""
    frame_dir = job.dir / "frames"
    index = frame_dir / "index.json"
    if index.exists():
        return [(v, t, frame_dir / n) for v, t, n in json.loads(index.read_text())]
    total = sum(job.durations)
    every = max(1.0, total / config.MAX_FRAMES)
    frames = []
    for vi, s in enumerate(job.sources):
        for t, p in media.extract_frames(job.dir / s["path"], frame_dir, every, f"v{vi}"):
            if t <= job.durations[vi]:
                frames.append((vi, t, p))
    frames = frames[: config.MAX_FRAMES + len(job.sources)]
    index.write_text(json.dumps([(v, t, p.name) for v, t, p in frames]))
    return frames


def _bg(job: Job, fn) -> None:
    def runner():
        try:
            fn(job)
        except Exception as exc:
            traceback.print_exc()
            job.update(task="", stage=-1, status="done" if job.status == "done" else "error", error=str(exc), message="")

    threading.Thread(target=runner, daemon=True).start()


def ai_ready() -> bool:
    return config.LLM_BACKEND == "mock" or bool(os.getenv("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_AUTH_TOKEN"))


# ---------------------------------------------------------------- 원고·업로드 글 쓰기

def start_write(job: Job, length: int, request: str) -> None:
    if job.task:
        raise ValueError("이미 작업 중입니다.")
    if not job.sources:
        raise ValueError("영상이나 사진을 먼저 넣어 주세요.")
    if not ai_ready():
        raise ValueError("원고를 쓰려면 .env에 ANTHROPIC_API_KEY가 필요합니다. 원고 칸에 직접 쓰셔도 됩니다.")
    job.update(task="writing", error="", length=int(length), request=request.strip(),
               message="장면 살펴보는 중", started=time.time())
    _bg(job, _write)


def _write(job: Job) -> None:
    frames = _frames(job)
    job.update(message="Claude가 원고와 업로드 글을 쓰는 중 (1~2분)")
    a = llm.write(frames, job.durations, job.title, job.request, job.length)
    if not job.cleanup:
        job.cleanup = suggest_cleanup(a.text_regions)
    if not job.title:
        job.title = a.product_name
    job.update(task="", message="", analysis=a.model_dump(), upload={})


def suggest_cleanup(regions: list[llm.TextRegion]) -> dict:
    """AI가 찾은 원본 글자 영역으로 영상별 '글자 가리기'를 미리 채웁니다."""
    out: dict = {}
    for r in regions:
        key = str(r.video_index)
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
        mode, box = val.get("mode", ""), val.get("box") or []
        if mode in ("crop", "blur", "erase") and len(box) == 4:
            clean[str(int(key))] = {"mode": mode, "box": [round(min(1, max(0, float(v))), 4) for v in box]}
    job.update(cleanup=clean)


# ---------------------------------------------------------------- 만들기

SETTINGS = ("voice", "rate", "ratio", "style", "bgm", "smart_cut", "title", "link")


def apply_settings(job: Job, data: dict) -> None:
    for k in SETTINGS:
        if k in data and data[k] is not None:
            setattr(job, k, data[k])
    if job.ratio not in media.RATIOS:
        job.ratio = "9:16"
    if job.style not in subtitles.STYLES:
        job.style = "insta"
    if job.bgm and not (config.BGM_DIR / job.bgm).is_file():
        job.bgm = ""
    job.rate = max(-30, min(50, int(job.rate)))


def set_script(job: Job, text: str, hook1: str, hook2: str, badge: str) -> None:
    """원고 칸 내용으로 문장 목록을 갱신합니다. 같은 문장은 고른 장면을 유지합니다."""
    parsed = manual.parse(text)
    old = {ln["text"]: ln for ln in job.script.get("lines", [])}
    lines = []
    for t in parsed["lines"]:
        prev = old.get(t)
        lines.append(prev if prev else {"text": t, "clips": [], "orig_audio": False, "reason": ""})
    if not lines:
        raise ValueError("원고가 비어 있습니다. 한 줄에 한 문장씩 적어 주세요.")
    job.script = {
        "hook1": parsed.get("hook1", hook1 or "").strip(), "hook2": parsed.get("hook2", hook2 or "").strip(),
        "badge": parsed.get("badge", badge or "").strip(), "lines": lines,
    }


def set_lines(job: Job, lines: list[dict]) -> None:
    """편집 화면에서 고친 문장·장면을 반영합니다."""
    nsrc = len(job.sources)
    out = []
    for ln in lines:
        text = str(ln.get("text", "")).strip()
        if not text:
            continue
        clips = []
        for c in ln.get("clips", [])[:3]:
            v = int(c.get("v", 0))
            if 0 <= v < nsrc:
                clips.append({"v": v, "start": round(max(0.0, min(float(c.get("start", 0)), job.durations[v])), 2)})
        out.append({"text": text, "clips": clips, "orig_audio": bool(ln.get("orig_audio")), "reason": ln.get("reason", "")})
    if not out:
        raise ValueError("문장이 하나도 없습니다.")
    job.script["lines"] = out


def start_make(job: Job, rechoose: bool = False) -> None:
    if job.task:
        raise ValueError("이미 작업 중입니다.")
    if not job.sources:
        raise ValueError("영상이나 사진을 먼저 넣어 주세요.")
    if not job.script.get("lines"):
        raise ValueError("원고가 비어 있습니다.")
    if rechoose:
        for ln in job.script["lines"]:
            ln["clips"], ln["reason"] = [], ""
    job.update(task="making", stage=0, started=time.time(), progress=0, error="", message="")
    _bg(job, _make)


def _tts_cached(job: Job, text: str) -> Path:
    key = hashlib.md5(f"{text}|{job.voice}|{job.rate}|{config.TTS_BACKEND}".encode()).hexdigest()[:16]
    cache = job.dir / "tts"
    for ext in (".mp3", ".wav"):
        if (cache / f"{key}{ext}").exists():
            return cache / f"{key}{ext}"
    return tts.synthesize(subtitles.strip_marks(text), job.voice, job.rate, cache / key)


def line_audio(job: Job, index: int) -> Path:
    return _tts_cached(job, job.script["lines"][index]["text"])


def _make(job: Job) -> None:
    lines = job.script["lines"]
    n = len(lines)
    size = media.size_of(job.ratio)
    work = job.dir / "render"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)

    # 1. 목소리
    speech, seg_lens, wavs = [], [], []
    for i, ln in enumerate(lines):
        job.update(message=f"목소리 {i + 1}/{n}: {ln['text']}", progress=i / n)
        raw = _tts_cached(job, ln["text"])
        sp = media.probe(raw).duration
        total = media.frame_quantize(sp + config.SENTENCE_GAP)
        wav = work / f"a_{i:02d}.wav"
        media.to_wav(raw, wav, total)
        speech.append(sp)
        seg_lens.append(total)
        wavs.append(wav)

    # 2. 영상 살펴보기
    job.update(stage=1, message="영상 살펴보는 중", progress=0)
    infos = [media.probe(job.dir / s["path"]) for s in job.sources]
    scans = {}
    if job.smart_cut:
        for vi, s in enumerate(job.sources):
            scans[vi] = smartcut.scan(job.dir / s["path"], job.dir / "scan" / f"{Path(s['path']).stem}.json")

    # 3. 장면 고르기
    job.update(stage=2, message="문장마다 어울리는 장면 고르는 중")
    need = [i for i, ln in enumerate(lines) if not ln.get("clips")]
    if need:
        choices = []
        if ai_ready() and config.LLM_BACKEND != "mock":
            try:
                choices = llm.pick_scenes(_frames(job), job.durations, [ln["text"] for ln in lines], seg_lens)
            except Exception as exc:
                print("[드롭컷] Claude 장면 고르기 실패, 자동 배치로 대신합니다:", exc)
        by_line = {c.line_index: c for c in choices}
        auto = manual.auto_place(seg_lens, job.durations)
        nsrc = len(job.sources)
        for i in need:
            c = by_line.get(i)
            if c and 0 <= c.video_index < nsrc:
                clips = [{"v": c.video_index, "start": round(max(0.0, c.start_sec), 2)}]
                if 0 <= c.second_video_index < nsrc and seg_lens[i] > 3:
                    clips.append({"v": c.second_video_index, "start": round(max(0.0, c.second_start_sec), 2)})
                lines[i]["clips"], lines[i]["reason"] = clips, c.reason
            else:
                v, st = auto[i]
                lines[i]["clips"], lines[i]["reason"] = [{"v": v, "start": st}], "영상 순서대로 자동 배치"

    # 어색한 컷 보정
    fixes = []
    for i, ln in enumerate(lines):
        part = seg_lens[i] / len(ln["clips"])
        for c in ln["clips"]:
            if c["v"] in scans:
                new, found = smartcut.best_start(scans[c["v"]], infos[c["v"]].duration, c["start"], part)
                if found and abs(new - c["start"]) >= 0.05:
                    fixes.append(f"{i + 1}번 문장: {', '.join(found)} · {c['start']:.1f}초 → {new:.1f}초")
                    c["start"] = new
    job.update(fixes=fixes, seg_lens=seg_lens)

    # 4. 장면 이어 붙이기
    job.update(stage=3, message="장면 이어 붙이는 중", progress=0)
    segs, origs = [], []
    for i, ln in enumerate(lines):
        clips = ln["clips"]
        parts = [media.frame_quantize(seg_lens[i] / len(clips))] * len(clips)
        parts[-1] = max(1 / config.FPS, round(seg_lens[i] - sum(parts[:-1]), 4))
        for k, c in enumerate(clips):
            v = c["v"]
            src = job.dir / job.sources[v]["path"]
            seg = work / f"v_{i:02d}_{k}.mp4"
            media.make_segment(src, infos[v], c["start"], parts[k], seg, job.cleanup.get(str(v)), size)
            segs.append(seg)
            oa = work / f"o_{i:02d}_{k}.wav"
            media.segment_audio(src, infos[v], c["start"], parts[k], oa, bool(ln.get("orig_audio")))
            origs.append(oa)
        job.update(progress=(i + 1) / n, message=f"장면 {i + 1}/{n}")
    media.concat(segs, work / "video.mp4")
    media.concat(wavs, work / "narration.wav")
    use_orig = any(ln.get("orig_audio") for ln in lines)
    if use_orig:
        media.concat(origs, work / "orig.wav")

    # 5. 자막·문구
    job.update(stage=4, message="자막·문구 만드는 중")
    cues, t = [], 0.0
    for i, ln in enumerate(lines):
        cues += subtitles.cues_for_sentence(ln["text"], t, speech[i])
        t += seg_lens[i]
    total = t
    sc = job.script
    ass = subtitles.build_ass(sc["hook1"], sc["hook2"], cues, total, size, job.style, sc.get("badge", ""))
    (work / "subs.ass").write_text(ass, encoding="utf-8")

    # 6. 미리보기 준비
    job.update(stage=5, message="영상 마무리하는 중")
    out_dir = job.dir / "out"
    out_dir.mkdir(exist_ok=True)
    bgm = config.BGM_DIR / job.bgm if job.bgm else None
    media.final_render(work, work / "video.mp4", work / "narration.wav", work / "subs.ass", work / "final.mp4",
                       bgm, work / "orig.wav" if use_orig else None)
    shutil.move(str(work / "final.mp4"), out_dir / "shorts.mp4")
    media.thumbnail(out_dir / "shorts.mp4", min(1.0, total / 2), out_dir / "cover.jpg")
    (out_dir / "subtitles.srt").write_text(subtitles.build_srt(cues), encoding="utf-8")
    if not job.upload:
        job.upload = default_upload(job)
    (out_dir / "upload.txt").write_text(upload_text(job), encoding="utf-8")
    job.update(task="", stage=-1, status="done", progress=1.0, message="", duration=round(total, 2),
               elapsed=round(time.time() - job.started, 1))


# ---------------------------------------------------------------- 업로드 글

def default_upload(job: Job) -> dict:
    a = job.analysis or {}
    titles = a.get("titles") or [job.title or "쇼핑 추천템"]
    return {
        "title": titles[0],
        "description": a.get("description", ""),
        "keywords": " ".join(f"#{k}" for k in a.get("keywords", [])),
        "reply": a.get("reply") or "제품 정보는 고정 댓글에서 확인하세요!",
        "dm": a.get("dm", ""),
    }


def description_text(job: Job) -> str:
    u = job.upload or default_upload(job)
    parts = [u.get("description", "").strip()]
    if job.link:
        parts.append(f"👉 구매 링크: {job.link}")
    if u.get("keywords"):
        parts.append(u["keywords"])
    if job.link:
        parts.append(config.COUPANG_DISCLOSURE)
    return "\n\n".join(p for p in parts if p)


def reply_text(job: Job) -> str:
    u = job.upload or default_upload(job)
    text = u.get("reply", "").strip()
    if job.link:
        text += f"\n{job.link}\n\n{config.COUPANG_DISCLOSURE}"
    return text


def upload_text(job: Job) -> str:
    u = job.upload or default_upload(job)
    narration = "\n".join(ln["text"] for ln in job.script.get("lines", []))
    return (
        f"[제목]\n{u.get('title', '')}\n\n[설명]\n{description_text(job)}\n\n"
        f"[답글·고정 댓글]\n{reply_text(job)}\n\n[DM 문구]\n{u.get('dm', '')}\n\n[나레이션 원고]\n{narration}\n"
    )


def list_bgm() -> list[str]:
    if not config.BGM_DIR.exists():
        return []
    return sorted(p.name for p in config.BGM_DIR.iterdir() if p.suffix.lower() in (".mp3", ".wav", ".m4a", ".aac", ".ogg"))
