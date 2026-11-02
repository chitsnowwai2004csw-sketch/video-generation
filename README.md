# Video Creator for Open WebUI — Docker package

Install once on the server. Users access Video Creator through Open WebUI in a browser.

For a fresh server, place the separate `video_creator_docker_images.tar.gz` archive next to this extracted package and run:

```powershell
docker load -i video_creator_docker_images.tar.gz
docker compose up -d --no-build
```

Open http://localhost:3000, create the first administrator account, then run:

```powershell
docker compose --profile tools run --rm configure
```

The configuration command prompts for the administrator login and connects the shared worker automatically. No manual worker API key copying is required.

For an existing Docker Open WebUI, follow **Option B** in [DOCKER_SETUP.md](DOCKER_SETUP.md). It uses `compose.existing.yaml` and keeps the existing container and database. Both deployment modes were tested; see [DOCKER_TEST_RESULTS.md](DOCKER_TEST_RESULTS.md).

If you prefer to build instead of loading the prebuilt images, run `docker compose up -d --build`. The build downloads server dependencies/model assets; ordinary user jobs reuse the image.

Default output uses simple source montages. Optional external text planning, Brag-style preset behavior, source-format support, and current limits are described in the setup guide. This first release targets Linux/amd64 containers.
