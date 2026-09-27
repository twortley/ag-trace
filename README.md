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
| `api` | Yes | The local LanguageServer API (undocumented). **Experimental** — tested against a faked server only |

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

**As a tool** (any platform with Python 3.9+):

```
pip install git+https://github.com/twortley/ag-trace@v1.0.0
ag-trace --version
```

**From a clone, with the tests — Windows (PowerShell):**

```powershell
git clone https://github.com/twortley/ag-trace.git
cd ag-trace
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # venv, editable install, tests
.\.venv\Scripts\Activate.ps1
```

**macOS and Linux (bash):**

```bash
git clone https://github.com/twortley/ag-trace.git
cd ag-trace
python3 -m venv .venv && .venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest -q
```

## Use

```powershell
ag-trace list -n 10                                   # newest first, with call counts
ag-trace capture latest --label "run 12, step 3"      # or a cascade id
ag-trace verify captures\<cascade_id>-<ts>-<hash>.zip  # or a capture folder
ag-trace pack captures\<cascade_id>\<timestamp>       # zip an existing folder
ag-trace derive captures\<cascade_id>\<timestamp>     # verify, then regenerate derived/
```

Options: `--source api`, `--ag-home DIR` (or `$env:AG_HOME`), `--out DIR`
(or `$env:AG_TRACE_OUT`; default `.\captures`), `--allow-truncated`, `--no-zip`,
`--host-label TEXT` (or `$env:AG_TRACE_HOST`).

**The manifest records the machine's hostname** as the capture's `host`, unless
`--host-label` names it otherwise. Set it before attaching captures anywhere shared.

### Attaching a capture to a test record

`capture` ends by printing `attach  captures\<cascade_id>-<timestamp>-<hash>.zip`.
**That zip is the one file to attach.** Its name carries the first 16 hex digits of
its own SHA-256, so the link in the record says which bytes it means: a re-capture of
the same conversation, a swapped file or a damaged copy cannot have the same name.
`ag-trace verify <zip>` checks the name against the bytes, then every evidence file
against the manifest inside. Nothing needs to be copied into the record by hand.

This **binds** a record to a file; it does not prove who made it. Anyone who can edit
the zip can rename it. Tamper evidence needs the hash kept somewhere the record's
store cannot change.

Zips are deterministic: packing the same capture again gives the same bytes and name.

### A capture

```
captures\<cascade_id>-<local timestamp>-<hash>.zip     the folder below, zipped
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
| 2 | Failed; **nothing written**. Or `verify`/`derive` found evidence that no longer matches its manifest, or a zip whose name does not match its bytes |
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
- The `api` source has not yet been exercised against a live LanguageServer. It
  talks only to `127.0.0.1`, bypasses any proxy, and accepts the LanguageServer's
  self-signed certificate — which is why it never connects anywhere else.
- **Captures can contain private content** (prompts, file contents, command
  output). `captures/` is git-ignored; keep it that way.

## Development

CI runs the offline suite on Ubuntu and Windows, Python 3.9 and 3.13, plus ruff and
an encoding check. **Nothing in CI runs Antigravity** — see the top of
`.github/workflows/ci.yml` for what a green run does and does not mean.

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
