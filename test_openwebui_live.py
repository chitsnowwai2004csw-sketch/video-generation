"""Exercise the real local Open WebUI HTTP API and shared rendering worker.

Run setup_shared_tools.ps1, install server dependencies, start_local_test.py,
then run this file. All accounts/data are isolated under .local-test.
"""
import io
import json
import os
import re
import time
import zipfile
from pathlib import Path

import httpx
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".local-test"
WEBUI = "http://127.0.0.1:8080"
WORKER = "http://127.0.0.1:8001"
SECRETS = json.loads((STATE / "secrets.json").read_text())
client = httpx.Client(timeout=180, trust_env=False)
report = {"checks": []}
tools_config = json.loads((Path(os.environ["LOCALAPPDATA"]) / "VideoCreator/tools/tools.json").read_text(encoding="utf-8-sig"))
shared_root = Path(tools_config["tools_root"])
runtime_files = [Path(tools_config[k]) for k in ("hyperframes", "kokoro_model", "kokoro_voices")]
runtime_files.extend(shared_root / "node_modules" / package / "package.json" for package in ("hyperframes", "remotion", "@remotion/renderer"))
runtime_files.append(Path(json.loads((shared_root / "remotion-browser.json").read_text())["path"]))
runtime_before = {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in runtime_files}


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    report["checks"].append(name)
    print("PASS " + name, flush=True)


def request(method, path, token=None, **kwargs):
    response = client.request(method, WEBUI + path, headers={"Authorization": "Bearer " + token} if token else {}, **kwargs)
    if response.status_code >= 400:
        raise RuntimeError(f"{method} {path}: HTTP {response.status_code}: {response.text[:400]}")
    return response.json()


def completion(token, text, files=None):
    body = {"model": "video_creator_test", "messages": [{"role": "user", "content": text}], "stream": False}
    if files:
        body["files"] = files
    value = request("POST", "/api/chat/completions", token, json=body)
    return value["choices"][0]["message"]["content"]


print("Waiting for local Open WebUI...", flush=True)
for attempt in range(180):
    try:
        if client.get(WEBUI + "/health", timeout=2).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(1)
else:
    raise RuntimeError("Open WebUI did not start; see .local-test/openwebui.log")

email = "video-admin@example.com"
signin = client.post(WEBUI + "/api/v1/auths/signin", json={"email": email, "password": SECRETS["password"]})
if signin.status_code == 200:
    admin = signin.json()["token"]
else:
    admin = request("POST", "/api/v1/auths/signup", json={"name": "Local Video Test Admin", "email": email, "password": SECRETS["password"]})["token"]
check("Real Open WebUI administrator session", bool(admin))
source = (ROOT / "video_creator_pipe.py").read_text(encoding="utf-8")
existing = client.get(WEBUI + "/api/v1/functions/id/video_creator_test", headers={"Authorization": "Bearer " + admin})
form = {"id": "video_creator_test", "name": "Video Creator Test", "content": source, "meta": {"description": "Shared tools integration test"}}
if existing.status_code == 200:
    function = request("POST", "/api/v1/functions/id/video_creator_test/update", admin, json=form)
else:
    function = request("POST", "/api/v1/functions/create", admin, json=form)
if not function["is_active"]:
    request("POST", "/api/v1/functions/id/video_creator_test/toggle", admin)
valves = {"VIDEO_API_URL": WORKER, "VIDEO_API_KEY": SECRETS["worker_key"], "OPENWEBUI_INTERNAL_URL": WEBUI,
          "PUBLIC_OUTPUT_URL": WORKER, "WAIT_SECONDS": 0, "WIDTH": 1280, "HEIGHT": 720, "FPS": 24, "NARRATION": True}
request("POST", "/api/v1/functions/id/video_creator_test/valves/update", admin, json=valves)
# Current Open WebUI hides ungranted base models from regular users. Publish
# this one test model explicitly; disable RAG because the worker needs originals.
model_form = {"id": "video_creator_test", "name": "Video Creator Test", "base_model_id": None,
              "params": {}, "meta": {"capabilities": {"file_context": False, "vision": True}},
              "access_grants": [{"principal_type": "user", "principal_id": "*", "permission": "read"}]}
model_exists = client.get(WEBUI + "/api/v1/models/model?id=video_creator_test", headers={"Authorization": "Bearer " + admin})
request("POST", "/api/v1/models/model/update" if model_exists.status_code == 200 else "/api/v1/models/create", admin, json=model_form)
check("Pipe imported and enabled without dependency installation", "requirements:" not in source.split('"""', 2)[1])
check("Pipe help through real chat completion endpoint", "/status" in completion(admin, "/help"))
health = completion(admin, "/health")
check("Shared tools available through Open WebUI", "**ready**" in health and "remotion: ready" in health)

