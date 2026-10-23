# License and publication notes

This document separates code, model, and binary dependency licenses. It is not a legal clearance for model-enabled distribution.

| Component | Observed license / source | Distribution treatment |
|---|---|---|
| audio.cpp snapshot `18bba55495c8991bbbfe7625234d4d8dbc6e82f4` | Apache-2.0; original repository LICENSE begins Copyright 2026 ShugoAI LLC | Apache LICENSE/NOTICE retained; engine/vendor source is not bundled in the standalone UI archive |
| New Local Voice Studio source | Apache-2.0 under repository LICENSE | Source files are at this repository/archive root; preserve LICENSE and NOTICE |
| Harper / harper.js 2.13.0 | Apache-2.0, Automattic/harper | Bundled in frontend as local JS/WASM; preserve package LICENSE when distributing built assets |
| Vite 7.1.3 and build tooling | MIT plus transitive licenses | Build dependencies installed from npm lockfile, not shipped as node_modules |
| Whisper tiny.en converted by Systran | MIT, official [model card](https://huggingface.co/Systran/faster-whisper-tiny.en) and [Whisper source](https://github.com/openai/whisper) | Downloaded separately by explicit optional setup; no weights in source release |
| faster-whisper 1.2.1 / CTranslate2 4.8.3 | MIT | Installed from official PyPI packages into `.venv`; do not bundle the environment |
| PyAV 17.1.0 | BSD-3-Clause | Its license does not cover every library in its wheel |
| FFmpeg in tested Windows PyAV wheel | `avutil_license()` reports **LGPL version 3 or later**; libavutil 60.26.101, libavcodec 62.28.101 | Do not redistribute wheels/DLLs as part of a binary app without corresponding license/source/compliance review |
| Drama 3 / Jmica GGUF conversion | Fish Audio Community License v1.0, updated 2026-10-13; Jmica NOTICE covers conversion | No weights included or redistributed; keep model LICENSE/NOTICE beside downloaded files |

`dependency-licenses-win-py310.json` records installed Python package metadata. `requirements-stt-lock-win-py310.txt` records the tested versions. Metadata alone is not a complete binary-license audit. Different platforms and future dependency updates can have different binary builds and obligations.

The installed Drama model is **not Apache/MIT**. The license includes limited commercial rights only below the stated US$500,000 aggregate trailing-year revenue threshold, separate hosted-service restrictions, required “Built with Fish Audio” attribution, identifiable-voice consent restrictions, and other use restrictions. Do not state unrestricted commercial rights. Its hosted-service definition includes SDKs/applications/features primarily handling user-supplied TTS/voice cloning, so local wrapper distribution is a review question rather than an assumed exemption. The initial public package is independently written UI/server source with bring-your-own-model instructions: no Fish code, weights or derivatives are redistributed, no automatic Drama downloader is supplied, and the publisher operates no inference service. A future model-enabled binary/service package would require its own license review. No outreach or legal agreement acceptance has occurred.

No Fish Audio logo is used. Local Voice Studio is an independent product name; Drama 3 appears only as factual model identification. The UI and documentation retain the required attribution. This source change does not modify trained model weights.

For a built-asset distribution, preserve all upstream notices and copy relevant dependency license texts into the distributable. Source-only releases should use the lockfiles and installer rather than shipping `.venv`, downloaded models, FFmpeg DLLs, or npm dependencies. Preserve the accompanying Apache LICENSE/NOTICE. This source-only release does not bundle engine binaries, Python wheels, native codecs, npm dependencies or model weights.
