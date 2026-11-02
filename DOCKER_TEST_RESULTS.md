# Docker release verification

Verified locally on October 30, 2026, using Docker Engine 29.7.2 and Docker Compose 5.5.0 with Linux/amd64 containers. These checks ran against the real containerized Open WebUI 0.12.4 slim and the real rendering worker.

## Fresh stack

- Built `video-creator-worker:1.0.0` and `video-creator-webui:0.12.4` successfully.
- Worker runs as UID 10001; its management API has no published host port.
- Chromium, FFmpeg, HyperFrames 0.8.185, Remotion 4.0.539, Kokoro runtime, and checksum-verified voice/model files are installed in the image.
- Kokoro synthesized speech during the image build and during both renderer tests.
- The one-time configuration command imported and enabled the Pipe, saved its worker connection/key, and granted regular users access.
- Two regular test accounts successfully used the shared tool health command without installing anything.
- Uploaded a PNG through the gateway and forwarded its original bytes through Open WebUI to the worker.
- HyperFrames rendered a 960×540 H.264/AAC MP4, duration 3.008 seconds.
- Remotion rendered a 960×540 H.264/AAC MP4, duration 3.008 seconds.
- Both signed MP4 downloads passed through the gateway. FFprobe inspection and decoded thumbnail inspection passed.
- Cross-user job access was rejected. Worker management URLs were not exposed through the browser gateway.
- Renderer job logs contained no tool downloads or package installation commands.
- Worker restart preserved its API key and completed jobs.
- Replacing the worker image preserved previously completed jobs.
- A public gateway `/api/v1/files/{id}/content` image reference was accepted through the final Pipe, resolved by ID against the authenticated internal API, and submitted as a valid job. That extra verification job was cancelled after submission.
- Nginx configuration validation passed. Docker DNS resolution is dynamic so container IP changes do not require static upstream addresses.

## Existing Open WebUI add-on

Used the fresh stack's disposable Open WebUI as the existing deployment, on its real Docker network:

- Started `compose.existing.yaml` without declaring or replacing the existing Open WebUI container.
- Verified the existing container ID stayed unchanged.
- Configured the add-on with the existing administrator account.
- An existing regular account used the add-on gateway, submitted an uploaded image, and obtained a real rendered MP4.
- Signed downloads passed through the add-on gateway; management URLs remained private.
- Restored the primary test Pipe afterward and stopped the add-on containers without deleting their test volumes.

## Automated checks and scope

Nineteen adapter/configuration tests passed. Compose configuration validation passed for both deployment options. The release installer and final worker health check also passed after the last image rebuild. Rebuild logs show the tool/model provisioning layer reused from cache for application-only changes.

The sample renders used local source-template planning. An external LLM planner, OCR, video transcription, PDF/PPTX browser uploads, internet-facing TLS deployment, high concurrency, and GPU passthrough were not tested. The first worker's documented functional limits remain unchanged. End users do not download tools; initial administrator image build/load and deliberate image updates can transfer dependencies/model assets.

Docker images contain application files and preloaded tool/model assets. Generated secrets, accounts, uploaded originals, and rendered jobs are stored in volumes, which are not included in image exports.
