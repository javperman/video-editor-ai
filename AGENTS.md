# Instructions for coding agents

## Mission

Build a reliable automatic editing pipeline for technical tutorials: screen,
webcam/mobile and voice inputs; deterministic edit plans; reproducible renders;
QC that fails closed.

## Source of truth

1. `edit_plan.json`, validated against `schemas/edit-plan.schema.json`.
2. A project is rebuilt from the plan, never edited backwards.
3. Every natural-language instruction produces a new immutable revision.

## Hard rules

- Never modify the original media. Verify SHA-256 before and after.
- Do not upload full video to external services without explicit approval.
- Do not use models that train on the data for real material.
- Do not expose the MCP server outside `127.0.0.1`.
- Do not install global dependencies when an isolated environment exists.
- Do not call a test passed if it only starts the app: it must import, edit,
  save, reopen and render.
- Document every limitation and every test that was not run.
- Do not commit secrets, credentials, tokens, private keys or `.env` files.

## Honesty about capabilities

Before applying an edit, check whether it exists in the deterministic catalogue
(`src/video_ai/commands.py` for phrases; `schemas/edit-plan.schema.json` for
operations).

- If it is not available, say so explicitly. Do not simulate it and do not claim
  it was done.
- Then propose alternatives: approximate with an existing operation, implement
  the missing operation (and say it is a code change), or ask for approval if it
  changes meaning or personal data.
- Never claim a render, integration or test works if it was not executed.
- "It cannot be done" is a valid and expected answer.

## OpenChatCut traps

- Offline MCP sessions must be confirmed or discarded in the same process. If the
  transport dies, the project remains locked as "active browser or offline editor".
- `import_assets` requires absolute paths.
- The packaged MCP does not expose render/export; use the internal `POST /export`
  route or the source CLI.
- Set worker and RAM limits explicitly; defaults are too aggressive for 16 GB.
- `transform` in OpenChatCut is `translate(x%,y%) scale()` with the origin at the
  center. It is not normalized. Verify the conversion by rendering.
- The OpenChatCut export uses WebCodecs (software) and is roughly 2× real time.
  Use `src/video_ai/render.py` with `h264_nvenc` for the final encode.
- PiP is applied by the local FFmpeg renderer from the plan's normalized
  transform, not by OpenChatCut's transform.

## Analysis traps

- Scene detection (`scdet`) is unreliable for soft UI changes; periodic sampling
  is better for screen content.
- The cursor is not reliably detected after the fact; record it during capture.
- OCR must run locally. `rapidocr-onnxruntime` installs in `.venv`; `tesseract`
  is optional.
- CUDA with ctranslate2 needs `libcublas.so.12` and cuDNN; load them from pip
  wheels with `ctypes`, without `sudo` or a global `LD_LIBRARY_PATH`.
- Load the Whisper model once per (model, device, compute); do not reload it per
  call.
- Filler-word cuts are `human_review`. A cut that removes words from the
  transcript may be proposed as `pending`, but only applies with
  `approval: approved`.
- `atrim` uses seconds (`start`/`end`); `trim` accepts `start_frame`. Do not mix
  conventions.
- Tolerate sources without audio; do not map `[aout]` if the source has no audio
  track.
- Clap-based sync is unreliable across microphones with different gain; use
  correlation (`find_offset`) as the primary method.
- `transform` in the plan is normalized: `x`/`y` are the top-left corner
  (0..1), `scale` is a fraction of canvas width; height follows the aspect ratio.
- All frame numbers in the plan use the base screen fps. Normalize other sources:
  `duration_frames = round(duration_seconds * fps_base)`.
- Align webcam/mobile to screen with a time-aligned copy; `source_in` alone is
  not enough because cuts are applied in screen time.
- Audio codec must match the container: AAC inside `.wav` produces a broken file.
- Subtitles are burned with an ASS file at the real output resolution. Do not
  use `force_style` with a fixed `FontSize`.
- The plan's `transform` is normalized, but OpenChatCut's is not; always verify a
  conversion by rendering.

## Natural-language editing

- The parser is deterministic; it does not use an LLM. An instruction that does
  not match a known pattern is rejected instead of invented.
- A valid instruction creates a new immutable revision; never edit the previous
  plan in place.
- Approving a meaning-changing cut is mandatory before it is applied.
- After changing cuts, recalculate subtitles: they live in timeline frames.
- Unsupported operations must be rejected with a clear message.

## Maintenance

At the end of every iteration:

1. Update `README.md` if the system state changed.
2. Update the relevant ADR or benchmark note if a decision or measurement changed.
3. Record what was tested, the commands, the results and the limitations.
4. Commit only when the tree is clean and the tests/render evidence is attached.
