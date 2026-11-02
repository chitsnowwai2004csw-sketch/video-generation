# Video Creator Docker package

This package runs the shared video tools on the server. End users only open Open WebUI in a browser. Python, Node.js, Chromium, FFmpeg, HyperFrames, Remotion, Kokoro, and its model/voice files are installed during the worker image build. Ordinary requests do not install packages or download models/browsers.

Requirements: Docker Engine with Compose, or Docker Desktop in Linux-container mode. This first image targets Linux/amd64. The first build needs internet access and several GB of free disk space. After building, local template rendering needs no model-provider account. An optional external text planner is configured separately.

The included release archive `video_creator_docker_images.tar.gz` can be loaded instead of building. It contains the worker, customized Open WebUI, and Nginx images, without user data or secrets:

```powershell
docker load -i video_creator_docker_images.tar.gz
docker compose up -d --no-build
```

Then create your administrator account and run the configuration command below. Keep the Compose/source package alongside the images: the gateway configuration is mounted from `docker/`. See `DOCKER_TEST_RESULTS.md` for the completed container tests.

Choose either a new complete stack or an add-on for your existing Open WebUI.

## Option A: new complete stack

From the extracted package folder:

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

Open http://localhost:3000 and create your first Open WebUI account. The first account becomes administrator. Then run:

```powershell
docker compose --profile tools run --rm configure
```

Enter that administrator email and password when prompted. The command imports/enables the Pipe, connects the worker, saves its API key, turns off RAG File Context for this model, grants authenticated users read access, and verifies `/health`. The password is not saved by the command. The worker key is never printed. To restrict the model to the administrator initially, append `--private`.

Select **Video Creator** in Open WebUI. Send `/health`. Upload source files and request a video. Use `/status JOB_ID`, `/revise JOB_ID changes`, and `/cancel JOB_ID` as needed.

No manual API URL/key copying is required for this stack. Keys are generated once in the `video-secrets` Docker volume and preserved across container restarts and image rebuilds.

## Option B: connect your existing Docker Open WebUI

This option keeps your existing Open WebUI container and database. It adds a worker and a new gateway URL. The authenticated configuration command adds or updates only the `video_creator` Function and its model configuration. It makes that model available to all authenticated users unless you append `--private`.

Find your Open WebUI container's Docker network and internal container name. A Compose deployment often has a network such as `open-webui_default`. Inspect it using Docker Desktop, or:

```powershell
docker inspect YOUR_OPENWEBUI_CONTAINER --format '{{json .NetworkSettings.Networks}}'
```

Copy `.env.example` to `.env`, then add/edit:

```dotenv
OPENWEBUI_DOCKER_NETWORK=YOUR_EXISTING_NETWORK
OPENWEBUI_UPSTREAM=YOUR_OPENWEBUI_CONTAINER:8080
WEBUI_PORT=3001
VIDEO_PUBLIC_URL=http://localhost:3001/video
```

Use the container's internal port in `OPENWEBUI_UPSTREAM`. Choose an unused host port for `WEBUI_PORT`. The network must be a user-defined Docker network that supports container DNS. Then run:

```powershell
docker compose -f compose.existing.yaml up -d --build
docker compose -f compose.existing.yaml --profile tools run --rm configure
```

Sign in with your existing administrator credentials when prompted. Open http://localhost:3001 to use your existing Open WebUI through the new video gateway. Downloads now use the same browser-facing gateway. This package does not expose the worker's management API on a host port.

## Sharing with your team

The default gateway binds only to `127.0.0.1` for a local setup. Other computers cannot reach that address. For a private LAN deployment, configure `BIND_ADDRESS` and `VIDEO_PUBLIC_URL` to addresses your users can reach, and apply your normal firewall/access policy. For internet use, put the gateway behind your HTTPS reverse proxy and set `VIDEO_PUBLIC_URL=https://YOUR_HOST/video`. Keep Open WebUI authentication enabled.

Changing `.env` requires recreating containers:

```powershell
docker compose up -d
docker compose --profile tools run --rm configure
```

Run the configure command again after changing the public URL so the Pipe's saved Valves are updated. For Option B, include `-f compose.existing.yaml` in both commands. Add-on mode requires your existing Open WebUI to support the Function/model APIs used by the installer. The fresh stack pins Open WebUI 0.12.4 slim; custom deployments may differ.

## Storage and operation

- `webui-data`: accounts, chats, uploaded originals, and Function settings (new-stack mode only).
- `video-data`: worker SQLite jobs, ingested assets, projects, and outputs.
- `video-secrets`: persistent worker and Open WebUI secrets. Back this up with the databases. Do not share it with ordinary users.
- Tool packages, Chromium, and Kokoro models are baked into the worker image, not downloaded into each user's browser.

Stop without deleting data:

```powershell
docker compose down
```

Start again:

```powershell
docker compose up -d
```

Do not add `--volumes`/`-v` to `down` when you want to keep accounts, projects, or keys. Use your normal Docker-volume backup process for all three volumes. Keep one worker process per worker data volume; horizontal scaling is not implemented.

Check status and logs:

```powershell
docker compose ps
docker compose logs --tail 100 video-worker
```

## Optional text planner

Set `PLANNER_URL`, `PLANNER_MODEL`, and (when required) `PLANNER_API_KEY` in `.env`. The endpoint must support `/chat/completions` and JSON-object output. No external planner is called by default. This adapter sends source filenames and extracted document text; it does not send image pixels or video transcripts. Brag-style planning uses an adapted preset, not the complete interactive Brag skill.

## Current limits

The worker retains the first package's limits: simple source-based templates, one render at a time, scene-level captions, no OCR or video transcription, and no automatic storage cleanup. Default Pipe limits are 12 sources, 100 MiB per file, 300 MiB total. Output links expire after an hour; `/status JOB_ID` creates fresh links. Cancelling a job prevents publication but may let an active rendering subprocess finish.

Open WebUI slim does not contain a general document extraction stack. The worker reads supported documents itself, but browser upload behavior can depend on Open WebUI's model capabilities and extraction settings. Original uploads through `process=false` are the tested integration path; configure a supported external extractor or use standard Open WebUI if your browser document flow needs it.

## Save/load the built images for another server

```powershell
docker save -o video-creator-images.tar video-creator-worker:1.0.0 video-creator-webui:0.12.4 nginx:1.28-alpine
```

Copy the image archive and this source/Compose package to the other server, then:

```powershell
docker load -i video-creator-images.tar
docker compose up -d --no-build
```

Create the administrator account and run the configure command there. Secrets and databases are intentionally not embedded in exported images.
