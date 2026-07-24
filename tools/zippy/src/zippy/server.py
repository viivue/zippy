"""FastAPI app: static UI, native file picker, and job APIs for vidopt/imgopt/fontslice."""

from __future__ import annotations

import json
import queue
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from imgopt.cli import DEFAULT_QUALITY as IMG_DEFAULT_QUALITY
from pydantic import BaseModel, Field
from vidopt.cli import DEFAULT_QUALITY as VID_DEFAULT_QUALITY
from vidopt.cli import DEFAULT_SPEED as VID_DEFAULT_SPEED

from . import browse as browse_mod
from .jobs import Job, JobRegistry
from .runners import run_fontslice_job, run_imgopt_job, run_vidopt_job

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="zippy")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

registry = JobRegistry()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# ── file/folder browsing ─────────────────────────────────────────────────────


class BrowseRequest(BaseModel):
    mode: Literal["file", "files", "folder"] = "folder"
    filetypes: list[tuple[str, str]] | None = None


@app.post("/api/browse")
def api_browse(body: BrowseRequest) -> dict:
    if not browse_mod.available():
        raise HTTPException(
            status_code=501, detail="tkinter is not available on this system"
        )
    try:
        result = browse_mod.browse(body.mode, body.filetypes)
    except RuntimeError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    if body.mode == "files":
        return {"paths": result or []}
    return {"path": result}


# ── vidopt ────────────────────────────────────────────────────────────────────


class VidoptJobRequest(BaseModel):
    input: str | list[str]
    output: str | None = None
    quality: int = Field(default=VID_DEFAULT_QUALITY, ge=1, le=5)
    speed: Literal["fast", "balanced", "slow", "thorough"] = VID_DEFAULT_SPEED
    h265: bool = False
    max_width: int | None = None
    recursive: bool = False
    overwrite: bool = False
    dry_run: bool = False


@app.post("/api/vidopt/jobs")
def api_vidopt_job(body: VidoptJobRequest) -> dict:
    job = registry.create("vidopt", lambda j: run_vidopt_job(j, body.model_dump()))
    return {"job_id": job.id}


# ── imgopt ────────────────────────────────────────────────────────────────────


class ImgoptJobRequest(BaseModel):
    input: str | list[str]
    output: str | None = None
    quality: int = Field(default=IMG_DEFAULT_QUALITY, ge=1, le=5)
    format: Literal["original", "webp", "jpg"] = "original"
    max_width: int | None = None
    max_height: int | None = None
    keep_exif: bool = False
    recursive: bool = False
    overwrite: bool = False
    dry_run: bool = False


@app.post("/api/imgopt/jobs")
def api_imgopt_job(body: ImgoptJobRequest) -> dict:
    job = registry.create("imgopt", lambda j: run_imgopt_job(j, body.model_dump()))
    return {"job_id": job.id}


# ── fontslice ─────────────────────────────────────────────────────────────────


@app.get("/api/fontslice/scan")
def api_fontslice_scan(
    dir: str | None = None, fonts_dir: str | None = None, config: str | None = None
) -> dict:
    from fontslice.list_fonts import discover_fonts

    try:
        resolved_fonts_dir, config_path, fonts = discover_fonts(
            base=dir, fonts_dir=fonts_dir, config=config
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"fonts_dir": resolved_fonts_dir, "config_path": config_path, "fonts": fonts}


class FontSpec(BaseModel):
    font_path: str
    basename: str
    family_name: str
    weight_min: str
    weight_max: str
    opsz: str = ""
    weight_override: str | None = None


class FontsliceJobRequest(BaseModel):
    fonts_dir: str
    fonts: list[FontSpec]
    subsets: list[str] | None = None
    text_file: str | None = None


@app.post("/api/fontslice/jobs")
def api_fontslice_job(body: FontsliceJobRequest) -> dict:
    job = registry.create(
        "fontslice", lambda j: run_fontslice_job(j, body.model_dump())
    )
    return {"job_id": job.id}


# ── job status / SSE ──────────────────────────────────────────────────────────


@app.get("/api/jobs")
def api_jobs_list() -> list[dict]:
    return [j.to_dict() for j in registry.list()]


@app.get("/api/jobs/{job_id}")
def api_job_detail(job_id: str) -> dict:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return job.to_dict()


def _sse_stream(job: Job):
    q = job.subscribe()
    try:
        while True:
            try:
                payload = q.get(timeout=15)
            except queue.Empty:
                yield ": ping\n\n"
                continue
            yield f"data: {json.dumps(payload)}\n\n"
            if payload["status"] in ("done", "failed"):
                break
    finally:
        job.unsubscribe(q)


@app.get("/api/jobs/{job_id}/events")
def api_job_events(job_id: str) -> StreamingResponse:
    job = registry.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return StreamingResponse(_sse_stream(job), media_type="text/event-stream")
