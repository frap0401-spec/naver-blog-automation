"""드롭컷 웹 서버. `python -m dropcut` 로 실행 후 http://127.0.0.1:8000 접속."""
from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, llm, pipeline, tts

app = FastAPI(title="드롭컷")
STATIC = Path(__file__).parent / "static"
ALLOWED = {".mp4", ".mov", ".m4v", ".webm", ".mkv", ".avi"}


def _job(job_id: str) -> pipeline.Job:
    job = pipeline.get(job_id)
    if not job:
        raise HTTPException(404, "작업을 찾을 수 없습니다.")
    return job


def _public(job: pipeline.Job) -> dict:
    data = {
        k: getattr(job, k)
        for k in ("id", "product_name", "link", "status", "progress", "message", "analysis",
                  "chosen", "voice", "rate", "bgm", "error", "duration", "durations")
    }
    if job.status == "done" and job.chosen:
        script = llm.Script.model_validate(job.chosen)
        data["export"] = {
            "title": script.title,
            "description": pipeline.description_text(job, script),
            "pinned": pipeline.pinned_text(job, script),
        }
    return data


@app.get("/api/config")
def get_config():
    return {
        "voices": tts.VOICES,
        "bgm": pipeline.list_bgm(),
        "llm": config.LLM_BACKEND,
        "tts": config.TTS_BACKEND,
    }


@app.post("/api/jobs")
async def create_job(
    files: list[UploadFile] = File(...),
    product_name: str = Form(""),
    notes: str = Form(""),
    link: str = Form(""),
):
    items = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in ALLOWED:
            raise HTTPException(400, f"지원하지 않는 형식입니다: {f.filename}")
        items.append((f.filename or "video.mp4", await f.read()))
    if not items:
        raise HTTPException(400, "영상을 올려 주세요.")
    if len(items) > 10:
        raise HTTPException(400, "영상은 최대 10개까지 올릴 수 있습니다.")
    job = pipeline.create(items, product_name, notes, link)
    pipeline.start_analysis(job)
    return _public(job)


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    return _public(_job(job_id))


@app.post("/api/jobs/{job_id}/retry")
def retry(job_id: str):
    job = _job(job_id)
    if job.status in ("analyzing", "rendering"):
        raise HTTPException(409, "이미 진행 중입니다.")
    if job.chosen and job.analysis:
        pipeline.start_render(job, job.voice, job.rate, job.bgm)
    else:
        pipeline.start_analysis(job)
    return _public(job)


@app.post("/api/jobs/{job_id}/script")
def choose_script(job_id: str, script: dict):
    job = _job(job_id)
    try:
        pipeline.choose_script(job, script)
    except Exception as exc:
        raise HTTPException(400, f"원고 형식이 올바르지 않습니다: {exc}")
    return _public(job)


class RenderReq(BaseModel):
    voice: str
    rate: int = 10
    bgm: str = ""


@app.post("/api/jobs/{job_id}/render")
def render(job_id: str, req: RenderReq):
    job = _job(job_id)
    if job.status in ("analyzing", "rendering"):
        raise HTTPException(409, "이미 진행 중입니다.")
    if req.voice not in {v["id"] for v in tts.VOICES}:
        raise HTTPException(400, "알 수 없는 목소리입니다.")
    try:
        pipeline.start_render(job, req.voice, max(-30, min(50, req.rate)), req.bgm)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return _public(job)


FILES = {"video": ("shorts.mp4", "video/mp4"), "srt": ("subtitles.srt", "text/plain"), "txt": ("upload.txt", "text/plain")}


@app.get("/api/jobs/{job_id}/files/{kind}")
def download(job_id: str, kind: str, dl: int = 0):
    job = _job(job_id)
    if kind not in FILES:
        raise HTTPException(404)
    name, mime = FILES[kind]
    path = job.dir / "out" / name
    if not path.exists():
        raise HTTPException(404, "아직 만들어지지 않았습니다.")
    base = (job.product_name or "shorts").replace("/", "_")[:30]
    filename = f"{base}_{name}" if dl else None
    return FileResponse(path, media_type=mime, filename=filename)


@app.get("/api/jobs/{job_id}/source/{index}")
def source(job_id: str, index: int):
    job = _job(job_id)
    if not 0 <= index < len(job.sources):
        raise HTTPException(404)
    return FileResponse(job.dir / job.sources[index])


@app.get("/api/voices/{voice}/preview")
def voice_preview(voice: str, rate: int = 10):
    if voice not in {v["id"] for v in tts.VOICES}:
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
