# Changelog

## 1.0.0 — 2026-09-26

First public release.

- **The manifest names the tool `ag-trace`.** It carried an internal registry id,
  written into every capture. Captures made by 0.4.0 still verify: `verify` checks
  the evidence against the manifest, not the tool's name.
- **`--host-label`** (or `$AG_TRACE_HOST`) records a name of your choosing as the
  capture's host instead of the machine name. Captures get attached to shared
  records; a hostname is yours to disclose. The default is unchanged.
- **CI:** the offline suite on Ubuntu and Windows, Python 3.9 and 3.13; ruff; an
  encoding check; a tag-triggered release that refuses a tag disagreeing with
  `__version__`, and attaches the wheel and sdist.
- README: install from the repository URL or with `pip`, on Windows or elsewhere.
- Used for the end-to-end verification of
  [ollama-delegate](https://github.com/twortley/ollama-delegate) `v1.0.0`, where
  captures decided three acceptance criteria that screenshots could not.

## 0.4.0 — 2026-09-25

- `capture` also writes `<cascade_id>-<timestamp>-<hash>.zip` beside the capture
  folder and prints it as `attach`: the one file to attach to a test record. The name
  carries the first 16 hex digits of the zip's SHA-256.
- `verify` accepts a zip: checks the name against the bytes, rejects entries outside
  the capture folder, then verifies the manifest inside.
- New `pack` command zips an existing capture folder. Zips are deterministic.
- `--no-zip` skips the zip.

## 0.3.0 — 2026-09-25

- **Skills.** The skills offered to the model are read from the "Available skills" list
  in the prompt stored in the conversation `.db`. A skill counts as used when a
  `view_file` call reads its `SKILL.md` at that path (Antigravity's own definition).
  New `derived/skills.json`; `summary.md` has a skills table; `capture` prints skills read.
  Other `SKILL.md` reads are listed separately. Unknown is reported as unknown.
- **The conversation `.db` (+ `-wal`, `-shm`) is now captured as evidence**, so the
  completeness cross-check and skills can be recomputed from the capture alone.
- Steps absent from the transcript carry the readable text of their `.db` error, e.g.
  "user denied permission to run command".

## 0.2.2 — 2026-09-25

- `capture` prints tool calls and MCP calls by server for each user turn, and the path
  to `summary.md`. It previously printed only a step-type census, which names no
  tools and made a capture with 4 ollama-delegate calls look as if it had none.

## 0.2.1 — 2026-09-25

- `list` includes conversations that only have the truncated `transcript.jsonl`,
  marked `TRUNC`, with a full/truncated count in the header. Previously they were
  left out without notice (found on first Windows run: 11 listed of 54 stored).

## 0.2.0 — 2026-09-25

- **New default source: `transcript`.** Reads Antigravity's on-disk
  `transcript_full.jsonl` and large-output files; no running Antigravity needed, so
  past conversations can be captured.
- Step count cross-checked against `conversations/<id>.db` (read from a copy). Steps
  present in the `.db` but absent from the transcript are listed with type and status.
- Derived views sorted by `step_index` (transcripts are written in completion order);
  each step carries its user turn.
- `calls.jsonl`: one row per requested tool call; `call_mcp_tool` resolved to
  `mcp:<server>/<tool>`; JSON-encoded argument values decoded.
- `summary.md`: completeness, tool calls per user turn, MCP calls by server.
- Evidence and derived files separated (`evidence/`, `derived/`); manifest lists a
  hash for every evidence file. New `verify` command; `derive` verifies first and
  also rejects unlisted files.
- `--allow-truncated` for conversations that only have `transcript.jsonl`.
- Code split into `evidence`, `transcript`, `live`, `derive`, `cli`.

## 0.1.0 — 2026-09-25

- First version. `list`, `capture`, `derive`.
- Raw LanguageServer response saved unmodified with a SHA-256 manifest.
- Every step becomes a derived row, known type or not.
- Fails loudly: API error or zero steps exits 2 and writes nothing; a short
  capture is written and exits 3.
- Manifest records the package source hash and `git describe` of the tool.
