"""Start isolated, localhost-only Open WebUI and worker test instances."""
import json
import importlib.util
import os
import secrets
import socket
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parent
state = root / ".local-test"
state.mkdir(exist_ok=True)
(state / "webui-data").mkdir(exist_ok=True)
secrets_path = state / "secrets.json"
if secrets_path.is_file():
    config = json.loads(secrets_path.read_text())
else:
    config = {"worker_key": secrets.token_urlsafe(32), "webui_key": secrets.token_urlsafe(32), "password": secrets.token_urlsafe(24)}
    secrets_path.write_text(json.dumps(config))
environment = {
    **os.environ,
    "VIDEO_API_KEY": config["worker_key"],
    "VIDEO_DATA_DIR": str(state / "worker-data"),
    "DATA_DIR": str(state / "webui-data"),
    "STATIC_DIR": str(state / "webui-static"),
    "FRONTEND_BUILD_DIR": str(Path(importlib.util.find_spec("open_webui").origin).parent / "frontend"),
    "WEBUI_SECRET_KEY": config["webui_key"],
    "USE_SLIM_DOCKER": "true",
    "OFFLINE_MODE": "true",
    "ENABLE_VERSION_UPDATE_CHECK": "false",
    "ENABLE_PIP_INSTALL_FRONTMATTER_REQUIREMENTS": "false",
    "ENABLE_SIGNUP": "true",
    "DEFAULT_USER_ROLE": "user",
    "ENABLE_OLLAMA_API": "false",
    "ENABLE_OPENAI_API": "false",
    "ANONYMIZED_TELEMETRY": "false",
}
pids_path = state / "pids.json"
pids = json.loads(pids_path.read_text()) if pids_path.is_file() else {}
for name, target, port in [("worker", "video_worker:app", "8001"), ("openwebui", "open_webui.main:app", "8080")]:
    with socket.socket() as probe:
        if probe.connect_ex(("127.0.0.1", int(port))) == 0:
            print(f"Reusing local {name} on port {port}")
            continue
    with (state / (name + ".log")).open("w", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", target, "--host", "127.0.0.1", "--port", port],
                                   cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    pids[name] = process.pid
pids_path.write_text(json.dumps(pids))
print("Started isolated local test services. URLs: http://127.0.0.1:8080 and http://127.0.0.1:8001")
