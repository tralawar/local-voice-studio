# Install Local Voice Studio for Drama 3

Independent local UI and server source, Apache-2.0. **Built with Fish Audio.** This is not an official Fish Audio product. The release contains no Fish code, model weights, recorded voices, user data, native engine or Python binaries. The publisher provides downloads and documentation, not a hosted speech service.

## Windows prerequisites

- Windows 10/11 x64; Python 3.10 x64 is the tested version (3.10+ required).
- Node.js 22.12+ and npm during installation; Git only if cloning source. Node is not needed to run the installed app.
- For the tested Drama setup: NVIDIA RTX 4090 24 GB, at least 32 GB system RAM, compatible NVIDIA driver, CUDA toolkit and Visual C++ runtime. The tested existing engine needs CUDA 12.9 runtime DLLs. Other GPUs/platforms are not validated by this release.
- An existing trusted `audiocpp_server.exe` built from the upstream revision below, or Visual Studio C++ tools, CMake and the complete CUDA toolkit to build it yourself. System tools are installed separately; this script never installs drivers or changes system configuration.
- Your separately acquired compatible Drama 3 GGUF. The tested quantization is 24,596,497,888 bytes (~24.6 GB), with eight CPU expert layers and context 4096. Allow at least 30 GB for a new model plus extra space for build/toolchains. An existing model is referenced in place.
- Optional English dictation downloads 78,090,594 bytes (~78.1 MB) plus Python dependencies. Allow at least 1 GB for UI/STT dependencies, additional npm/build caches, and room for generated audio/backups. Download/install requires internet; installed inference, checking and dictation use local resources.

## 1. Obtain this source

Download and extract the source ZIP linked on the Forge release. Open PowerShell in the extracted directory containing `install-windows.ps1`. To use Git instead, copy the release's actual Code URL into `$RepoUrl`, then:

```powershell
git clone "$RepoUrl" local-voice-studio
cd local-voice-studio
```

The standalone source release puts the UI files at the repository/archive root. If using the development audio.cpp fork instead, change to `webui/drama-studio`.

## 2. Acquire/reuse a model under its own license

