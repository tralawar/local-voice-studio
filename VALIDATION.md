# Output-folder review corrections

The independent reviewer reproduced a trailing-slash authorization bypass and a directory-substitution race in candidate 0dbc1836. Both are corrected before deployment/public promotion. Routes are normalized once and output authorization is enforced at the actual choose/clear/save-as/export dispatch. Slash variants cannot invoke a picker or export without both the exact Origin and action token.

Windows output IO now opens and verifies the selected directory object, holds it without share-delete, and uses NtCreateFile with that directory handle for a single staging leaf. The staging file remains exclusively held through flush and NtSetInformationFile publication with no replacement, relative to the same directory handle. Cleanup deletes the held staging object, never a potentially substituted pathname. Retry matching also reads by directory/file handles. OPEN_REPARSE_POINT plus explicit reparse-attribute rejection prevent junction/symlink traversal at the opened boundary; handle identity must equal the selected device/file ID. There is no path-based write fallback on other platforms.

The full corrected suite passes 54 tests (33 Python, 20 JavaScript and one offline Harper). The frontend was rebuilt and its JS/CSS bytes exactly match candidate 0dbc1836. Four targeted regressions pass on real Windows filesystem objects: unauthenticated slash variants, directory/staging substitution at publication, replacement between the preliminary path check and directory-handle open, and a real temporary junction after the preliminary path check. The directory move, staging unlink and staging replacement are denied while handles are held; the authorized audio alone is published. Junction fixture cleanup removes only the temporary junction, not its target tree. All tests use synthetic temporary directories.

# Output-folder addition — 0.1.1

A native Windows folder picker stores an explicit directory selection in SQLite metadata. Generation completion persists internal WAV/history before attempting external export; a separate failure cannot mark generation failed. Per-take Save as uses a native file picker without changing the automatic folder. External exports use exclusive atomic publication, collision-safe names, flush-before-publish, partial cleanup on ordinary failures and exact-byte recovery on explicit retry after interrupted publication. Startup never bulk-exports old takes. Client-supplied paths, missing action token, foreign Origin and alias routes are rejected. Folder identity changes require re-selection.

New isolated tests cover selection/cancel/restart persistence, no retroactive export, normal automatic generation, concurrent filename collisions, idempotent retry, missing/replaced/read-only/full destinations, atomic staging cleanup, generation cancellation/failure, native Save as cancellation/collision and selected filename, status updates not resurrecting trashed history, and HTTP path/token/origin boundaries. Frontend tests cover picker serialization, cancel state, busy cleanup after failure and export status messages. No real user folders or microphone were used. Tkinter 8.6 is available on the tested Windows Python. Actual user-driven native folder/file selection remains a manual check; automated tests inject isolated picker results rather than approving a user filesystem destination.

The full suite passed: 29 Python tests, 20 JavaScript lifecycle/editor/output tests and one offline Harper test (50 total). Production build passed. Disposable native Chrome profiles rendered and checked exact 1360/900/390 CSS viewports with no horizontal overflow. Synthetic history showed Save as and Retry controls, and a real page/API Save as flow with an injected temporary-directory picker preserved both unsubmitted text fields and released busy controls. These checks used a synthetic backend, not the owner's profile, voices, microphone or active generation.

The prior working UI/live backend is unchanged during development. The new backend and assets require a coordinated restart/deployment after independent review; they have not been applied to the user's live session.

# Validation record — 2026-10-22

## Release scope

The public package contains independently written UI/server source, tests and original installation instructions. It does not contain engine source/binaries, model weights, private voice references, prompts, history, credentials, downloaded dependencies or FFmpeg binaries. Drama models are bring-your-own under their separate license. Optional MIT Whisper files are downloaded explicitly by setup, with pinned revision and hashes. Apache UI source and model licensing are separate.

## Working implementation and review

The standalone UI/native engine ran without Pinokio on Windows/NVIDIA RTX 4090 24 GB. An actual synthetic sentence produced a 2.322-second, 44.1 kHz WAV in 22.64 seconds on a cold standalone request. Local Whisper transcribed that sentence in 2.719 seconds. Earlier warmed default-voice generation was faster; saved-reference generation took up to 50.12 seconds. These fixture measurements are not hardware-independent speed or quality promises. The owner confirmed the UI and dictation work.

