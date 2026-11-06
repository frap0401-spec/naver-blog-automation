"""드롭컷 웹 서버. `python -m dropcut` 로 실행 후 http://127.0.0.1:8000 접속."""
from __future__ import annotations

import hashlib
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, graphics, manual, media, pipeline, sfx, subtitles, tts

app = FastAPI(title="드롭컷")
STATIC = Path(__file__).parent / "static"
ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"} | media.IMAGE_EXT


def _job(job_id: str) -> pipeline.Job:
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404, "프로젝트를 찾을 수 없습니다.")
    return job


def _public(job: pipeline.Job) -> dict:
    data = asdict(job)
    data["ai"] = pipeline.ai_ready()
    if job.status == "done":
        data["export"] = {
            "description": pipeline.description_text(job),
            "reply": pipeline.reply_text(job),
        }
    return data


async def _read(files: list[UploadFile]) -> list[tuple[str, bytes]]:
    items = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in ALLOWED:
            raise HTTPException(400, f"지원하지 않는 형식입니다: {f.filename}")
        items.append((f.filename or "video.mp4", await f.read()))
    return items


@app.get("/api/config")
def get_config():
    return {
        "voices": tts.all_voices(),
        "eleven": bool(tts.ELEVEN_KEY),
        "bgm": pipeline.list_bgm(),
        "styles": [{"id": k, "name": v["name"]} for k, v in subtitles.STYLES.items()],
        "ratios": list(media.RATIOS.keys()),
        "stages": pipeline.STAGES,
        "talk_stages": pipeline.TALK_STAGES,
        "sfx": sfx.names(),
        "graphic_types": graphics.TYPES, "graphic_themes": {k: v["name"] for k, v in graphics.THEMES.items()},
        "graphic_positions": graphics.POSITIONS, "graphic_amounts": graphics.AMOUNTS,
        "beauty": {"none": "없음", "light": "약하게", "normal": "보통", "strong": "강하게"},
        "ai": pipeline.ai_ready(),
        "mock": config.LLM_BACKEND == "mock",
        "chat_prompt": manual.PROMPT_FOR_CHAT,
    }


# ---------------------------------------------------------------- 프로젝트

@app.get("/api/projects")
def projects():
    return pipeline.list_jobs()


@app.post("/api/projects")
async def create_project(files: list[UploadFile] = File(...), title: str = Form(""), link: str = Form(""),
                         mode: str = Form("auto")):
    items = await _read(files)
    job = pipeline.create(title, link, mode)
    try:
        pipeline.add_files(job, items)
    except Exception as exc:
        pipeline.delete(job)
        raise HTTPException(400, str(exc))
    return _public(job)


@app.get("/api/projects/{job_id}")
def project(job_id: str):
    return _public(_job(job_id))


@app.delete("/api/projects/{job_id}")
def delete_project(job_id: str):
    job = _job(job_id)
    if job.task:
        raise HTTPException(409, "작업 중에는 지울 수 없습니다.")
    pipeline.delete(job)
    return {"ok": True}


@app.post("/api/projects/{job_id}/files")
async def add_files(job_id: str, files: list[UploadFile] = File(...)):
    job = _job(job_id)
    try:
        pipeline.add_files(job, await _read(files))
    except Exception as exc:
        raise HTTPException(400, str(exc))
    return _public(job)


@app.delete("/api/projects/{job_id}/files/{index}")
def remove_file(job_id: str, index: int):
    job = _job(job_id)
    pipeline.remove_file(job, index)
    return _public(job)


class WriteReq(BaseModel):
    length: int = 30
    request: str = ""
    title: str = ""


@app.post("/api/projects/{job_id}/write")
def write(job_id: str, req: WriteReq):
    job = _job(job_id)
    if req.title:
        job.title = req.title.strip()
    try:
        pipeline.start_write(job, req.length, req.request)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public(job)


class TalkReq(BaseModel):
    level: str = "normal"
    drop_fillers: bool = True
    settings: dict = {}
    hook1: str = ""
    hook2: str = ""
    badge: str = ""


@app.post("/api/projects/{job_id}/talk")
def talk_start(job_id: str, req: TalkReq):
    """컷·자막 자동 편집 시작: 소리 분석 → 받아쓰기 → 자동으로 만들기까지."""
    job = _job(job_id)
    try:
        pipeline.apply_settings(job, req.settings)
        job.script.update({"hook1": req.hook1, "hook2": req.hook2, "badge": req.badge})
        pipeline.start_talk(job, req.level if req.level in ("loose", "normal", "tight") else "normal", req.drop_fillers)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public(job)


class MakeReq(BaseModel):
    script_text: str | None = None
    hook1: str = ""
    hook2: str = ""
    badge: str = ""
    lines: list[dict] | None = None
    pieces: list[dict] | None = None
    settings: dict = {}
    upload: dict | None = None
    rechoose: bool = False
    save_only: bool = False


