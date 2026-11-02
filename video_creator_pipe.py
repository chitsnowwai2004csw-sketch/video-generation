"""
title: Video Creator
description: Connect Open WebUI uploads and chat to a HyperFrames/Remotion video worker.
version: 1.1.0
license: MIT
"""

import asyncio
import base64
import hashlib
import json
import mimetypes
import re
import tempfile
import time
from urllib.parse import quote, urlsplit

import httpx
from pydantic import BaseModel, Field

# Both imports are built into Open WebUI. There is deliberately no requirements
# frontmatter, pip/npm installation, subprocess execution, or model download here.
# Rendering tools belong to one administrator-managed shared worker.


class Pipe:
    class Valves(BaseModel):
        VIDEO_API_URL: str = Field(default="", description="Video worker API, e.g. http://video-worker:8001")
        VIDEO_API_KEY: str = Field(default="", description="Shared secret accepted by the video worker")
        OPENWEBUI_INTERNAL_URL: str = Field(default="http://127.0.0.1:8080", description="Open WebUI URL reachable from its own backend; no /api suffix")
        PUBLIC_OUTPUT_URL: str = Field(default="", description="Optional browser-reachable origin for relative output links")
        RENDERER: str = Field(default="hyperframes", pattern="^(hyperframes|remotion)$")
        PRESET: str = Field(default="explainer", pattern="^(explainer|slideshow|brag)$")
        NARRATION: bool = True
        LANGUAGE: str = "en"
        VOICE: str = "af_heart"
        WIDTH: int = Field(default=1920, ge=256, le=3840)
        HEIGHT: int = Field(default=1080, ge=256, le=3840)
        FPS: int = Field(default=30, ge=1, le=60)
        MAX_FILES: int = Field(default=12, ge=1, le=100)
        MAX_FILE_MB: int = Field(default=100, ge=1, le=2048)
        MAX_TOTAL_MB: int = Field(default=300, ge=1, le=4096)
        REQUEST_TIMEOUT: int = Field(default=120, ge=5, le=600)
        WAIT_SECONDS: int = Field(default=30, ge=0, le=300, description="After this, return the job ID; rendering continues in the worker")
        POLL_SECONDS: float = Field(default=2, ge=0.1, le=30)

    class UserValves(BaseModel):
        RENDERER: str = Field(default="", pattern="^(|hyperframes|remotion)$", description="Leave blank to use the shared default")
        PRESET: str = Field(default="", pattern="^(|explainer|slideshow|brag)$")
        NARRATION: bool | None = Field(default=None, description="Use the shared default when unset")
        LANGUAGE: str = ""
        VOICE: str = ""

    def __init__(self):
        self.valves = self.Valves()

    async def pipe(self, body: dict, __user__: dict = None, __request__=None,
                   __event_emitter__=None, __files__: list = None,
                   __metadata__: dict = None, __task__: str = None,
                   __chat_id__: str = None, __message_id__: str = None) -> str:
        # Open WebUI can invoke the model for titles, tags, and suggestions.
        # Those requests must never create extra renders.
        if __task__:
            return "Video Creator"
        job_id = None

        async def status(text, done=False):
            if __event_emitter__:
                try:
                    await __event_emitter__({"type": "status", "data": {"description": text, "done": done}})
                except Exception:
                    pass  # A closed browser must not invalidate the worker's job.

        try:
            messages = body.get("messages", [])
            latest = next((m for m in reversed(messages) if m.get("role") == "user"), {})
            prompt = self._text(latest.get("content", "")).strip()
            if prompt.lower() in ("/help", "help"):
                return self._help()
            if not self.valves.VIDEO_API_URL or not self.valves.VIDEO_API_KEY:
                return "Configure VIDEO_API_URL and VIDEO_API_KEY in this Function's Valves. This Pipe requires a running video worker. Use /help for commands."
            base = self._base(self.valves.VIDEO_API_URL)
            user_id = str((__user__ or {}).get("id") or "")
            if not user_id:
                raise ValueError("An authenticated Open WebUI user is required.")
            headers = {"Authorization": "Bearer " + self.valves.VIDEO_API_KEY, "X-OpenWebUI-User-ID": user_id}
            preferences = (__user__ or {}).get("valves") or {}
            if isinstance(preferences, BaseModel):
                preferences = preferences.model_dump()
            preferences = self.UserValves(**preferences).model_dump()
            def setting(name):
                value = preferences.get(name)
                return value if value is not None and value != "" else getattr(self.valves, name)
            metadata = __metadata__ or {}
            chat_id = __chat_id__ or metadata.get("chat_id")
            message_id = __message_id__ or metadata.get("message_id")
            command = re.fullmatch(r"/(status|cancel|revise)\s+([A-Za-z0-9_-]{1,128})(?:\s+([\s\S]+))?", prompt)
            async with httpx.AsyncClient(timeout=self.valves.REQUEST_TIMEOUT, follow_redirects=False, trust_env=False) as client:
                if prompt.lower() == "/health":
                    health = await self._json(client, "GET", base + "/health", headers)
                    ready = health.get("ready") is True
                    tools = health.get("tools", {})
                    if not isinstance(tools, dict):
                        raise ValueError("Worker health must return a tools object.")
                    lines = ["Shared video worker: **" + ("ready" if ready else "not ready") + "**"]
                    for name in ("hyperframes", "remotion", "kokoro", "ffmpeg", "brag"):
                        tool = tools.get(name, {})
                        installed = isinstance(tool, dict) and tool.get("ready") is True
                        lines.append(f"- {name}: " + ("ready" if installed else "not configured"))
                    lines.append("Tools are installed once on the server. Users do not install them.")
                    await status("Shared worker checked", True)
                    return "\n".join(lines)
                if command:
                    action, job_id, instructions = command.groups()
                    path = "/jobs/" + quote(job_id, safe="")
                    if action == "status":
                        job = await self._json(client, "GET", base + path, headers)
                        await status("Job status retrieved", True)
                        return self._result(job)
                    if action == "cancel":
                        job = await self._json(client, "POST", base + path + "/cancel", headers, json={})
                        await status("Cancellation requested", True)
                        return self._result(job)
                    if not instructions:
                        return "Use /revise JOB_ID followed by your changes."
                    headers["Idempotency-Key"] = self._key(user_id, chat_id, message_id, prompt)
                    job = await self._json(client, "POST", base + path + "/revisions", headers,
                                           json={"instructions": instructions, "chat_id": chat_id})
                else:
                    if prompt.startswith("/"):
                        return self._help()
                    if not prompt:
                        return "Describe the video you want, and optionally attach images, videos, audio, or documents."
                    attached = __files__ if __files__ is not None else metadata.get("files", body.get("files", []))
                    sources = self._sources(attached or [], latest)
                    if len(sources) > self.valves.MAX_FILES:
                        raise ValueError(f"At most {self.valves.MAX_FILES} sources are allowed.")
                    await status("Forwarding source files")
                    assets = await self._upload(client, base, headers, sources, __request__)
                    payload = {
                        "instructions": prompt,
                        "chat_id": chat_id,
                        "message_id": message_id,
                        "assets": assets,
                        "settings": {
                            "renderer": setting("RENDERER"), "preset": setting("PRESET"),
                            "width": self.valves.WIDTH, "height": self.valves.HEIGHT,
                            "fps": self.valves.FPS,
                            "narration": {"enabled": setting("NARRATION"), "provider": "kokoro",
                                          "language": setting("LANGUAGE"), "voice": setting("VOICE")},
                        },
                    }
                    headers["Idempotency-Key"] = self._key(user_id, chat_id, message_id, json.dumps(payload, sort_keys=True))
                    await status("Submitting video job")
                    job = await self._json(client, "POST", base + "/jobs", headers, json=payload)
                job_id = self._job_id(job)
                deadline = time.monotonic() + self.valves.WAIT_SECONDS
                while job.get("status") not in {"completed", "failed", "cancelled"}:
                    await status(f"Video job {job_id}: {job.get('stage') or job.get('status', 'queued')}")
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    await asyncio.sleep(min(self.valves.POLL_SECONDS, remaining))
                    job = await self._json(client, "GET", base + "/jobs/" + quote(job_id, safe=""), headers)
                await status("Video job " + str(job.get("status", "queued")), True)
                return self._result(job)
        except (ValueError, httpx.HTTPError) as exc:
            await status("Video request could not finish", True)
            if isinstance(exc, httpx.HTTPStatusError):
                # Do not echo URLs, response bodies, signed links, or credentials.
                detail = f"Video API or source download returned HTTP {exc.response.status_code}. Check worker logs and settings."
            elif isinstance(exc, httpx.HTTPError):
                detail = "Cannot reach the video API or Open WebUI file service. Check URLs, networking, and timeouts."
            else:
                detail = str(exc)
            if job_id:
                detail += f"\n\nThe worker may still be running. Use `/status {job_id}`."
            else:
                detail += "\n\nIf submission timed out, check the worker before submitting again."
            return detail

    @staticmethod
    def _text(content):
        if isinstance(content, str):
            return content
        return "\n".join(p.get("text", "") for p in content or [] if isinstance(p, dict) and p.get("type") == "text")

    @staticmethod
    def _base(value):
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Service URLs must be HTTP(S) URLs without credentials, queries, or fragments.")
        return value.rstrip("/")

    @staticmethod
    def _key(user, chat, message, fallback):
        # A message ID is stable even when attachment ingestion returns new IDs.
        identity = [user, chat, message] if message else [user, chat, fallback]
        return hashlib.sha256(json.dumps(identity).encode()).hexdigest()

    @staticmethod
    def _job_id(job):
        value = str(job.get("id", ""))
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
            raise ValueError("The video worker must return a valid job id.")
        return value

    async def _json(self, client, method, url, headers, **kwargs):
        response = await client.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError("The video worker must return a JSON object.")
        return data

    def _sources(self, files, latest):
        sources, seen = [], set()

        def add(value):
            key = value.get("id") or hashlib.sha256(value["data"].encode()).hexdigest()
            if key not in seen:
                seen.add(key)
                sources.append(value)

        for item in files:
            if not isinstance(item, dict):
                raise ValueError("Unrecognized attachment format. Upload sources as individual files.")
            nested = item.get("file") or {}
            file_id = nested.get("id") or item.get("id")
            if item.get("type") in {"collection", "folder", "knowledge"} or not file_id:
                raise ValueError("Attach individual source files; knowledge collections are not original media files.")
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", str(file_id)):
                raise ValueError("Invalid Open WebUI file id.")
            name = nested.get("filename") or item.get("name") or "source"
            add({"id": str(file_id), "name": str(name)})
        content = latest.get("content", [])
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") != "image_url":
                continue
            image = part.get("image_url", {})
            value = image.get("url", "") if isinstance(image, dict) else image
            if not isinstance(value, str):
                raise ValueError("Invalid image attachment.")
            if value.startswith("data:image/"):
                add({"data": value, "name": "image"})
            else:
                parsed = urlsplit(value)
                match = re.fullmatch(r"/api/v1/files/([A-Za-z0-9_-]{1,128})/content(?:/[^/]*)?", parsed.path)
                if not match:
                    if parsed.netloc:
                        raise ValueError("Upload remote images as files. External image URLs are not downloaded by this Pipe.")
                    raise ValueError("Unrecognized image URL. Upload the image as a file or inline image.")
                # The browser's public gateway origin can differ from the
                # container's internal origin. Resolve only the file ID and
                # fetch from the configured internal API with caller auth.
                # Never request the URL's supplied host.
                add({"id": match.group(1), "name": "image"})
        return sources

    async def _upload(self, client, base, headers, sources, request):
        assets, total = [], 0
        limit = self.valves.MAX_FILE_MB * 1024 * 1024
        total_limit = self.valves.MAX_TOTAL_MB * 1024 * 1024
        auth = {}
        if request is not None:
            # Forward caller credentials only to the configured Open WebUI origin.
            for name in ("authorization", "cookie"):
                if request.headers.get(name):
                    auth[name] = request.headers[name]
        for source in sources:
            with tempfile.TemporaryFile() as spool:
                size = 0
                if "data" in source:
                    match = re.fullmatch(r"data:(image/[A-Za-z0-9.+-]+);base64,([\s\S]*)", source["data"])
                    if not match or len(match.group(2)) > ((min(limit, total_limit - total) + 2) // 3) * 4:
                        raise ValueError("Inline image is invalid or exceeds the upload limit.")
                    mime = match.group(1)
                    try:
                        raw = base64.b64decode(match.group(2), validate=True)
                    except ValueError:
                        raise ValueError("Invalid base64 image.") from None
                    size = len(raw)
                    spool.write(raw)
                else:
                    if not auth:
                        raise ValueError("Cannot download source files without the current user's HTTP credentials. Use an authenticated Open WebUI session.")
                    url = self._base(self.valves.OPENWEBUI_INTERNAL_URL) + "/api/v1/files/" + quote(source["id"], safe="") + "/content"
                    async with client.stream("GET", url, headers=auth) as response:
                        response.raise_for_status()
                        mime = response.headers.get("content-type", "application/octet-stream").split(";")[0]
                        async for chunk in response.aiter_bytes(65536):
                            size += len(chunk)
                            if size > limit or total + size > total_limit:
                                raise ValueError("Source files exceed MAX_FILE_MB or MAX_TOTAL_MB.")
                            spool.write(chunk)
                if size > limit or total + size > total_limit:
                    raise ValueError("Source files exceed MAX_FILE_MB or MAX_TOTAL_MB.")
                total += size
                spool.seek(0)
                filename = re.split(r"[/\\]", source["name"])[-1]
                filename = re.sub(r"[\x00-\x1f\x7f]", "_", filename)[:200] or "source"
                if "data" in source:
                    filename += "." + {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime, "bin")
                elif not re.search(r"\.[A-Za-z0-9]{1,12}$", filename):
                    filename += mimetypes.guess_extension(mime) or ""
                asset = await self._json(client, "POST", base + "/assets", headers,
                                         files={"file": (filename, spool, mime)})
                if not isinstance(asset.get("id"), str) or not asset["id"]:
                    raise ValueError("The worker's /assets endpoint must return an id.")
                assets.append({"id": asset["id"], "name": filename, "content_type": mime})
        return assets

    def _result(self, job):
        job_id = self._job_id(job)
        state = str(job.get("status", "unknown"))
        lines = [f"Video job: `{job_id}`", f"Status: **{state}**"]
        if state == "failed":
            lines.append("Rendering failed. Ask the administrator to check the worker logs for this job ID.")
        for label, value in (job.get("outputs") or {}).items():
            if label not in {"video", "thumbnail", "subtitles", "project"} or not isinstance(value, str):
                continue
            if value.startswith("/") and not value.startswith("//"):
                root = self.valves.PUBLIC_OUTPUT_URL or self.valves.VIDEO_API_URL
                value = self._base(root) + value
            parsed = urlsplit(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc and not parsed.username and not parsed.password:
                # Escape Markdown delimiters and control characters in worker URLs.
                value = quote(value, safe=":/?&=%#+@,;~!$*'-._")
                lines.append(f"[{label.capitalize()}]({value})")
        if state not in {"completed", "failed", "cancelled"}:
            lines.append(f"Rendering continues in the worker. Check with `/status {job_id}`.")
        lines.append(f"Changes: `/revise {job_id} describe your changes`")
        return "\n\n".join(lines)

    @staticmethod
    def _help():
        return (
            "Attach images, videos, audio, or documents and describe your video.\n\n"
            "Commands: `/health`, `/status JOB_ID`, `/cancel JOB_ID`, `/revise JOB_ID your changes`, `/help`.\n\n"
            "Tools are shared on the server. Users do not install or download rendering tools.\n\n"
            "The administrator configures HyperFrames or Remotion, the preset (explainer, slideshow, brag), "
            "and Kokoro narration in Valves. Use User Valves to override your renderer, preset, or voice. "
            "Rendering requires a separate video worker implementing "
            "the API documented in VIDEO_PIPE_SETUP.md."
        )