Independent code review verified draft acknowledgments, generation cancellation serialization, stale dictation invalidation when editing presets, Windows child ownership and port collision handling. The final browser timer fix was reviewed with 28 tests passing. Subsequent installer download regressions increase the suite to 33 tests (15 Python, 17 JavaScript lifecycle/editor tests and one offline Harper test).

## Browser capture regression

An isolated native Chrome profile with generated Web Audio, real MediaRecorder and native window timers reproduced “Illegal invocation.” Unbound native timers had been invoked with a DictationSession receiver. The corrected arrow wrappers retain the Window receiver; cleanup releases all microphone tracks even if recorder/timer cleanup fails. Native test output confirmed started=true, stopReturned=true, trackReleased=true, sessionReleased=true and recording=false, with no real microphone accessed. The reviewer separately passed mocked receiver/cleanup regressions; its native Chrome attempt timed out and is not counted as a successful native result.

## Persistence and offline checks

Temporary-database and HTTP tests exercise voice CRUD, import validation/atomicity, history generation, cancellation, restore/delete/backup, restart persistence and draft conflicts. Frontend tests exercise tab retention, acknowledgment tracking and late-result suppression. Host/Origin, traversal and input-limit checks pass. Windows synthetic supervisor abrupt-exit and occupied-port tests pass without targeting other applications.

Harper runs local WASM with fetch blocked except the inline WASM data URL. Whisper runs against the explicit complete tiny.en directory with Python socket connections disabled. Synthetic WAV, WebM/Opus and MP4/AAC decode/transcription tests passed. Dictation uses independent four-second chunks and pauses while transcribing; it is not true streaming ASR. No agent requested real microphone permission or captured live microphone audio.

## Installer and limits

The dependency setup was previously exercised in a fresh source-only directory, including frontend build, isolated Python 3.10 environment and checksum reuse of all four tiny.en files. The official Systran download completed earlier: 78,090,594 bytes at revision 0d3d19a32d3338f10357c0889762bd8d64bbdeba. New regressions verify no-network reuse, interrupted-download resumption and rejection of a corrupt download before promotion. The new PowerShell one-command installer passed in a fresh source-only directory using Python 3.10 and Node 24.18.0. It rebuilt the exact reviewed frontend bundle, installed all locked optional STT dependencies, reused the four existing STT files by checksum, copied only the verified engine executable and referenced the Drama model in place. A second installer invocation refused to overwrite configuration. Temporary-port standalone verification returned healthy UI/engine and STT ready with zero loaded GPU models, then released its owned children. The pre-existing live engine remained running. Fresh-environment Whisper with sockets blocked transcribed synthetic audio in 5.5 seconds cold and 0.375 seconds warm. Initial sandbox-only registry/process access restrictions required the normal approved execution context; no system npm settings or live application were changed.

Clean Visual Studio/CUDA provisioning and a full clean native engine build have not been validated here. Actual inference reuses a trusted existing upstream engine. A new 24.6 GB Drama model was not downloaded. Other GPU profiles, platforms, languages, noisy-device quality and experimental multi-speaker conditioning are not validated. Python dependency locks describe the tested Windows/Python 3.10 build; the generic fallback on other Python/platform combinations is less reproducible.

PyAV metadata is BSD-3-Clause; the tested bundled FFmpeg reports LGPL version 3 or later. No wheels, DLLs or environment are redistributed. A future binary bundle needs its own corresponding-source/license audit.

The legacy browser batch-import upload remains approval-pending and was never repeated; temporary-database migration/rollback tests passed independently. Final responsive viewport screenshots could not be completed through the unavailable browser transport. The release does not claim those manual checks passed.

## Data and rollback

Original installation/configuration/models/browser storage were preserved. The live standalone UI received only the reviewed frontend asset fix; its services, engine and database remained running. Release/setup work uses isolated folders and never reloads the owner’s page. Private runtime records, snapshots and fixture audio are excluded from the release. Read RELEASE.md before updating or restoring data.
