# Third-party components

This repository contains the pipeline code and test fixtures. It does not bundle
OpenChatCut, FFmpeg, Remotion, model weights or recorded media.

| Component | Role | License | Distribution |
|---|---|---|---|
| [OpenChatCut](https://github.com/0xsline/OpenChatCut) | Optional interactive editor + MCP | AGPL-3.0 | Installed separately as an AppImage/source; not bundled |
| [FFmpeg](https://ffmpeg.org/) | Decode/encode, filters, NVENC | LGPL/GPL depending on build | External binary; not bundled |
| [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | Local ASR | MIT | Optional Python dependency |
| [Whisper large-v3-turbo](https://huggingface.co/mobiuslabsgmbh/faster-whisper-large-v3-turbo) | ASR model | MIT (model card) | Downloaded/cached locally; not bundled |
| [rapidocr-onnxruntime](https://github.com/RapidAI/RapidOCR) | Local OCR | Apache-2.0 | Optional Python dependency |
| [Remotion](https://www.remotion.dev/license) | Motion graphics (not included) | Remotion License (free/company tiers) | Not bundled; the example project was removed |
| [jsonschema](https://github.com/python-jsonschema/jsonschema) | Plan validation | MIT | Python dependency |
| [PyYAML](https://pyyaml.org/) | Config parsing | MIT | Python dependency |
| [jsonpatch](https://github.com/stefankoegl/python-json-patch) | Immutable revisions | BSD-3-Clause | Python dependency |

## Notes

- OpenChatCut is AGPL-3.0. It is invoked as an external local service; this
  repository does not include its source or AppImage.
- FFmpeg is invoked as an external binary. Its license depends on how it was
  built; the user is responsible for the build they install.
- Remotion was used for a separate motion-graphics project that is not part of
  this repository. If you add Remotion compositions, review its license terms.
- No third-party model weights or media are distributed here.

This is an engineering inventory, not legal advice.
