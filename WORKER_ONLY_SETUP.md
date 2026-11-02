# Worker only: existing Open WebUI and Nginx Proxy Manager

This deployment adds one continuously running video worker. It does not create
Open WebUI or a proxy. An initializer runs once and exits; a configuration helper
runs only when you request it. Tools and Kokoro models are included in the worker
image and reused by every user. Initial builds need Internet access.

## 1. Shared Docker network

Use the actual container names shown by `docker ps`. The names `open-webui` and
`nginx-proxy-manager` below are examples. These instructions assume all three
services run on the same Docker engine, using Linux containers on amd64.

```powershell
docker network create video-tools
docker network connect video-tools open-webui
docker network connect video-tools nginx-proxy-manager
```

If the network already exists, skip its creation. If containers are already
connected, skip those connections. Add this external network to the original
Open WebUI and NPM Compose files too, so recreated containers retain access.

## 2. Environment

Work in the package directory. Copy `.env.worker.example` to `.env.worker` and
edit its three connection settings. Replace `open-webui` with your actual existing
Open WebUI container name, and `video.example.com` with your own DNS hostname.

```powershell
Copy-Item .env.worker.example .env.worker
```

The Open WebUI URL uses its internal container port, usually 8080. The public
video URL must be reachable by users' browsers, with no trailing `/video` here.

## 3. Start the worker

If you have the provided image archive, load it first:

```powershell
docker load -i video_creator_docker_images.tar.gz
docker compose --env-file .env.worker -f compose.worker.yaml up -d --no-build
```

The archive also contains the older demo UI/proxy images. Loading images does
not create containers; this Compose file starts only the worker and initializer.
Alternatively, build just the worker first:

```powershell
docker compose --env-file .env.worker -f compose.worker.yaml build video-worker
docker compose --env-file .env.worker -f compose.worker.yaml up -d --no-build
```

## 4. Existing Nginx Proxy Manager

Create a separate Proxy Host for `video.example.com`:

- Scheme: `http`
- Forward hostname: `video-creator-worker-only`
- Forward port: `8001`
- Access List: Publicly Accessible (downloads use expiring signed URLs)
- SSL: issue/select a certificate for this hostname; enable Force SSL.

Point DNS at your existing NPM server. In this Proxy Host's Advanced configuration,
allow only download paths through the public hostname:

```nginx
if ($uri !~ "^/downloads/") {
    return 404;
}
proxy_read_timeout 900s;
```

Do not apply this restriction to your Open WebUI hostname. Keep the existing
Open WebUI proxy host unchanged. The worker has no published host port; Open
WebUI submits jobs directly over Docker networking. NPM exposes signed downloads.

## 5. Connect your existing Open WebUI

```powershell
docker compose --env-file .env.worker -f compose.worker.yaml --profile tools run --rm configure
```

Enter an administrator email and password from your EXISTING Open WebUI.
The helper imports/updates the `video_creator` Function and model, saves the
generated worker secret automatically, grants model access to authenticated users,
and checks worker readiness. It does not save the administrator password.
An existing Function/model with that ID will be updated. SSO-only accounts need
manual Function import and Valve configuration instead.

For manual configuration, import `video_creator_pipe.py` under Admin Settings >
Functions, enable it, and set its Valves:

| Valve | Value |
|---|---|
| VIDEO_API_URL | `http://video-creator-worker-only:8001` |
| OPENWEBUI_INTERNAL_URL | Your `.env.worker` Open WebUI URL |
| PUBLIC_OUTPUT_URL | `https://video.example.com` |
| VIDEO_API_KEY | Secret printed by the command below |

```powershell
docker compose --env-file .env.worker -f compose.worker.yaml exec video-worker cat /run/video-secrets/video-api-key
```

Keep that secret in administrator Valves; users do not need it.

## 6. Verify

```powershell
docker compose --env-file .env.worker -f compose.worker.yaml ps -a
docker compose --env-file .env.worker -f compose.worker.yaml logs --tail 50 video-worker
```

The worker should be healthy and init should have exited with code 0. In your
existing Open WebUI, select Video Creator, send `/health`, then upload an image
and request a short video. Check playback/download from a second user's browser.
The public hostname root should return 404. A generated signed download should
work; an unsigned `/downloads/` request should fail.

Retain the `video-data` and `video-secrets` volumes across updates. Do not use
`down -v` unless intentionally deleting jobs, assets, outputs and credentials.
One worker renders one job at a time; long jobs return an ID for `/status ID`.
This is a template-based source montage, not automatic visual understanding of
arbitrary documents/videos or the full interactive Brag workflow.

The separate local full-stack demo is not modified by these instructions. Stop
its containers only after confirming your existing Open WebUI is the intended
deployment. Do not delete its volumes while migrating.