Review the [Fish Audio Community License](https://huggingface.co/fishaudio/drama-3/blob/main/LICENSE) and [Jmica conversion notices/model files](https://huggingface.co/Jmica/Drama-3-GGUF). Acquire the selected GGUF yourself only if your use is permitted. This software neither accepts an agreement nor grants model rights. Model licenses are separate from the Apache UI license and do not grant unrestricted commercial use. See LICENSES.md for revenue, hosting, attribution and voice-consent restrictions. Only use voice references you have the necessary rights and consent to use.

Tested file: `drama-3-backbone-8bit-experts-Q4_K_S.gguf`, Jmica revision `17a5b40c5dc2c2be986f5371a7e650108b828e29`, SHA-256 `05af716baf78e7c20863b9ccebb3ebdeca9607dd3ea7d0b72c35079e675b212b`. Keep its model LICENSE/NOTICE with your model. Do not download every quantization in the repository. This installer has no Drama download option.

## 3. Install with an existing trusted engine

Replace these example paths with your own. `-ModelLicenseReviewed` acknowledges your independent review; it is not agreement acceptance. `-WithDictation` is optional and explicitly installs/downloads MIT-licensed tiny.en and its dependencies.

```powershell
.\install-windows.ps1 -EngineExe 'D:\audio.cpp\build\windows-cuda-release\bin\audiocpp_server.exe' -Model 'D:\models\drama-3-backbone-8bit-experts-Q4_K_S.gguf' -CudaRoot 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9' -ModelLicenseReviewed -WithDictation
```

The script builds the frontend, creates an isolated optional `.venv`, verifies/resumes the four pinned STT downloads, copies and hashes only the selected engine executable, and writes private local settings. It leaves the selected Drama model and original installation in place. It refuses to overwrite an already configured installation. It does not start inference, request microphone permission or record audio.

If Windows blocks a downloaded script, review the source and use your normal approved PowerShell script-running procedure. No execution-policy change is required or performed by the installer.

## Build an engine when no compatible executable exists

Obtain the pinned upstream Apache engine source in a separate directory (Git is needed here):

```powershell
git clone --no-checkout https://github.com/0xShug0/audio.cpp.git D:\audio.cpp
git -C D:\audio.cpp checkout --detach 18bba55495c8991bbbfe7625234d4d8dbc6e82f4
```

Then, from this UI source directory:

```powershell
.\install-windows.ps1 -BuildEngine -EngineSource 'D:\audio.cpp' -Model 'D:\models\drama-3-backbone-8bit-experts-Q4_K_S.gguf' -CudaRoot 'C:\Program Files\NVIDIA GPU Computing Toolkit\CUDA\v12.9' -ModelLicenseReviewed -WithDictation
```

This calls the upstream `scripts/build_windows.ps1` for `fish_drama3` and `audiocpp_server`. Optional external server frontend adapters are not needed. The bundled UI does not modify engine source. A complete clean Visual Studio/CUDA build has not been validated in this project; tested inference uses an existing build from this revision. Build errors are shown and stop installation. Original folders are never deleted.

## 4. Start and stop

Double-click `launch-standalone.cmd`. Open **http://127.0.0.1:8046/**. Keep the launcher window open; Ctrl+C stops its owned UI and engine. Windows process ownership also releases the children if the supervisor exits abruptly. The launcher refuses to duplicate a running native engine or take over an occupied UI port. It never stops another application. To choose another UI port, use `.venv\Scripts\python.exe standalone.py --ui-port 8047 --open` (or `python` without optional STT).

Use `python standalone.py --verify-only` for a temporary-port health/ownership check without loading GPU weights. Actual generation loads the model and can take substantially longer on first use.

Dictation starts only when you press Dictate and grant browser permission. It processes four-second chunks with pauses during transcription, not continuous streaming recognition. English tiny.en can make errors. Stop releases capture; navigation/hidden-page handling discards stale results. No cloud AI or paid service is used. Avoid exposing the loopback service through tunnels/proxies.

## Output folder and Save as (Windows)

Beside Generate, press **Choose folder…** once and select an existing folder in the Windows dialog. The app remembers this choice in its local database across browser/server restarts and ports. Future completed takes are automatically saved there even if you close the browser tab. Every take also keeps its internal history copy. Existing takes are not retroactively exported. Change folder or Turn off is in the same compact control; turning off never deletes files.

Playback and each completed history take offer **Save as…**, opening a native file dialog directly. This saves one WAV without changing the automatic folder. Opening a native picker stops dictation capture and flushes its final segment so the microphone does not keep recording behind the dialog. Download WAV remains as a separate browser-managed fallback. Windows Python must include Tkinter and have an interactive desktop; the standard tested Python 3.10 installation includes it. Other platforms keep browser downloads but do not provide this native-picker workflow.

Only user-selected destinations are accepted; web requests cannot submit arbitrary paths. Selection/export endpoints require the same loopback Origin and a per-service token. Choosing a folder authorizes future new-take exports there; Turn off forgets that authorization in the app without changing operating-system permissions. Restoring a backup may restore a prior explicit choice; review the folder summary before generating. A replaced/moved folder requires selection again.

Windows WAV staging, publication and retry matching are bound to verified directory/file handles. The directory is held against rename, staging stays exclusively open, and reparse points are rejected at the native boundary. WAVs are flushed before exclusive atomic publication; no potentially substituted path is used for staging, rename or cleanup. Automatic filename collisions receive a numbered suffix; Save as refuses an existing filename instead of overwriting it. Filenames use time/take ID rather than private prompt text. Missing/full/read-only disks produce an actionable error on the take; audio remains in history. Reconnect/reselect and press Retry folder save, which uses the currently selected folder. Restart never performs a bulk retry: an interrupted external save stays visible for explicit retry. If a complete file was published before interruption, retry recognizes its exact bytes and avoids creating a duplicate. Sudden power/process loss may leave a hidden `.localvoice-*.partial` staging file in the output folder; it is not a completed WAV and can be removed manually after the app is stopped. Trash and backup cleanup affect internal storage, not exported WAVs.

## Data, upgrades and rollback

Private data is in `data/studio.sqlite3` with snapshots in `data/backups`; `.native`, `.runtime`, `.venv`, models and `standalone.local.json` are local too. Protect these folders as private. Storage/Trash controls show usage; emptying Trash creates a backup that still contains deleted content. Nothing silently prunes backups.

Use the app's Backup control before an upgrade. Preserve reference text that has not been submitted as a voice. Stop the old launcher, extract the new version into a separate folder, install/configure it, then copy the **complete stopped** `data` directory to the new folder before first normal launch. Keep the old folder/data intact for rollback. Do not run two servers against one data directory or copy a live SQLite database. Optional dictation files may be copied to the new `models/whisper-tiny.en` directory; setup verifies all four hashes before reuse. Never copy another user's configuration or data.

For backup restoration, stop the server and run `python restore.py --data data --backup <snapshot-filename>`; the snapshot must be inside `data/backups`. Restoration preserves a recovery snapshot first. To undo an upgrade, stop the new launcher and start the old folder; do not mix schema versions. The existing Pinokio/original installation was not replaced. Only return to its original launcher after stopping this standalone engine to avoid duplicate model allocation.

## Troubleshooting and verified limits

- “Another native speech engine” / occupied port: finish and close the existing engine yourself, or select a free UI port. No process is killed automatically.
- Missing CUDA/MSVC DLL: install the reputable official runtime/toolkit appropriate for your engine build; do not download individual DLLs from unknown sites.
- Dictation not installed: run setup with `--with-stt` in a stopped/new installation. Models load only from complete local directories (`local_files_only=True`).
- Dictation errors: preserve text, stop browser microphone capture if stuck, and reload the current UI. This release fixes native browser timer receiver errors (“Illegal invocation”) and prevents late results crossing edited voice presets.
- Source and synthetic regression tests passed, including offline Harper/Whisper, codec decoding, persistence, cancellation and owned process cleanup. GoodBox completed actual standalone synthetic generation and local transcription; the owner confirmed the working UI. See VALIDATION.md. There is no quality/speed promise for other hardware, noisy microphones, languages or experimental multi-speaker conditioning.

Source publication includes no weights, voices, transcripts, history, credentials, executable bundles, Python wheels or FFmpeg binaries. Dependencies are installed from their public registries with lockfiles and separate license notices.