users = []
for number in (1, 2):
    email = f"video-user-{number}@example.com"
    result = client.post(WEBUI + "/api/v1/auths/signin", json={"email": email, "password": SECRETS["password"]})
    if result.status_code != 200:
        request("POST", "/api/v1/auths/add", admin, json={"name": f"Video User {number}", "email": email, "password": SECRETS["password"], "role": "user"})
        result = client.post(WEBUI + "/api/v1/auths/signin", json={"email": email, "password": SECRETS["password"]})
    result.raise_for_status()
    users.append(result.json())
for number, user in enumerate(users, 1):
    models = request("GET", "/api/models", user["token"])
    check(f"User {number} can access the shared Pipe", any(m["id"] == "video_creator_test" for m in models["data"]))
    check(f"User {number} needs no local tools", "Tools are installed once" in completion(user["token"], "/health"))

image = Image.new("RGB", (960, 540), "#102033")
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((80, 80, 880, 460), radius=30, fill="#1e4564", outline="#56dfbf", width=4)
draw.text((150, 220), "Shared video tools", fill="white", font_size=48)
draw.text((150, 300), "One server. Every user.", fill="#56dfbf", font_size=32)
image_bytes = io.BytesIO()
image.save(image_bytes, format="PNG")
uploaded = request("POST", "/api/v1/files/?process=false", users[0]["token"], files={"file": ("shared-tools.png", image_bytes.getvalue(), "image/png")})
attachment = {"type": "file", "id": uploaded["id"], "name": "shared-tools.png", "file": uploaded, "context": "full"}
check("Original image uploaded to real Open WebUI", bool(uploaded["id"]))

job_ids = []
for renderer in ("hyperframes", "remotion"):
    valves["RENDERER"] = renderer
    request("POST", "/api/v1/functions/id/video_creator_test/valves/update", admin, json=valves)
    response = completion(users[0]["token"], "Create a short source slideshow with narration.", [attachment])
    match = re.search(r"Video job: `(job_[a-z0-9]+)`", response)
    if not match:
        raise RuntimeError("Pipe did not create a job: " + response[:400])
    job_id = match.group(1)
    job_ids.append(job_id)
    print(f"Rendering {renderer}: {job_id}", flush=True)
    for attempt in range(240):
        response = completion(users[0]["token"], "/status " + job_id)
        if "**completed**" in response:
            break
        if "**failed**" in response:
            raise RuntimeError(f"{renderer} render failed. See .local-test/worker-data/{job_id}/render.log")
        time.sleep(2)
    else:
        raise RuntimeError("Render timed out: " + job_id)
    check(f"{renderer} rendered through Open WebUI with Kokoro narration", "**completed**" in response)
    url = re.search(r"\[Video\]\(([^)]+)\)", response).group(1)
    output = client.get(url)
    check(f"{renderer} output downloads in the browser", output.status_code == 200 and len(output.content) > 1000)
    (STATE / (renderer + "-smoke.mp4")).write_bytes(output.content)
    report[renderer] = {"job_id": job_id, "bytes": len(output.content), "output": str(STATE / (renderer + "-smoke.mp4"))}
    forbidden = completion(users[1]["token"], "/status " + job_id)
    check(f"User 2 cannot read User 1's {renderer} job", "HTTP 404" in forbidden)

report["openwebui_version"] = request("GET", "/api/version").get("version")
runtime_after = {str(path): (path.stat().st_size, path.stat().st_mtime_ns) for path in runtime_files}
check("Both renderers reused unchanged installed packages, Kokoro models, and Chrome", runtime_before == runtime_after)
for renderer in ("hyperframes", "remotion"):
    log = (STATE / "worker-data" / report[renderer]["job_id"] / "render.log").read_text(encoding="utf-8", errors="replace").lower()
    check(f"No download or package installer in {renderer} job log", not any(word in log for word in ("downloading", "npm install", "pip install")))
report["runtime_assets_unchanged"] = True
(STATE / "live-test-report.json").write_text(json.dumps(report, indent=2))
valves["RENDERER"] = "hyperframes"
request("POST", "/api/v1/functions/id/video_creator_test/valves/update", admin, json=valves)
print("Live integration checks passed. Report: .local-test/live-test-report.json", flush=True)
