# RNYFTBL UPSCALLER AI — backend-connected prototype

## What works in this increment
- Mobile-friendly upload and local preview UI.
- FastAPI upload endpoint with extension allowlist and configurable upload-size limit.
- Server-side FFmpeg processing job.
- Job status/progress polling and MP4 download.
- Resolution scaling, denoise, sharpening and saturation controls.

**Important:** the current processing is conventional FFmpeg filtering, not AI inference. The app does not yet include an AI upscaling model, frame interpolation, authentication, cloud object storage, or a durable distributed job queue. Do not expose this prototype publicly as-is.

## Run locally
Requirements: Docker Desktop (recommended), or Python 3.11+ and FFmpeg/ffprobe installed.

```bash
docker build -t rnyftbl-upscaller .
docker run --rm -p 8000:8000 -e MAX_UPLOAD_BYTES=524288000 rnyftbl-upscaller
```

Open http://localhost:8000 on the same device/network. For a phone, use the computer's LAN IP instead of localhost while both devices are on the same Wi-Fi.

Without Docker:
```bash
pip install -r requirements.txt
# Install ffmpeg and ffprobe on your OS, then:
DATA_DIR=./jobdata uvicorn backend.main:app --host 0.0.0.0 --port 8000
```
Serve `frontend/index.html` from the same FastAPI origin; do not open it as a `file://` page because API calls use relative URLs.

## Recommended production architecture
1. Mobile browser frontend (current HTML; later migrate to React/Vite or Next.js PWA).
2. API gateway: HTTPS, user authentication, per-user quotas, MIME/content probing, upload size and duration limits.
3. Object storage: signed multipart uploads to S3-compatible storage; avoid holding large videos in API memory.
4. Durable queue: Redis + Celery/RQ or a managed queue. Store job state in PostgreSQL; do not rely on in-memory `jobs` for production.
5. GPU worker: containerized NVIDIA GPU worker running FFmpeg decode/encode plus a licensed, pinned AI model such as Real-ESRGAN for spatial upscaling. Add a separate frame-interpolation model only if needed. Confirm model license, GPU VRAM, throughput and commercial-use rights before deployment.
6. Progress: worker writes frame/step progress to the database; frontend polls or uses Server-Sent Events/WebSockets.
7. Export: encode MP4 (H.264 for compatibility; optionally HEVC), store output in object storage, return short-lived signed download URL.
8. Security/operations: HTTPS, auth, signed URLs, rate limits, malware scanning, isolated workers, automatic file expiry, storage quotas, observability and deletion controls.

## Next implementation step
Replace `run_processing()`'s FFmpeg filter path with a GPU model adapter that:
- downloads input to a per-job worker directory;
- invokes the chosen model with fixed, validated arguments;
- reports progress and cancellation;
- re-encodes audio/video and validates the output with ffprobe;
- records model/version and processing settings for reproducibility.

The current in-process background task and local disk storage are for local testing only.
