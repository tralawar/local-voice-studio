# Local Voice Studio for Drama 3

A local workspace for the Fish Audio Drama 3 backend in audio.cpp. **Built with Fish Audio.**
This is an independent UI project, not an official Fish Audio product. New UI/server code is covered by the repository's Apache-2.0 license. Model weights have a different license; see [LICENSES.md](LICENSES.md).

For the standalone source archive, start with [RELEASE.md](RELEASE.md): one Windows setup command, prerequisites, model licensing, startup and upgrades. No Drama model is included or downloaded.

## Run without Pinokio on Windows 10 or newer

`launch-standalone.cmd` starts the standalone supervisor, which owns **both** the native Drama inference process and the workspace process. It does not call Pinokio. Keep the launcher open; Ctrl+C stops only its owned children.

Child lifetime is enforced by a Windows [kill-on-close Job Object](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects). The job is assigned inside process creation through [PROC_THREAD_ATTRIBUTE_JOB_LIST](https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute), and its handle is not inherited. Abrupt supervisor termination therefore closes its ownership handle and terminates its contained children/descendants. There is no post-spawn assignment window. An occupied UI port is rejected before starting either child.

Configure once with a verified existing executable and model (no model copy/download):

```sh
python standalone.py --configure --engine-exe /path/to/audiocpp_server.exe --model /path/to/existing.gguf --cuda-bin /path/to/CUDA/bin
launch-standalone.cmd
```

Configuration copies only the verified engine executable into ignored `.native/`, verifies its SHA-256, and records private paths in ignored `standalone.local.json`. An existing system CUDA toolkit and Visual C++ runtime are still prerequisites. The observed installed engine used system CUDA 12.9 DLLs; this is independent of the original launcher's locally provisioned build toolkit. No system setting is changed. Python/STT uses this workspace's `.venv`, and all original models/configuration remain in place.

The launcher refuses a normal start while another `audiocpp_server.exe` exists, to avoid loading the large model twice. Finish any generation and coordinate closing the existing engine before transitioning. It never kills another app. `--verify-only` instead starts its own UI/engine on temporary ports with lazy model loading, verifies health and ownership without allocating model weights, then stops only those test processes. This mode and full standalone synthetic generation were exercised on GoodBox. The owner subsequently confirmed the UI works, including dictation.

For review, `--static /path/to/candidate-dist` can select an independently built UI directory without replacing the active preview's assets. Logs/configuration/verification records stay in ignored `.runtime/`. Do not publish `.native`, `.runtime`, settings, weights or virtual environments.

## What it does

- Saves scripts, generation settings, references, and completed WAV takes in local SQLite.
- Keeps editor/form state when switching pages, saves the script automatically, and detects conflicting edits from another browser tab.
- Voice presets: import an audio file, convert it to mono PCM WAV in the browser, save/edit its name and exact transcript, preview, download, delete to Trash, and restore.
- Generation history: search scripts/seeds/status, play/download audio, restore script/settings, and recover deleted items.
- Choose a Windows output folder once beside Generate; future completed takes automatically export as WAV. Save as is available on playback/history. Internal history keeps its copy when an external save fails. Retry explicitly after reconnecting a disk; old history is never bulk-exported automatically.
- English spelling and grammar checks with bundled Harper WebAssembly; no remote checker or browser spellcheck service.
- Whitespace formatter with Undo that preserves speaker and emotion tags.
- Optional English dictation using Whisper tiny.en through faster-whisper on CPU/int8. It processes independent four-second segments, **not true streaming ASR**. The microphone pauses during inference. Explicit Stop flushes the last segment; switching pages/hiding the window discards pending results and releases the microphone.
- Dictation is available independently in the script and Create Voice's reference transcript. One microphone session is shared; results append only to the chosen field. Permission/device/network/empty-recording errors preserve existing text and explain how to retry. Unsaved reference text triggers an unload warning.
- Local backups, storage usage, recoverable deletion, and explicit Trash compaction with a recovery backup.

## Install and run against an existing engine

Requirements: Python 3.10+, Node.js 22.12+ and npm for setup/build. Inference uses an existing local audio.cpp Drama 3 server. Normal operation needs no Node.js server.

From an audio.cpp fork containing this directory (the standalone source archive instead places the UI at its root):

```sh
git clone "$RepoUrl" local-voice-studio  # Copy RepoUrl from the Forge release Code link first
cd local-voice-studio  # Standalone source release root; development fork: webui/drama-studio
python setup.py
python run.py --engine http://127.0.0.1:ENGINE_PORT
```

Open `http://127.0.0.1:8046`. The service binds only to loopback. Choose `--port` if occupied; stored data survives port changes. Pinokio users can obtain the current engine URL with `pterm status drama-3 --probe`; use its `ready_url` rather than assuming a fixed port. The original interface remains available from Setup & privacy.

With optional local dictation:

```sh
python setup.py --with-stt
python run.py --engine http://127.0.0.1:ENGINE_PORT
```

Setup creates `.venv` for optional STT dependencies, installs public packages, and downloads the four required tiny.en files from the official Systran repository. The model is **78,090,594 bytes** (about 78.1 MB decimal). Allow roughly 600 MB additional disk space for Python dependencies/environment, plus npm build dependencies. Installation requires internet; generation/checking/dictation then work offline. The installed frontend includes a 20.3 MB local Harper WASM asset.

STT revision is pinned to `0d3d19a32d3338f10357c0889762bd8d64bbdeba`; SHA-256 values are in `setup.py`. Existing matching files are reused. Interrupted downloads leave `.partial` files and resume if the server supports byte ranges. Ctrl+C cancels setup. A checksum mismatch stops setup and leaves the partial file for diagnosis. No automatic model download happens when pressing Dictate.

To reuse an already downloaded model:

```sh
python run.py --engine http://127.0.0.1:ENGINE_PORT --stt-model /path/to/complete/whisper-tiny.en
```

Missing STT dependencies/files produce a Not installed state. The loader uses an explicit local directory and `local_files_only=True`; missing files do not trigger runtime downloads. English tiny.en prioritizes low resource use and latency; it is not suitable for all languages or noisy input. No microphone permission is requested until the user presses Dictate.

## Fresh Drama engine / model setup

The development fork uses a snapshot of audio.cpp commit `18bba55495c8991bbbfe7625234d4d8dbc6e82f4`. The standalone source release does not bundle that engine; see RELEASE.md for the separate pinned clone/build. Preserve upstream LICENSE and submodule notices. Optional upstream frontend adapters are unnecessary for this UI. If independently using those adapters, initialize the optional submodule with the public URL:

```sh
git -c submodule.external/audio.cpp-server-frontends.url=https://github.com/0xShug0/audio.cpp-server-frontends.git submodule update --init --recursive
```

On Windows/NVIDIA, use upstream's build script from the repository root:

```powershell
powershell -File scripts/build_windows.ps1 -Preset windows-cuda-release -ModelSet custom -Models fish_drama3 -Target audiocpp_server -Jobs 8
```

Visual Studio C++ build tools and a complete CUDA toolkit are prerequisites. The original installation uses CUDA 12.8.1. GPU/driver/build requirements follow upstream. This UI's real engine tests reuse the existing GoodBox build; a complete clean CUDA/toolchain installation has **not** been retested.

`bootstrap_engine.py --model /path/to/existing.gguf --build --cuda-root /path/to/cuda` automates that Windows build and writes a new local engine configuration, without changing/copying the existing model. It refuses to overwrite an existing local configuration. The public release is bring-your-own-model: it never downloads Drama weights or accepts a model agreement. With the standalone UI archive, supply `--source-dir` pointing to the pinned upstream engine checkout; see RELEASE.md. The bootstrap does not install system Visual Studio/CUDA.

Do not download the whole Jmica repository (it contains multiple large quantizations). The selected single weight file is **24,596,497,888 bytes** (~24.6 GB decimal). Allow additional disk space for build/tools and at least 32 GB RAM for the current offload profile. The complete checkpoint does not fit the 4090 with normal desktop overhead; current local configuration uses `fish_drama3.cpu_expert_layers=8` and context length 4096.

