# Video Creator Pipe for Open WebUI

`video_creator_pipe.py` is the importable Open WebUI Function. It connects chat and uploads to the included `video_worker.py` service. HyperFrames, Remotion, Kokoro, and an adapted Brag planning preset live on the shared server. Users need only Open WebUI in a browser.

## Set up the shared Windows server once

Prerequisites: Node.js 22+, Python 3.12, FFmpeg and FFprobe available on PATH.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r worker-requirements.txt
powershell -NoProfile -ExecutionPolicy Bypass -File .\setup_shared_tools.ps1
```

Setup pins the Node packages under `%LOCALAPPDATA%\VideoCreator\tools`, installs Kokoro's Python runtime if missing, and preloads model/voice/browser caches. Running setup again reuses installed Node packages when the manifest matches. It may regenerate the short voice setup sample; ordinary video requests never run setup.

Start the worker without installing anything:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\start_video_worker.ps1
```

The start script creates `server.local.json` with a persistent random API key. Copy that key into the Pipe's `VIDEO_API_KEY` Valve. Keep the config private and excluded from source control. Start the worker as one process; multiple worker processes sharing the same SQLite directory are not supported. The default listener is localhost only. For Open WebUI in Docker or another host, place the worker behind a private authenticated proxy or adjust its listener/firewall deliberately.

The included worker uses SQLite jobs, local source storage, per-user ownership checks, and one-hour signed downloads. Keep its data and tool caches persistent. Establish retention/cleanup and process supervision before a production rollout.

### What this first worker does

Both renderers support source images, videos, audio, text cards, captions, and local Kokoro narration. Documents supported: PDF (text from the first five pages), DOCX, PPTX, TXT, MD. Image/video/audio formats are explicitly checked by `/assets`.

Without a planner, it creates a simple source montage from filenames and document excerpts. It does not interpret arbitrary visual instructions, summarize video speech, perform OCR, or reconstruct demonstrated screens. Revisions update the brief but cannot intelligently change scene content in this template mode. Subtitles use scene-level timing. Original video audio is muted; standalone audio is used when narration is disabled. Source media can be truncated to scene duration.

To enable scripted explainers and Brag-style text planning, set these server environment variables before starting the worker:

```powershell
$env:PLANNER_URL = 'http://your-model-server:port/v1'
$env:PLANNER_MODEL = 'your-model-name'
$env:PLANNER_API_KEY = 'your-provider-key-if-required'
```

The optional planner endpoint must implement `/chat/completions` and JSON-object responses. It receives the brief, filenames, and extracted document text. This first adapter does not send image pixels or video transcripts to that planner. It edits scene titles, captions, and narration; source assets and scene count stay fixed. The Brag preset is adapted planning guidance in `server-tools/brag-preset.md`, not the complete interactive Brag skill workflow. No external planner is called by default.

## Import

1. Sign in as an Open WebUI administrator.
2. Open the Functions management screen (normally Admin Panel → Functions).
3. Create a Function and paste the complete contents of `video_creator_pipe.py`, or use the file import option if your version provides one.
4. Save and enable the Function. Set its display name to **Video Creator**.
5. Open its Valves and configure the values below.
6. Select **Video Creator** in a chat. Send `/help` to verify the Function loaded. This does not contact the worker.

### Make it available to every intended user

Enabling a Function alone may leave its model hidden from regular users. In Workspace → Models, configure the Pipe's model and grant read access to all intended users or groups. The local integration test explicitly creates a public-read model grant; it does not disable access checks globally. Set the model's **File Context** capability off, since this worker consumes original uploads rather than Open WebUI RAG snippets. Keep vision/file attachment capability on. Users can select renderer, preset, voice, narration, and language through their own User Valves when their permissions allow it.

For document uploads, a slim Open WebUI deployment may need an external extractor even though the video worker has its own document reader. The integration tests upload originals using `process=false` through Open WebUI's API. Standard Open WebUI or appropriate upload/extraction configuration is needed to validate the same document flow through your browser UI.

Current integration reference: https://docs.openwebui.com/features/extensibility/plugin/functions/pipe/

## Required settings

### Install once; share with all users

The Pipe has no installer and uses `httpx` and `pydantic`, which are already dependencies of Open WebUI. It has no `requirements:` frontmatter, so importing or loading it does not ask Open WebUI to run pip. Users need only a browser and access to this enabled Function/model.

Administrators install the rendering tools once in the shared worker. Use a pinned local Node.js project for HyperFrames and Remotion, a Python environment for Kokoro, and persistent model/browser/font caches. Invoke installed executables directly in job handlers; never run `npx`, `npm install`, `pip install`, skill updates, or model downloads from a job. Preload the browser, fonts, Kokoro model and voice files during server setup. Check them at startup and reject missing dependencies with an administrator-facing error.

