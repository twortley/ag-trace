# ag-trace

Capture a Google Antigravity conversation as **lossless, hashed evidence** for
agent evals: which tools were called, in what order, with what arguments and
outcome.

Antigravity keeps each conversation's full trajectory behind a local, undocumented
LanguageServer API. `ag-trace` saves that response **exactly as received**,
records its SHA-256 in a manifest, and derives one row per step for analysis.

It exists because a general-purpose exporter is the wrong shape for evidence:
exporters render the steps they recognise and drop the rest, flatten tool
arguments, and treat a failed fetch as an empty conversation. `ag-trace` keeps
every step, keeps the raw response, and fails loudly.

## Requirements

- Windows, with Antigravity running and a workspace open
- Python 3.9+ (standard library only; no runtime dependencies)

## Install

```powershell
git clone <this repo> ag-trace
cd ag-trace
powershell -ExecutionPolicy Bypass -File .\setup.ps1   # venv, editable install, tests
.\.venv\Scripts\Activate.ps1
```

## Use

```powershell
ag-trace list -n 10                                  # newest conversations first
ag-trace capture latest --label TR-P055-012-step-3   # or a cascade id
ag-trace derive captures\<cascade_id>\<timestamp>    # regenerate derived files offline
```

Captures go to `.\captures` by default, or `--out DIR`, or `$env:AG_TRACE_OUT`.

### What a capture contains

`captures\<cascade_id>\<local timestamp>\`

| File | |
|---|---|
| `raw.json` | **The evidence.** Response bytes exactly as received |
| `manifest.json` | SHA-256 of `raw.json`; tool version, source hash and `git describe`; capture time, host, Python; LanguageServer exe path; steps expected vs received; completeness |
| `steps.jsonl` | Derived. One row per step: index, type, status, time, model, label, payload with long strings replaced by length + hash |
| `steps.md` | Derived. Step-type census and a table |

### Exit codes

| Code | Meaning |
|---|---|
| 0 | Captured, complete |
| 2 | Failed; **nothing written** (API error, zero steps, malformed response, tampered raw on `derive`) |
| 3 | Written but **SHORT**: fewer steps than the index reports. Don't cite as complete |

## Limits

- **Undocumented API.** An Antigravity update can change it. The manifest records
  the LanguageServer build; the census in `steps.md` shows new or renamed step
  types when that happens.
- **Windows only** for discovery.
- The CSRF token is used for the request and never written to disk.
- **Captures can contain private content** (prompts, file contents, command
  output). `captures/` is git-ignored; keep it that way.

## Development

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\ruff.exe check src tests
```

## Licence and attribution

Apache-2.0. The approach to LanguageServer discovery is derived from
[antigravity-history](https://github.com/neo1027144-creator/antigravity-history)
@ `4046f8f7e808be28b8d5b8cc57bf2ec39d2cc9bd`; see [NOTICE](NOTICE).
