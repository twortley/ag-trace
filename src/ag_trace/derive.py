"""Derived views. Everything here is regenerable from the evidence files.

Outputs, under <capture>/derived/:
    steps.jsonl   one row per step, every step, known type or not
    calls.jsonl   one row per tool call the model requested
    summary.md    step-type census, tool calls per user turn, and the step table

A call row records what the model *requested*. Neither source links a call to its
result by id, so no pairing is claimed; results are separate step rows.
"""

import json
import re
from collections import Counter, OrderedDict

from ag_trace.evidence import CaptureError, sha256
from ag_trace.transcript import parse_rows, user_request

LONG = 200  # strings longer than this are summarised in derived rows (never in evidence)
_SAVED = re.compile(r"saved to: file:///\S*?/steps/(\d+)/output\.txt")


def compact(v):
    """Keep structure and short values; replace long strings by length + hash."""
    if isinstance(v, str):
        if len(v) <= LONG:
            return v
        return f"<{len(v)} chars sha256:{sha256(v.encode())[:12]}>"
    if isinstance(v, dict):
        return {k: compact(x) for k, x in v.items()}
    if isinstance(v, list):
        if len(v) > 20:
            return [compact(x) for x in v[:20]] + [f"<+{len(v) - 20} more>"]
        return [compact(x) for x in v]
    return v


def decode_arg(v):
    """Some Antigravity versions store argument values JSON-encoded ('"C:\\\\x"'), others
    plain. Decode only a value that is itself a JSON string literal; leave the rest."""
    if isinstance(v, str) and len(v) >= 2 and v[0] == '"' and v[-1] == '"':
        try:
            out = json.loads(v)
            if isinstance(out, str):
                return out
        except ValueError:
            pass
    return v


def resolve_call(tc):
    """-> (tool, server, args). MCP calls routed through call_mcp_tool are resolved to
    mcp:<server>/<tool> so they can be counted per server."""
    name = tc.get("name") or "?"
    args = {k: decode_arg(v) for k, v in (tc.get("args") or {}).items()}
    if name == "call_mcp_tool":
        server = args.get("ServerName") or "?"
        return f"mcp:{server}/{args.get('ToolName') or '?'}", server, args
    return name, None, args


# ---------------------------------------------------------------- transcript source

def transcript_rows(rows, output_files=()):
    """Rows in step order. The file is in completion order (see transcript.py)."""
    steps, calls, turn = [], [], 0
    for r in sorted(rows, key=lambda x: x.get("step_index", -1)):
        typ = r.get("type") or ""
        if typ == "USER_INPUT":
            turn += 1
        i = r.get("step_index")
        row = {"i": i, "turn": turn, "type": typ, "status": r.get("status"),
               "source": r.get("source"), "at": r.get("created_at")}
        content = r.get("content") or ""
        if typ == "USER_INPUT":
            row["label"] = user_request(content)[:160]
        tcs = r.get("tool_calls") or []
        if tcs:
            names = []
            for j, tc in enumerate(tcs):
                tool, server, args = resolve_call(tc)
                names.append(tool)
                calls.append({"turn": turn, "step": i, "n": j, "tool": tool, "server": server,
                              "at": r.get("created_at"), "args": compact(args)})
            row["label"] = "calls: " + ", ".join(names)
        elif typ != "USER_INPUT" and content:
            lines = [ln for ln in content.splitlines()
                     if not ln.startswith(("Created At:", "Completed At:"))]
            row["label"] = (lines[0] if lines else "")[:160]
            m = _SAVED.search(content)
            if m:
                rel = f"steps/{m.group(1)}/output.txt"
                row["output_file"] = rel if rel in output_files else f"{rel} (NOT CAPTURED)"
        if r.get("thinking"):
            row["thinking"] = compact(r["thinking"])
        if content:
            row["content"] = compact(content)
        if r.get("truncated_fields"):
            row["truncated_fields"] = r["truncated_fields"]
        steps.append(row)
    return steps, calls


# ---------------------------------------------------------------- api source

def _label(payload):
    keys = ("serverName", "toolName", "name", "commandLine", "command", "absolutePathUri",
            "directoryPath", "filePath", "query", "url", "uri", "error", "message")
    if not isinstance(payload, dict):
        return ""
    return " | ".join(str(payload[k]) for k in keys
                      if isinstance(payload.get(k), (str, int)))[:160]