Keep these directories in persistent storage when using containers. Updating or replacing a worker must reuse caches or bake them into its image. Brag planning instructions are installed on the worker, not on each user's computer. Configure Function/model access for the intended Open WebUI user groups. Worker ownership checks must still separate each user's sources and jobs.

Send `/health` to check the worker's shared tool readiness without submitting a video.

| Valve | Example | Meaning |
| --- | --- | --- |
| `VIDEO_API_URL` | `http://video-worker:8001` | Worker URL reachable from Open WebUI's backend |
| `VIDEO_API_KEY` | Your worker's secret | Bearer token accepted by the worker |
| `OPENWEBUI_INTERNAL_URL` | `http://127.0.0.1:8080` | Open WebUI's own backend URL, used for authenticated source downloads |
| `PUBLIC_OUTPUT_URL` | `https://videos.example.com` | Browser-reachable base for relative output links |

URLs must have no embedded credentials, query strings, or fragments. Set `PUBLIC_OUTPUT_URL` when the worker's internal hostname is inaccessible to the browser. The service must serve downloads through authenticated links or expiring signed links; the Pipe does not proxy output downloads.

When Open WebUI runs in Docker and the worker runs on the Windows host, use `http://host.docker.internal:8001` for `VIDEO_API_URL`. Inside the Open WebUI container, `localhost` refers to that container. For separate containers on the same Docker network, use the worker's service name instead. With a reverse proxy under a URL prefix, include that prefix in `OPENWEBUI_INTERNAL_URL`.

Use `RENDERER=hyperframes` initially. Set `PRESET=explainer`, `slideshow`, or `brag`. The Brag preset tells the worker to use the promo planning workflow; it is not a remote `/brag` skill invocation. Switch `RENDERER` to `remotion` only when the worker implements that adapter. The worker must reject unavailable renderers, unsupported voices, and unsupported narration languages rather than silently substituting them.

Other settings cover dimensions, FPS, Kokoro voice, upload limits, request timeout, and polling. Defaults: 1920×1080, 30 FPS, English narration, `af_heart`, 12 files, 100 MiB per file, 300 MiB total. Narration can be disabled. Verify language support in the installed Kokoro model before selecting a language.

## Use

Attach original images, videos, audio, or documents. Example prompt:

> Create a 60-second explainer from these files. Keep the source images, use clear captions, and explain the main steps.

The worker interprets creative instructions and target duration; the Pipe passes them unchanged. Renderer, preset, dimensions, and voice come from administrator Valves. The Pipe sends the latest user prompt and attached sources, not full chat history. Use explicit revision commands to change existing jobs:

```text
/status JOB_ID
/revise JOB_ID Shorten scene two and make the ending clearer.
/cancel JOB_ID
/help
```

After 30 seconds of polling, the default Pipe returns the job ID. Rendering continues in the worker; send `/status JOB_ID` to obtain the latest state and links. Closing the browser does not cancel a submitted job. If the connection closes before the job ID appears, use the worker's job list/logs to recover it. There is no automatic completion push after a Pipe request ends.

Knowledge collections are not accepted as original media. The Pipe handles individual file IDs in `__files__`, metadata/body file lists, base64 inline images, and Open WebUI `/api/v1/files/{id}/content` references. A public gateway hostname can differ from the internal server hostname: the Pipe resolves the file ID and downloads only from the configured internal API with the caller's credentials. Other external image URLs must be uploaded as files. Upload serialization varies by Open WebUI version; confirm a small image, PDF, and video on your installed version. File downloads use the current request's Authorization/Cookie headers. No administrator file API key is used. Remote credentials are never sent to the worker.

## Worker API contract

The included worker implements this integration contract. These are not built-in HyperFrames or Remotion endpoints. Every management endpoint authenticates `Authorization: Bearer VIDEO_API_KEY`. The worker receives `X-OpenWebUI-User-ID` from the trusted Pipe and enforces ownership. Expose the worker only through this trusted integration; clients must not be allowed to impersonate users by setting that header. Download endpoints instead use short-lived signed URLs, which must be treated as private bearer links.

### GET /health

Check local installations and persistent model files without installing or downloading anything. Return tool readiness:

```json
{
  "ready": true,
  "tools": {
    "hyperframes": {"ready": true, "version": "0.8.185"},
    "remotion": {"ready": true},
    "kokoro": {"ready": true},
    "ffmpeg": {"ready": true},
    "brag": {"ready": true}
  }
}
```

Only report a tool ready when its actual runtime and required assets are present. Return `ready: false` if a required component is unavailable.

