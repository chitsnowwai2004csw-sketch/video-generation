"""Contract tests for the Open WebUI adapter; no real renderer is required."""

import base64
import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from video_creator_pipe import Pipe


class PipeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.pipe = Pipe()
        self.pipe.valves.VIDEO_API_URL = "http://worker:8001"
        self.pipe.valves.VIDEO_API_KEY = "worker-secret"
        self.pipe.valves.PUBLIC_OUTPUT_URL = "https://videos.example.com"
        self.pipe.valves.WAIT_SECONDS = 0
        self.calls = []

    def client(self, handler):
        # Construct before patching the factory, using a real HTTPX client.
        instance = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return patch("video_creator_pipe.httpx.AsyncClient", return_value=instance)

    async def invoke(self, text, **kwargs):
        return await self.pipe.pipe(
            {"messages": [{"role": "user", "content": text}]},
            __user__={"id": "user-1"}, **kwargs,
        )

    async def test_help_and_background_tasks_never_submit(self):
        with patch("video_creator_pipe.httpx.AsyncClient", side_effect=AssertionError("unexpected network")):
            self.assertIn("/status", await self.invoke("/help"))
            self.assertEqual(await self.invoke("generate a title", __task__="title_generation"), "Video Creator")

    async def test_original_file_uses_caller_auth_only_for_download(self):
        def handler(request):
            self.calls.append(request)
            if request.url.host == "127.0.0.1":
                self.assertEqual(request.headers["authorization"], "Bearer caller-secret")
                self.assertNotIn("x-openwebui-user-id", request.headers)
                return httpx.Response(200, content=b"original-video-bytes", headers={"content-type": "video/mp4"})
            self.assertEqual(request.headers["authorization"], "Bearer worker-secret")
            self.assertEqual(request.headers["x-openwebui-user-id"], "user-1")
            self.assertNotIn("cookie", request.headers)
            if request.url.path == "/assets":
                self.assertIn(b"original-video-bytes", request.content)
                return httpx.Response(200, json={"id": "asset-1"})
            payload = json.loads(request.content)
            self.assertEqual(payload["assets"][0]["id"], "asset-1")
            self.assertEqual(payload["settings"]["narration"]["provider"], "kokoro")
            self.assertIn("idempotency-key", request.headers)
            return httpx.Response(202, json={"id": "job-1", "status": "queued"})

        with self.client(handler):
            result = await self.invoke("Create a tutorial", __files__=[{"file": {"id": "file-1", "filename": "clip.mp4"}}],
                                       __request__=SimpleNamespace(headers={"authorization": "Bearer caller-secret"}),
                                       __message_id__="message-1")
        self.assertIn("/status job-1", result)
        self.assertEqual(len(self.calls), 3)

    async def test_inline_image_and_file_reference_deduplication(self):
        value = "data:image/png;base64," + base64.b64encode(b"png-bytes").decode()
        def handler(request):
            if request.url.path == "/assets":
                self.assertIn(b"png-bytes", request.content)
                return httpx.Response(200, json={"id": "asset-image"})
            self.assertEqual(len(json.loads(request.content)["assets"]), 1)
            return httpx.Response(202, json={"id": "image-job", "status": "queued"})
        with self.client(handler):
            result = await self.invoke([
                {"type": "text", "text": "Animate this image"},
                {"type": "image_url", "image_url": {"url": value}},
                {"type": "image_url", "image_url": {"url": value}},
            ])
        self.assertIn("image-job", result)
        sources = self.pipe._sources([{"id": "file-1"}], {"content": [
            {"type": "image_url", "image_url": {"url": "/api/v1/files/file-1/content"}}
        ]})
        self.assertEqual(len(sources), 1)

    async def test_status_has_browser_links_and_no_new_job(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/jobs/job-1")
            return httpx.Response(200, json={"id": "job-1", "status": "completed", "outputs": {
                "video": "/downloads/movie(1).mp4?token=abc",
                "project": "javascript:alert(1)",
            }})
        with self.client(handler):
            result = await self.invoke("/status job-1")
        self.assertIn("https://videos.example.com/downloads/movie%281%29.mp4?token=abc", result)
        self.assertNotIn("javascript:", result)

    async def test_shared_worker_health_does_not_submit_or_install(self):
        def handler(request):
            self.assertEqual(request.method, "GET")
            self.assertEqual(request.url.path, "/health")
            return httpx.Response(200, json={"ready": True, "tools": {
                name: {"ready": True} for name in ("hyperframes", "remotion", "kokoro", "ffmpeg", "brag")
            }})
        with self.client(handler):
            result = await self.invoke("/health")
        self.assertIn("hyperframes: ready", result)
        self.assertIn("Users do not install", result)

    async def test_user_preferences_do_not_change_shared_credentials(self):
        def handler(request):
            self.assertEqual(request.headers["authorization"], "Bearer worker-secret")
            payload = json.loads(request.content)
            self.assertEqual(payload["settings"]["renderer"], "remotion")
            self.assertEqual(payload["settings"]["preset"], "brag")
            self.assertFalse(payload["settings"]["narration"]["enabled"])
            return httpx.Response(202, json={"id": "user-job", "status": "queued"})
        with self.client(handler):
            result = await self.pipe.pipe({"messages": [{"role": "user", "content": "Create a promo"}]},
                __user__={"id": "user-1", "valves": self.pipe.UserValves(RENDERER="remotion", PRESET="brag", NARRATION=False)})
        self.assertIn("user-job", result)

    async def test_revision_and_cancellation_endpoints(self):
        for command, endpoint in [("/revise job-1 Shorten it", "/jobs/job-1/revisions"),
                                  ("/cancel job-1", "/jobs/job-1/cancel")]:
            def handler(request):
                self.assertEqual(request.method, "POST")
                self.assertEqual(request.url.path, endpoint)
                return httpx.Response(200, json={"id": "job-2", "status": "cancelled"})
            with self.client(handler):
                self.assertIn("job-2", await self.invoke(command))

    async def test_denied_source_never_submits_job(self):
        def handler(request):
            self.assertEqual(request.url.host, "127.0.0.1")
            return httpx.Response(403, text="sensitive internal error")
        with self.client(handler):
            result = await self.invoke("Create video", __files__=[{"id": "file-1"}],
                                       __request__=SimpleNamespace(headers={"cookie": "session=secret"}))
        self.assertIn("HTTP 403", result)
        self.assertNotIn("sensitive", result)
        self.assertNotIn("secret", result)

    async def test_limit_blocks_source_before_upload(self):
        self.pipe.valves.MAX_FILE_MB = 1
        def handler(request):
            self.assertEqual(request.method, "GET")
            return httpx.Response(200, content=b"x" * (1024 * 1024 + 1))
        with self.client(handler):
            result = await self.invoke("Create video", __files__=[{"id": "file-1"}],
                                       __request__=SimpleNamespace(headers={"authorization": "Bearer user"}))
        self.assertIn("exceed", result)

    async def test_polling_failure_preserves_recoverable_job_id(self):
        self.pipe.valves.WAIT_SECONDS = 1
        self.pipe.valves.POLL_SECONDS = 0.1
        def handler(request):
            if request.method == "POST":
                return httpx.Response(202, json={"id": "recoverable-job", "status": "running"})
            raise httpx.ConnectError("private URL and credentials", request=request)
        with self.client(handler):
            result = await self.invoke("Create a video")
        self.assertIn("/status recoverable-job", result)
        self.assertNotIn("private URL", result)

    async def test_completed_poll_and_events(self):
        self.pipe.valves.WAIT_SECONDS = 1
        self.pipe.valves.POLL_SECONDS = 0.1
        events = []
        async def emitter(event):
            events.append(event)
        def handler(request):
            return httpx.Response(200, json={"id": "job-1", "status": "queued" if request.method == "POST" else "completed"})
        with self.client(handler):
            result = await self.invoke("Create video", __event_emitter__=emitter)
        self.assertIn("completed", result)
        self.assertTrue(events[-1]["data"]["done"])

    def test_retry_identity_stable_with_message_id(self):
        self.assertEqual(self.pipe._key("u", "c", "m", "asset-one"), self.pipe._key("u", "c", "m", "asset-two"))
        self.assertNotEqual(self.pipe._key("u", "c", "m", "x"), self.pipe._key("another-user", "c", "m", "x"))

    def test_remote_image_rejected(self):
        with self.assertRaisesRegex(ValueError, "Upload remote"):
            self.pipe._sources([], {"content": [{"type": "image_url", "image_url": {"url": "http://other-host/private"}}]})

    def test_public_gateway_file_url_is_resolved_as_internal_file_id(self):
        sources = self.pipe._sources([], {"content": [{"type": "image_url", "image_url": {
            "url": "https://videos.example.com/api/v1/files/file-123/content"
        }}]})
        self.assertEqual(sources, [{"id": "file-123", "name": "image"}])

    async def test_gateway_url_downloads_only_internal_file_and_infers_extension(self):
        def handler(request):
            if request.url.host == "127.0.0.1":
                self.assertEqual(request.url.path, "/api/v1/files/file-123/content")
                return httpx.Response(200, content=b"source-image", headers={"content-type": "image/png"})
            self.assertEqual(request.url.host, "worker")
            if request.url.path == "/assets":
                self.assertIn(b'filename="image.png"', request.content)
                return httpx.Response(200, json={"id": "asset-image"})
            return httpx.Response(202, json={"id": "gateway-job", "status": "queued"})
        with self.client(handler):
            result = await self.invoke([
                {"type": "text", "text": "Create a source montage"},
                {"type": "image_url", "image_url": {"url": "https://public.example.com/api/v1/files/file-123/content"}},
            ], __request__=SimpleNamespace(headers={"authorization": "Bearer user"}))
        self.assertIn("gateway-job", result)


if __name__ == "__main__":
    unittest.main()
