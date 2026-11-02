"""Additional real Open WebUI source, ownership, and cache-reuse checks."""
import io
import json
import os
import re
import sqlite3
import time
import zipfile
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent
STATE = ROOT / ".local-test"
settings = json.loads((STATE / "secrets.json").read_text())
tools = json.loads((Path(os.environ["LOCALAPPDATA"]) / "VideoCreator/tools/tools.json").read_text(encoding="utf-8-sig"))
client = httpx.Client(base_url="http://127.0.0.1:8080", timeout=180, trust_env=False)
checks = []


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print("PASS " + name, flush=True)


def login(email):
    response = client.post("/api/v1/auths/signin", json={"email": email, "password": settings["password"]})
    response.raise_for_status()
    return response.json()


def call(user, text, files=None):
    payload = {"model": "video_creator_test", "messages": [{"role": "user", "content": text}], "stream": False}
    if files:
        payload["files"] = files
    response = client.post("/api/chat/completions", headers={"Authorization": "Bearer " + user["token"]}, json=payload)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]


def submit(user, filename, data, mime):
    response = client.post("/api/v1/files/?process=false", headers={"Authorization": "Bearer " + user["token"]}, files={"file": (filename, data, mime)})
    response.raise_for_status()
    record = response.json()
    output = call(user, "Create a short source slideshow.", [{"type": "file", "id": record["id"], "name": filename, "file": record, "context": "full"}])
    match = re.search(r"Video job: `(job_[a-z0-9]+)`", output)
    if not match:
        raise RuntimeError(output)
    return match.group(1), record["id"]


def wait(user, job):
    print("Waiting for " + job, flush=True)
    for _ in range(240):
        output = call(user, "/status " + job)
        if "**completed**" in output:
            return output
        if "**failed**" in output:
            raise RuntimeError("Job failed; see render.log for " + job)
        time.sleep(2)
    raise TimeoutError(job)


admin = login("video-admin@example.com")
user1, user2 = login("video-user-1@example.com"), login("video-user-2@example.com")
runtime_paths = [Path(tools[key]) for key in ("hyperframes", "kokoro_model", "kokoro_voices")]
runtime_paths += [Path(json.loads((Path(tools["tools_root"]) / "remotion-browser.json").read_text())["path"])]
before = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in runtime_paths}
valves_response = client.get("/api/v1/functions/id/video_creator_test/valves", headers={"Authorization": "Bearer " + admin["token"]})
valves_response.raise_for_status()
valves = valves_response.json()
valves.update({"RENDERER": "hyperframes", "NARRATION": False, "WAIT_SECONDS": 0})
response = client.post("/api/v1/functions/id/video_creator_test/valves/update", headers={"Authorization": "Bearer " + admin["token"]}, json=valves)
response.raise_for_status()

buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w") as archive:
    archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    archive.writestr("_rels/.rels", '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
    archive.writestr("word/document.xml", '<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Install video tools once on the shared server. Every user can upload sources in Open WebUI.</w:t></w:r></w:p></w:body></w:document>')
doc_job, doc_file = submit(user2, "shared-server.docx", buffer.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
doc_output = wait(user2, doc_job)
plan = json.loads((STATE / "worker-data" / doc_job / "plan.json").read_text())
check("Regular User 2 rendered an uploaded Word document through Open WebUI", "Install video tools once" in plan["scenes"][0]["caption"])

video_job, video_file = submit(user1, "source-video.mp4", (STATE / "hyperframes-smoke.mp4").read_bytes(), "video/mp4")
wait(user1, video_job)
video_plan = json.loads((STATE / "worker-data" / video_job / "plan.json").read_text())
check("Uploaded video source rendered through Open WebUI", video_plan["scenes"][0]["kind"] == "video")
denied = client.get(f"/api/v1/files/{video_file}/content", headers={"Authorization": "Bearer " + user2["token"]})
check("User 2 cannot download User 1's original Open WebUI upload", denied.status_code in (403, 404))

revision = call(user2, f"/revise {doc_job} Shorten the ending.")
revision_job = re.search(r"Video job: `(job_[a-z0-9]+)`", revision).group(1)
cancelled = call(user2, "/cancel " + revision_job)
check("Revision creates a separate job that can be cancelled", revision_job != doc_job and "**cancelled**" in cancelled)
check("Original completed job survives revision cancellation", "**completed**" in call(user2, "/status " + doc_job))

with sqlite3.connect(STATE / "worker-data/jobs.sqlite3") as connection:
    payload, key, owner = connection.execute("SELECT payload,idem,owner FROM jobs WHERE id=?", (doc_job,)).fetchone()
retry = httpx.post("http://127.0.0.1:8001/jobs", headers={"Authorization": "Bearer " + settings["worker_key"], "X-OpenWebUI-User-ID": owner, "Idempotency-Key": key.removeprefix("create:")}, json=json.loads(payload), trust_env=False)
check("Retrying a submitted request returns its existing durable job", retry.status_code == 202 and retry.json()["id"] == doc_job)
url = re.search(r"\[Video\]\(([^)]+)\)", doc_output).group(1)
unsigned = httpx.get(url.split("?", 1)[0] + "?expires=9999999999&signature=invalid", trust_env=False)
check("Unsigned output download is blocked", unsigned.status_code == 403)
after = {str(p): (p.stat().st_size, p.stat().st_mtime_ns) for p in runtime_paths}
check("Installed runtimes and Kokoro models remained unchanged across users and jobs", before == after)
for name in (doc_job, video_job):
    log = (STATE / "worker-data" / name / "render.log").read_text(encoding="utf-8", errors="replace").lower()
    check("No package installation or tool download during " + name, not any(word in log for word in ("downloading", "pip install", "npm install")))
valves["NARRATION"] = True
client.post("/api/v1/functions/id/video_creator_test/valves/update", headers={"Authorization": "Bearer " + admin["token"]}, json=valves).raise_for_status()
report_path = STATE / "live-test-report.json"
report = json.loads(report_path.read_text())
report["checks"].extend(checks)
report["document_job"] = doc_job
report["video_source_job"] = video_job
report["runtime_assets_unchanged"] = True
report_path.write_text(json.dumps(report, indent=2))
print("Additional live source checks passed.", flush=True)
