# Changelog

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