### POST /assets

Accept multipart form-data with field `file`. Persist the original file, assign it to the caller, and return:

```json
{"id": "asset_123"}
```

Enforce content/size limits in the worker too. Remove orphaned uploads after a retention period; failed submissions can leave assets without a job.

### POST /jobs

Accept JSON:

```json
{
  "instructions": "Create a 60-second explainer.",
  "chat_id": "chat_123",
  "message_id": "message_123",
  "assets": [
    {"id": "asset_123", "name": "source.pdf", "content_type": "application/pdf"}
  ],
  "settings": {
    "renderer": "hyperframes",
    "preset": "explainer",
    "width": 1920,
    "height": 1080,
    "fps": 30,
    "narration": {
      "enabled": true,
      "provider": "kokoro",
      "language": "en",
      "voice": "af_heart"
    }
  }
}
```

Persist and enqueue before responding with HTTP 200/201/202 and a JSON object:

```json
{"id": "job_123", "status": "queued", "stage": "queued"}
```

IDs must match `[A-Za-z0-9_-]{1,128}`. Valid states: `queued`, `running`, `completed`, `failed`, `cancelled`.

Honor `Idempotency-Key` for job creation and revisions. Scope keys to the authenticated user and operation. Retries with an existing key must return the existing job, including when the retry references newly uploaded asset IDs. The key uses Open WebUI's message ID when available. Without a message ID, it hashes the payload; this fallback cannot fully prevent duplicate jobs when a retry reuploads assets. The Pipe never automatically retries POST requests.

### GET /jobs/{id}

Return the job object. Completed example:

```json
{
  "id": "job_123",
  "status": "completed",
  "stage": "done",
  "outputs": {
    "video": "/downloads/job_123/video.mp4?token=EXPIRING_TOKEN",
    "thumbnail": "/downloads/job_123/thumbnail.jpg?token=EXPIRING_TOKEN",
    "subtitles": "/downloads/job_123/subtitles.srt?token=EXPIRING_TOKEN",
    "project": "/downloads/job_123/project.zip?token=EXPIRING_TOKEN"
  }
}
```

Outputs are optional HTTP(S) URLs or paths beginning with one `/`. Absolute URLs must be reachable by the user's browser. Relative paths are prefixed by `PUBLIC_OUTPUT_URL`, falling back to `VIDEO_API_URL`. Failed jobs should keep detailed errors in worker logs; the Pipe returns the job ID without exposing raw backend errors.

### POST /jobs/{id}/revisions

Accept `{"instructions": "Shorten scene two.", "chat_id": "chat_123"}`. Create a new durable job that references the original project and assets. Return the new job object with its new ID. Do not overwrite the original.

### POST /jobs/{id}/cancel

Accept `{}`. Request cancellation and return the job object. Stop work safely and eventually set `cancelled`; already completed jobs can remain `completed`.

The included worker prevents further job publication when cancelled. A subprocess already rendering can finish before the worker moves on; immediate process-tree termination is not implemented.

## What the worker needs

1. Durable job storage and a worker loop that survives HTTP disconnects.
2. Source extraction: document text/page images, video keyframes/transcription, image analysis/OCR where needed.
3. An LLM configured to produce a validated scene plan grounded in source assets.
4. Brag planning instructions for the promo preset.
5. Kokoro narration per scene; measured audio durations determine scene timing.
6. HyperFrames CLI or Remotion Node.js rendering adapters, pinned to tested versions.
7. FFmpeg/probe checks, frame inspection, and protected output storage.

Start with a few tested templates, SQLite, local storage, and one render worker. Run generated rendering code in an isolated worker with restricted filesystem/network access. Uploaded documents are source material, not executable instructions.

## Validation

`test_video_creator_pipe.py` uses an in-process HTTP mock. Run:

```text
python -m pip install httpx pydantic
python -m unittest -v test_video_creator_pipe.py
```

These tests exercise the adapter contract, not actual rendering or a deployed Open WebUI session. Before deployment, test the real worker with one image, one document, and one video; then verify user isolation, reconnect/status, revision, cancellation, and browser downloads.

Real integration tests are also included. After installing an isolated Open WebUI 0.12.5 environment and the shared tools, `start_local_test.py` starts localhost-only services with separate test data and generated credentials under `.local-test`. Run `test_openwebui_live.py` for both renderer/narration paths, then `test_live_sources.py` for document/video inputs, ownership, revision/cancellation, idempotency, signed output access, and runtime cache reuse. These tests use the real Open WebUI HTTP API, not browser UI automation. The test environment disables plugin dependency installation. See `TEST_RESULTS.md` for the completed checks.
