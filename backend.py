import os, re, shutil, subprocess, threading, uuid
from pathlib import Path
from typing import Optional
from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE = Path(os.getenv("DATA_DIR", "/tmp/rnyftbl_jobs")).resolve()
BASE.mkdir(parents=True, exist_ok=True)
MAX_BYTES = int(os.getenv("MAX_UPLOAD_BYTES", str(500 * 1024 * 1024)))
ALLOWED = {".mp4", ".mov", ".m4v", ".webm"}
jobs = {}
lock = threading.Lock()
app = FastAPI(title="RNYFTBL UPSCALLER AI API", version="0.1.0")

class ProcessSettings(BaseModel):
    resolution: str = Field(default="1080p", pattern="^(Original|720p|1080p|2K|4K)$")
    denoise: int = Field(default=40, ge=0, le=100)
    sharpen: int = Field(default=55, ge=0, le=100)
    detail: int = Field(default=65, ge=0, le=100)
    color: int = Field(default=35, ge=0, le=100)
    fps: str = Field(default="Keep original", pattern="^(Keep original|30 FPS|60 FPS)$")

def tool_path(name):
    p = shutil.which(name)
    if not p:
        raise RuntimeError(f"{name} is not installed on the server")
    return p

def update(job_id, **values):
    with lock:
        jobs[job_id].update(values)

def run_processing(job_id, settings):
    job = jobs[job_id]
    source, output = Path(job["source"]), Path(job["output"])
    try:
        ffmpeg = tool_path("ffmpeg")
        ffprobe = tool_path("ffprobe")
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(source)],
            capture_output=True, text=True, timeout=30, check=True
        )
        duration = max(float(probe.stdout.strip() or 0), 0.1)
        scale_map = {"720p": 720, "1080p": 1080, "2K": 1440, "4K": 2160}
        filters = []
        if settings.resolution != "Original":
            height = scale_map[settings.resolution]
            filters.append(f"scale=-2:{height}:flags=lanczos")
        if settings.denoise:
            strength = round(settings.denoise / 100 * 4, 2)
            filters.append(f"hqdn3d={strength}:{strength}:{strength}:{strength}")
        if settings.sharpen:
            amount = round(settings.sharpen / 100 * 1.5, 2)
            filters.append(f"unsharp=5:5:{amount}:5:5:0")
        if settings.color:
            sat = 1 + (settings.color / 100 * 0.25)
            filters.append(f"eq=saturation={sat:.3f}")
        cmd = [ffmpeg, "-y", "-i", str(source)]
        if filters:
            cmd += ["-vf", ",".join(filters)]
        if settings.fps != "Keep original":
            cmd += ["-r", settings.fps.split()[0]]
        cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "19",
                "-c:a", "aac", "-movflags", "+faststart", "-progress", "pipe:1",
                "-nostats", str(output)]
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                text=True, bufsize=1)
        for line in proc.stdout:
            if line.startswith("out_time_ms="):
                try:
                    seconds = int(line.split("=", 1)[1]) / 1_000_000
                    update(job_id, progress=min(99, int(seconds / duration * 100)),
                           message="Applying FFmpeg enhancement filters…")
                except ValueError:
                    pass
        stderr = proc.stderr.read()
        code = proc.wait()
        if code != 0:
            raise RuntimeError(stderr[-1200:] or "FFmpeg processing failed")
        update(job_id, status="completed", progress=100,
               message="Complete. This version uses standard FFmpeg filters, not an AI model.")
    except Exception as exc:
        update(job_id, status="failed", message=str(exc), progress=0)

@app.get("/api/health")
def health():
    return {"ok": True, "service": "RNYFTBL UPSCALLER AI", "version": "0.1.0"}

@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...)):
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED:
        raise HTTPException(415, "Supported formats: MP4, MOV, M4V, WebM")
    job_id = str(uuid.uuid4())
    folder = (BASE / job_id).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    source = folder / ("input" + suffix)
    total = 0
    try:
        with source.open("wb") as out:
            while chunk := await file.read(1024 * 1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise HTTPException(413, "Video exceeds the upload size limit")
                out.write(chunk)
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    finally:
        await file.close()
    with lock:
        jobs[job_id] = {"id": job_id, "status": "uploaded", "progress": 0,
                        "message": "Upload complete. Ready to process.",
                        "source": str(source), "output": str(folder / "enhanced.mp4")}
    return {"id": job_id, "status": "uploaded"}

@app.post("/api/jobs/{job_id}/process")
def process_job(job_id: str, settings: ProcessSettings, background: BackgroundTasks):
    with lock:
        job = jobs.get(job_id)
        if not job: raise HTTPException(404, "Job not found")
        if job["status"] not in {"uploaded"}: raise HTTPException(409, "Job already started")
        job["status"] = "processing"
        job["message"] = "Processing started…"
    background.add_task(run_processing, job_id, settings)
    return {"id": job_id, "status": "processing"}

@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job: raise HTTPException(404, "Job not found")
        return {k: job[k] for k in ("id", "status", "progress", "message")}

@app.get("/api/jobs/{job_id}/download")
def download_job(job_id: str):
    with lock:
        job = jobs.get(job_id)
        if not job: raise HTTPException(404, "Job not found")
        if job["status"] != "completed": raise HTTPException(409, "Output is not ready")
        output = Path(job["output"])
    if not output.is_file(): raise HTTPException(404, "Output file missing")
    return FileResponse(output, media_type="video/mp4", filename="RNYFTBL_enhanced.mp4")

app.mount("/", StaticFiles(directory="/app/frontend", html=True), name="frontend")