def api_rows(api_steps):
    steps, calls, turn = [], [], 0
    for i, s in enumerate(api_steps):
        md = s.get("metadata") or {}
        typ = (s.get("type") or "").replace("CORTEX_STEP_TYPE_", "")
        if typ == "USER_INPUT":
            turn += 1
        keys = [k for k in s if k not in ("type", "metadata", "status")]
        row = {"i": i, "turn": turn, "type": typ,
               "status": (s.get("status") or "").replace("CORTEX_STEP_STATUS_", ""),
               "at": md.get("createdAt"), "model": md.get("generatorModel"),
               "payload_keys": keys}
        if typ == "USER_INPUT":
            row["label"] = ((s.get("userInput") or {}).get("userResponse") or "")[:160]
        elif typ == "PLANNER_RESPONSE":
            pr = s.get("plannerResponse") or {}
            text = pr.get("modifiedResponse") or pr.get("response") or ""
            row["label"] = f"<response {len(text)} chars>"
            names = []
            for j, tc in enumerate(pr.get("toolCalls") or []):
                tool, server, args = resolve_call(tc)
                names.append(tool)
                calls.append({"turn": turn, "step": i, "n": j, "tool": tool, "server": server,
                              "at": md.get("createdAt"), "args": compact(args),
                              "raw_call": compact(tc)})
            if names:
                row["label"] += " calls: " + ", ".join(names)
        else:
            row["label"] = " / ".join(filter(None, (_label(s.get(k)) for k in keys)))
        row["payload"] = compact({k: s.get(k) for k in keys})
        steps.append(row)
    return steps, calls


# ---------------------------------------------------------------- output

def _md_cell(s):
    return (s or "").replace("|", "\\|").replace("\n", " ")


def summary_md(steps, calls, manifest):
    census = Counter(r["type"] for r in steps)
    out = [f"**Completeness: {manifest.get('completeness')}**", ""]
    absent = (manifest.get("cross_check") or {}).get("absent_from_transcript")
    if absent:
        out += ["Steps in the .db but absent from the transcript (not DONE, typically):", ""]
        out += [f"- `{a}`" for a in absent]
        out += [""]
    out += ["## Step census", ""]
    out += [f"- `{t}`: {n}" for t, n in census.most_common()]
    out += ["", f"**Tool calls requested: {len(calls)}**", "",
            "## Tool calls per user turn", "",
            "| Turn | Request | Calls | By tool |", "|---|---|---|---|"]
    requests = OrderedDict((r["turn"], r.get("label", "")) for r in steps
                           if r["type"] == "USER_INPUT")
    for turn in sorted({r["turn"] for r in steps}):
        c = Counter(x["tool"] for x in calls if x["turn"] == turn)
        by = ", ".join(f"{t} {n}" for t, n in sorted(c.items()))
        out.append(f"| {turn} | {_md_cell(requests.get(turn, '(before first input)'))[:80]} "
                   f"| {sum(c.values())} | {_md_cell(by)} |")
    servers = Counter(x["server"] for x in calls if x["server"])
    if servers:
        out += ["", "## MCP calls by server", ""]
        out += [f"- `{s}`: {n}" for s, n in servers.most_common()]
    out += ["", "## Steps", "", "| # | turn | at | type | status | label |",
            "|---|---|---|---|---|---|"]
    for r in steps:
        out.append(f"| {r['i']} | {r['turn']} | {(r.get('at') or '')[11:19]} | {r['type']} "
                   f"| {r.get('status') or ''} | {_md_cell(r.get('label'))} |")
    return "\n".join(out) + "\n", census


def write_derived(cap, manifest, files):
    source = manifest.get("source")
    if source == "transcript":
        name = manifest.get("transcript_file") or "transcript_full.jsonl"
        steps, calls = transcript_rows(parse_rows(files[name]), set(files))
    elif source == "api":
        steps, calls = api_rows(json.loads(files["api_steps.json"]).get("steps") or [])
    else:
        raise CaptureError(f"unknown source in manifest: {source!r}")
    d = cap / "derived"
    d.mkdir(exist_ok=True)
    with open(d / "steps.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in steps)
    with open(d / "calls.jsonl", "w", encoding="utf-8", newline="\n") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in calls)
    md, census = summary_md(steps, calls, manifest)
    with open(d / "summary.md", "w", encoding="utf-8", newline="\n") as f:
        f.write(md)
    return steps, calls, census
