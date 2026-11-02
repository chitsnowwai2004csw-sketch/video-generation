# Local integration test results

Test date: October 30, 2026, Asia/Rangoon.

The Pipe was imported and executed by a real local Open WebUI 0.12.5 installation using its HTTP API. The tests did not use a simulated Open WebUI server. Docker Desktop could not start because of an existing local socket error, so the test used a native Python installation with Open WebUI's slim dependencies and a separate data directory. Browser UI automation was not performed.

## Verified

- The Function imports without installing dependencies. Open WebUI's automatic plugin dependency installer was disabled throughout testing.
- Two regular users can access the same explicitly shared Video Creator model and check shared tool readiness.
- An uploaded image passes through Open WebUI, authenticated original-file download, worker asset ingestion, and durable job creation.
- HyperFrames 0.8.185 produced a 1280×720 H.264/AAC MP4 with local Kokoro narration: 3.000 seconds.
- Remotion 4.0.539 produced a 1280×720 H.264/AAC MP4 with local Kokoro narration: 3.008 seconds.
- Both renderer outputs were downloaded successfully, checked with FFprobe, and visually inspected using decoded thumbnail frames.
- A Word document uploaded by the second regular user was extracted and rendered into a 5-second video.
- An uploaded MP4 source was rendered into a 5-second source montage.
- Cross-user access to worker jobs and Open WebUI original uploads was rejected.
- A revision created a new job. Cancelling that job preserved the original completed job.
- Repeating a job submission with its idempotency key returned the existing durable job.
- An output URL with an invalid signature was rejected.
- Installed runtime files, Kokoro model/voice files, and the Remotion browser executable remained unchanged across the additional source jobs. Those job logs contained no package installation or tool download.
- Re-running Remotion browser setup printed `Remotion browser cache reused.`
- Thirteen adapter tests passed. Python and Node.js syntax checks passed.

## Scope and remaining limitations

The render tests used the included source-template planner, not an external language model. A complete interactive Brag workflow was not tested; the worker includes adapted Brag-style planning instructions for an optional external planner. Image understanding, video transcription, OCR, complex visual editing, arbitrary target-duration following, and word-level subtitle alignment are not implemented by the first worker.

The source tests uploaded files through Open WebUI's API using `process=false`. Browser document upload behavior, external planner integration, PDF/PPTX rendering, production reverse proxies, and production concurrency were not tested. The worker is a single-process starting implementation with local SQLite storage. Cancelling a job prevents publication; a rendering subprocess can finish before the worker moves on.

Initial administrator setup downloads dependencies and missing models/browser assets. Ordinary user requests run installed tools directly and do not invoke package installers. The worker disables HyperFrames automatic updates/installation and points HyperFrames and Remotion at existing browser executables.
