# ag-trace

Capture a Google Antigravity conversation as **lossless, hashed evidence** for
agent evals: which tools and skills the agent used, in what order, with what
arguments, per user turn.

`ag-trace` copies what Antigravity recorded **exactly as it was read**, records a
SHA-256 for every file in a manifest, cross-checks the step count against an
independent record, and derives readable views. It fails loudly: a capture that
cannot be shown to be complete is flagged, and a failed read writes nothing.

## Two sources

| Source | Needs Antigravity running? | What it reads |
|---|---|---|
| `transcript` (default) | **No** — works for past conversations | `~/.gemini/antigravity/brain/<id>/.system_generated/logs/transcript_full.jsonl`, the large-output files beside it, and `conversations/<id>.db` (+ `-wal`, `-shm`) |
| `api` | Yes | The local LanguageServer API (undocumented) |

### What the transcript source has to work around

Observed on Antigravity for Windows, 2026-09-25, across 54 stored conversations:

- **`transcript.jsonl` truncates** step content at ~4 KB. `transcript_full.jsonl` is
  used. Older conversations have only the truncated file; capturing one needs
  `--allow-truncated` and is marked `TRUNCATED`.
- **Lines are in completion order, not step order.** A response that requested
  tool calls can be written after the results. Derived views sort by
  `step_index`; the evidence is kept as written.
- **A step that did not finish can be missing from the transcript.** In one
  conversation the `.db` held 87 steps and the transcript 86; the absent step was
  a command result with a non-DONE status. `ag-trace` compares the two and lists
  absent steps with their `.db` type and status.
- **Argument values are sometimes JSON-encoded strings**, sometimes plain. Only
  values that are themselves JSON string literals are decoded.
- **MCP calls go through `call_mcp_tool`** with `ServerName` and `ToolName`
  arguments; they are reported as `mcp:<server>/<tool>`.
- **A step that did not finish has readable error text in the `.db`**, e.g.
  *"user denied permission to run command"*; it is shown with the absent step.
- **No call-to-result id.** Calls are what the model *requested*; results are
  separate steps. `ag-trace` does not claim a pairing.

## Skills

Antigravity records no separate "skill used" event. Its own prompt, stored in the
`.db`, defines use: the model *"MUST read its SKILL.md instructions using
`view_file`"* at *"the exact path provided in the Available skills list"*. So:

- **Offered** — the "Available skills" list in the stored prompt (the most recent
  generation that carries one).
- **Read** — a `view_file` call on one of those paths (slash style and case ignored).
- **Other SKILL.md reads** — `SKILL.md` files read that were not on the list.

*Read* means the instructions were opened, not that they were followed. If the list
is not in the `.db`, skills are reported as unknown rather than guessed.

## Requirements

- Python 3.9+ (standard library only; no runtime dependencies)
- Windows for `--source api`; the transcript source reads files and runs anywhere
  the Antigravity data directory is reachable

## Install

```powershell
git clone <this repo> ag-trace
cd ag-trace
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # venv, editable install, tests
.\.venv\Scripts\Activate.ps1
```

## Use

```powershell
ag-trace list -n 10                                   # newest first, with call counts
ag-trace capture latest --label TR-P055-012-step-3    # or a cascade id
ag-trace verify captures\<cascade_id>\<timestamp>     # evidence still matches manifest?
ag-trace derive captures\<cascade_id>\<timestamp>     # verify, then regenerate derived/
```

Options: `--source api`, `--ag-home DIR` (or `$env:AG_HOME`), `--out DIR`
(or `$env:AG_TRACE_OUT`; default `.\captures`), `--allow-truncated`.

### A capture

```
captures\<cascade_id>\<local timestamp>\
    manifest.json          tool version, source hash and git state; host; completeness;
                           cross-check; SHA-256 and size of every evidence file
    evidence\              exactly as read, never modified
        transcript_full.jsonl
        steps\<n>\output.txt
        db\<id>.db, .db-wal, .db-shm
    derived\               regenerable with `derive`
        steps.jsonl        every step, in step order, with user turn
        calls.jsonl        every requested tool call: turn, step, tool, server, args
        skills.json        skills offered, SKILL.md files read (turn, step)
        summary.md         completeness, skills, calls per turn, MCP calls by server
```

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Captured, `COMPLETE` |
| 2 | Failed; **nothing written**. Or `verify`/`derive` found evidence that no longer matches its manifest |
| 3 | Written but **not demonstrably complete**: `SHORT`, `TRUNCATED`, `UNVERIFIED` (no `.db`), `INVALID`. Don't cite as complete |

## Limits

- **Everything read here is undocumented** and can change with any Antigravity
  update. The derived census shows new step types; the tests encode the formats
  observed so far.
- The `.db` stores steps as protobuf, which is not decoded. ag-trace reads step
  index, type and status by SQL, and error text and the skills list as readable text
  inside blobs. It is opened only from a temporary copy of the captured bytes.
- A `.db` copied while Antigravity is still writing to that conversation may be
  mid-update; capture after the conversation has finished.
- The `api` source has not yet been exercised against a live LanguageServer.
- **Captures can contain private content** (prompts, file contents, command
  output). `captures/` is git-ignored; keep it that way.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
```

The tests are built around broken input: missing, truncated, malformed and
out-of-order transcripts, steps absent from the transcript, altered and planted
evidence files, and a live database that must not be touched.

## Licence and attribution

Apache-2.0. The LanguageServer approach in `live.py` is derived from
[antigravity-history](https://github.com/neo1027144-creator/antigravity-history)
@ `4046f8f7e808be28b8d5b8cc57bf2ec39d2cc9bd`; see [NOTICE](NOTICE).