Before a new Drama weight download, the operator must independently review the upstream [Fish Audio Community License](https://huggingface.co/fishaudio/drama-3/blob/main/LICENSE), verify their rights and intended use, and preserve the [Jmica conversion notices](https://huggingface.co/Jmica/Drama-3-GGUF). No installer here accepts a gated agreement or grants a model license. Only after that review, these are the specific public files:

```sh
hf download Jmica/Drama-3-GGUF drama-3-backbone-8bit-experts-Q4_K_S.gguf LICENSE NOTICE --revision 17a5b40c5dc2c2be986f5371a7e650108b828e29 --local-dir models/Drama-3-GGUF
```

Expected model SHA-256 from the installed download metadata: `05af716baf78e7c20863b9ccebb3ebdeca9607dd3ea7d0b72c35079e675b212b`. No new Drama weights were downloaded for this work.

Copy `engine-config.example.json`, set the model path for your own installation, and launch the compiled server with `--config` and a free loopback port. Then point `run.py --engine` at it. The model must register as `drama-3` for this focused workspace.

## Data, migration, and rollback

Default storage is `data/studio.sqlite3`, with private recovery snapshots in `data/backups/`. Use `--data /private/path` or `DRAMA_STUDIO_DATA` to keep a stable location outside the checkout. Model files are separate. Browser IndexedDB and browser quota are not used for the new library/history.

The previous audio.cpp UI's voices are origin-bound. **Nothing here reads its private browser database.** On its original URL/port, use its Voices page to download the references you want to move, then add each WAV and matching transcript in this workspace. Originals remain untouched. Generic compatible batch exports can be imported in Setup & privacy; every batch is fully validated before writing and existing IDs are never overwritten. Export format:

```json
{"schema":"local-voice-studio.voices.v1","voices":[{"name":"My reference","transcript":"Exact words","audio":"BASE64_PCM_WAV"}]}
```

Voice export JSON contains private audio/transcripts. Treat it like a private recording. Import limit is 30 MB in the UI; per-reference WAV limit is 20 MB. Engine output is limited to 32 MB per take. Nothing is silently pruned. Trash can be restored; Empty Trash creates a full backup before deleting/compacting. Backups retain deleted content and occupy space until the user removes them.

Create a backup before updates. To restore, stop this workspace, preserve its current data directory, and use `restore.py --data /path/to/data --backup <filename>`; it accepts only a schema-1 snapshot inside that data directory's `backups` folder and creates a backup of the current database first. Restore is an operator command, never a web filesystem endpoint.

Rollback to the original UI simply means reopening the existing engine URL. The original source/config/models/outputs/browser library were never replaced. Incomplete jobs are marked Interrupted on the next workspace start, retaining their original script/settings for retry. Cancel closes the engine request and suppresses saving its late audio; the native backend may need time to finish unwinding before accepting another request.

## API

Same-origin loopback requests only; there is no CORS wildcard or client-supplied filesystem path API. Output-folder selection and Save as use explicit Windows native pickers and a per-service action token. Export retries are restricted to the selected folder. Do not expose this development service publicly.

```sh
curl http://127.0.0.1:8046/api/status
curl http://127.0.0.1:8046/api/history
curl -H "Content-Type: application/json" -d '{"text":"A synthetic test.","seed":1234,"maxTokens":1500}' http://127.0.0.1:8046/api/generate
```

```js
const job = await fetch('/api/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({text:'A synthetic test.',seed:1234})}).then(r=>r.json());
const state = await fetch(`/api/history/${job.id}`).then(r=>r.json());
// When complete: GET /api/history/<id>/audio
```

```python
import json, urllib.request
request = urllib.request.Request('http://127.0.0.1:8046/api/generate', data=json.dumps({'text':'A synthetic test.'}).encode(), headers={'Content-Type':'application/json'})
job = json.load(urllib.request.urlopen(request))
```

Other operations: `GET/POST /api/draft` (revision required), `GET/POST /api/voices`, `GET /api/voices/export`, `POST /api/voices/import`, `POST /api/transcribe` (raw audio bytes), `POST /api/history/<id>/cancel`, and `POST /api/{voices,history}/<id>/{delete,restore}`. `GET /api/output-folder`, `POST /api/output-folder/{choose,clear}` and `POST /api/history/<id>/{save-as,export}` use native-picker authorization (POST body `{}`, exact Origin and `X-Output-Token` from output preferences required). `GET /api/storage`, `POST /api/backup`, `POST /api/empty-trash` (`{"confirm":"EMPTY TRASH"}`).

Keyboard: Ctrl/Cmd+Enter generates, Alt+1…4 changes page, Escape stops dictation and transcribes its final segment. All visible controls remain keyboard focusable.

## Validation and release

```sh
python -m unittest discover -s tests -v
node tests/text.test.mjs
node tests/dictation.test.mjs
node tests/dictation_timers.test.mjs
node tests/dictation_targets.test.mjs
node tests/voice_edit.test.mjs
node tests/draft.test.mjs
node tests/offline_harper.mjs
```

Optional STT offline fixture test: `.venv/Scripts/python tests/offline_stt.py /path/to/synthetic.wav` (use `.venv/bin/python` on Unix). It denies all Python socket connections. See [VALIDATION.md](VALIDATION.md) for measured results and limitations.

Optional codec regression: `.venv/Scripts/python tests/codecs_stt.py /path/to/synthetic.wav` encodes a synthetic WAV as WebM/Opus and MP4/AAC, transcribes each with sockets disabled, and checks an actionable invalid-container error. No microphone is accessed. Technical dictation failure logging records only stage/error type/MIME/byte count, never audio or transcript text.

Native Chrome capture/timer regression on Windows: `python tests/browser_dictation.py`. It creates an isolated headless browser profile and generated Web Audio stream, uses real MediaRecorder/window timers, reports through its own localhost test endpoint, and closes the browser job. It never requests a real microphone or uses the user's browser profile. Chrome's default installed path may be overridden with `--browser`.

Only release tracked source and lockfiles. Never package `data*`, backups, `.venv`, npm caches, models, generated WAVs, user configuration, logs, or local export files. This release distributes independently written UI/server source and installation instructions. Fish code, weights and derivatives are excluded; users acquire their own models separately under the applicable license. Do not host self-service inference on Forge or suggest unlimited commercial rights. Publication is coordinated by the release owner.