@app.post("/api/projects/{job_id}/make")
def make(job_id: str, req: MakeReq):
    """원고·설정을 저장하고 (save_only가 아니면) 영상을 만듭니다."""
    job = _job(job_id)
    if job.task:
        raise HTTPException(409, "이미 작업 중입니다.")
    if req.settings.get("voice") and not tts.is_known(req.settings["voice"]):
        raise HTTPException(400, "알 수 없는 목소리입니다.")
    try:
        pipeline.apply_settings(job, req.settings)
        if req.script_text is not None:
            pipeline.set_script(job, req.script_text, req.hook1, req.hook2, req.badge)
        else:
            job.script.update({"hook1": req.hook1, "hook2": req.hook2, "badge": req.badge})
        if req.lines is not None:
            pipeline.set_lines(job, req.lines)
        if req.pieces is not None:
            pipeline.set_talk(job, req.pieces)
        if req.upload is not None:
            job.upload = {k: str(v) for k, v in req.upload.items()}
        job.save()
        if not req.save_only:
            pipeline.start_make(job, req.rechoose)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public(job)


@app.post("/api/projects/{job_id}/cleanup")
def set_cleanup(job_id: str, cleanup: dict):
    job = _job(job_id)
    pipeline.set_cleanup(job, cleanup)
    return _public(job)


# ---------------------------------------------------------------- 이미지·파일

def _src(job: pipeline.Job, index: int) -> Path:
    if not 0 <= index < len(job.sources):
        raise HTTPException(404)
    return job.dir / job.sources[index]["path"]


def _cached_image(out: Path, make) -> FileResponse:
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            make(out)
        except media.MediaError as exc:
            raise HTTPException(500, str(exc))
    return FileResponse(out, media_type="image/jpeg")


@app.get("/api/projects/{job_id}/thumb/{index}")
def thumb(job_id: str, index: int, t: float = -1):
    job = _job(job_id)
    src = _src(job, index)
    if t < 0:
        t = job.durations[index] / 3
    return _cached_image(job.dir / "thumbs" / f"{src.stem}_{t:.1f}.jpg", lambda o: media.thumbnail(src, t, o))


@app.get("/api/projects/{job_id}/strip/{index}")
def strip(job_id: str, index: int):
    job = _job(job_id)
    src = _src(job, index)
    return _cached_image(job.dir / "thumbs" / f"{src.stem}_strip.jpg",
                         lambda o: media.filmstrip(src, job.durations[index], o))


@app.get("/api/projects/{job_id}/cleanpreview/{index}")
def clean_preview(job_id: str, index: int, t: float = -1):
    job = _job(job_id)
    src = _src(job, index)
    info = media.probe(src)
    if t < 0:
        t = info.duration / 2
    c = job.cleanup.get(str(index))
    key = hashlib.md5(repr((t, c, job.ratio)).encode()).hexdigest()[:8]
    return _cached_image(job.dir / "thumbs" / f"p{src.stem}_{key}.jpg",
                         lambda o: media.preview_frame(src, info, t, c, o, media.size_of(job.ratio)))


@app.get("/api/projects/{job_id}/source/{index}")
def source(job_id: str, index: int):
    job = _job(job_id)
    return FileResponse(_src(job, index))


@app.get("/api/projects/{job_id}/cover")
def cover(job_id: str):
    job = _job(job_id)
    path = job.dir / "out" / "cover.jpg"
    if not path.exists():
        if job.sources:
            return thumb(job_id, 0)
        raise HTTPException(404)
    return FileResponse(path, media_type="image/jpeg")


@app.get("/api/projects/{job_id}/line/{index}/audio")
def line_audio(job_id: str, index: int):
    job = _job(job_id)
    if not 0 <= index < len(job.script.get("lines", [])):
        raise HTTPException(404)
    try:
        return FileResponse(pipeline.line_audio(job, index))
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)


FILES = {"video": ("shorts.mp4", "video/mp4"), "srt": ("subtitles.srt", "text/plain"), "txt": ("upload.txt", "text/plain")}


@app.get("/api/projects/{job_id}/files/{kind}")
def download(job_id: str, kind: str, dl: int = 0):
    job = _job(job_id)
    if kind not in FILES:
        raise HTTPException(404)
    name, mime = FILES[kind]
    path = job.dir / "out" / name
    if kind == "txt" and job.status == "done":
        path.write_text(pipeline.upload_text(job), encoding="utf-8")
    if not path.exists():
        raise HTTPException(404, "아직 만들어지지 않았습니다.")
    base = (job.title or "shorts").replace("/", "_").replace("\\", "_")[:40]
    return FileResponse(path, media_type=mime, filename=f"{base}_{name}" if dl else None)


@app.get("/api/sfx/{name}")
def sfx_preview(name: str):
    path = sfx.path(name)
    if not path:
        raise HTTPException(404)
    return FileResponse(path)


@app.get("/api/voices/{voice:path}/preview")
def voice_preview(voice: str, rate: int = 5):
    if not tts.is_known(voice):
        raise HTTPException(404)
    rate = max(-30, min(50, rate))
    key = hashlib.md5(f"{voice}{rate}{config.TTS_BACKEND}".encode()).hexdigest()[:10]
    cache = config.WORKSPACE / "_preview"
    for ext in (".mp3", ".wav"):
        if (cache / f"{key}{ext}").exists():
            return FileResponse(cache / f"{key}{ext}")
    try:
        path = tts.synthesize(tts.PREVIEW_TEXT, voice, rate, cache / key)
    except Exception as exc:
        return JSONResponse({"detail": str(exc)}, status_code=502)
    return FileResponse(path)


app.mount("/", StaticFiles(directory=STATIC, html=True), name="static")
