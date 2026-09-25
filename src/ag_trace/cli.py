"""ag_trace - capture Antigravity conversation traces as test evidence.

Tooling record: TOOL-P058-004 (P058 35_Tooling). Backlog: P058 BLI-037.

The raw API response is the evidence; everything else is derived from it and can
be regenerated with `derive`. Nothing is dropped: every step becomes a row, known
type or not. Any failure stops the run with a non-zero exit - an empty or partial
capture is never written as if it were complete.

Transport approach (process discovery, CSRF token, LanguageServer endpoints)
derived from https://github.com/neo1027144-creator/antigravity-history
at commit 4046f8f7e808be28b8d5b8cc57bf2ec39d2cc9bd (v0.2.6), Apache-2.0.
Re-written, not copied: stdlib transport, exact-PID port match, errors raised
instead of swallowed, no step-type whitelist. Standard library only.

Usage (Windows, Antigravity running with a workspace open):
    ag-trace list [-n 15]
    ag-trace capture latest|<cascade_id> [--out DIR] [--label TC-P055-006]
    ag-trace derive <capture_dir>          # re-derive offline from raw.json
"""

import argparse
import datetime as dt
import hashlib
import json
import os
import platform
import re
import ssl
import subprocess
import sys
import urllib.request
from collections import Counter
from pathlib import Path

from ag_trace import TOOL_ID, __version__

TOOL_VERSION = __version__
SERVICE = "exa.language_server_pb.LanguageServerService"
LONG = 200  # strings longer than this are summarised in derived rows (never in raw)


class CaptureError(Exception):
    pass


# ---------------------------------------------------------------- transport

_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE  # LanguageServer uses a self-signed cert on 127.0.0.1
_OPENER = urllib.request.build_opener(
    urllib.request.ProxyHandler({}),  # never route localhost through a proxy
    urllib.request.HTTPSHandler(context=_CTX),
)


def call(port, csrf, method, body, timeout=30):
    """POST to the LanguageServer. Returns (parsed_json, raw_bytes). Raises CaptureError."""
    req = urllib.request.Request(
        f"https://127.0.0.1:{port}/{SERVICE}/{method}",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
            "X-Codeium-Csrf-Token": csrf,
        },
        method="POST",
    )
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except Exception as e:  # re-raised with context, never swallowed
        raise CaptureError(f"{method} on port {port} failed: {e}") from e
    try:
        return json.loads(raw), raw
    except ValueError as e:
        raise CaptureError(f"{method} on port {port} returned non-JSON ({len(raw)} bytes)") from e


def discover():
    """Find live LanguageServer endpoints. Windows only. Raises CaptureError."""
    if platform.system() != "Windows":
        raise CaptureError("discovery is Windows-only; run this on the Antigravity host")
    ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'language_server*' } | "
          "Select-Object ProcessId, ExecutablePath, CommandLine | ConvertTo-Json")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, timeout=30, check=False)
    if r.returncode != 0 or not r.stdout.strip():
        raise CaptureError("no language_server process found - is Antigravity running "
                           "with a workspace open?")
    procs = json.loads(r.stdout)
    procs = [procs] if isinstance(procs, dict) else procs

    ns = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                        capture_output=True, text=True, timeout=30, check=False).stdout
    listening = {}  # pid -> [ports]; exact PID column match (upstream used a substring test)
    for line in ns.splitlines():
        parts = line.split()
        if len(parts) >= 5 and parts[3] == "LISTENING":
            m = re.match(r"127\.0\.0\.1:(\d+)$", parts[1])
            if m:
                listening.setdefault(parts[4], []).append(int(m.group(1)))

    endpoints, errors = [], []
    for p in procs:
        cmd = p.get("CommandLine") or ""
        m = re.search(r"--csrf_token[= ](\S+)", cmd)
        if not m:
            continue
        pid = str(p.get("ProcessId"))
        for port in sorted(listening.get(pid, [])):
            try:
                call(port, m.group(1), "GetAllCascadeTrajectories", {}, timeout=5)
            except CaptureError as e:
                errors.append(str(e))
                continue
            endpoints.append({"pid": int(pid), "port": port, "csrf": m.group(1),
                              "exe": p.get("ExecutablePath") or ""})
            break
    if not endpoints:
        raise CaptureError(f"found {len(procs)} language_server process(es) but no port "
                           f"answered. Last errors: {errors[-3:]}")
    return endpoints


def conversations(endpoints):
    """Merge summaries across endpoints. Returns {cascade_id: (summary, endpoint)}."""
    merged = {}
    for ep in endpoints:
        data, _ = call(ep["port"], ep["csrf"], "GetAllCascadeTrajectories", {}, timeout=15)
        for cid, s in (data.get("trajectorySummaries") or {}).items():
            merged.setdefault(cid, (s, ep))
    return merged


# ---------------------------------------------------------------- derivation

def _digest(b):
    return hashlib.sha256(b).hexdigest()


def tool_identity():
    """Hash of the package source (sorted *.py) plus git state if run from a checkout."""
    pkg = Path(__file__).resolve().parent
    h = hashlib.sha256()
    for f in sorted(pkg.glob("*.py")):
        h.update(f.name.encode() + b"\0" + f.read_bytes() + b"\0")
    git = None
    try:
        r = subprocess.run(["git", "-C", str(pkg), "describe", "--always", "--dirty", "--tags"],
                           capture_output=True, text=True, timeout=10, check=False)
        if r.returncode == 0:
            git = r.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        pass
    return {"tool": TOOL_ID, "tool_version": TOOL_VERSION,
            "tool_sha256": h.hexdigest(), "tool_git": git}


def compact(v):
    """Keep structure and short values; replace long strings by length + hash."""
    if isinstance(v, str):
        if len(v) <= LONG:
            return v
        return f"<{len(v)} chars sha256:{_digest(v.encode())[:12]}>"
    if isinstance(v, dict):
        return {k: compact(x) for k, x in v.items()}
    if isinstance(v, list):
        if len(v) > 20:
            return [compact(x) for x in v[:20]] + [f"<+{len(v) - 20} more>"]
        return [compact(x) for x in v]
    return v


_LABEL_KEYS = ("serverName", "toolName", "name", "commandLine", "command",
               "absolutePathUri", "directoryPath", "filePath", "query", "url", "uri",
               "error", "message")


def _label(payload):
    if not isinstance(payload, dict):
        return ""
    bits = [str(payload[k]) for k in _LABEL_KEYS if isinstance(payload.get(k), (str, int))]
    return " | ".join(bits)[:160]


def derive_rows(steps):
    rows = []
    for i, s in enumerate(steps):
        md = s.get("metadata") or {}
        payload_keys = [k for k in s if k not in ("type", "metadata", "status")]
        row = {
            "i": i,
            "type": (s.get("type") or "").replace("CORTEX_STEP_TYPE_", ""),
            "status": (s.get("status") or "").replace("CORTEX_STEP_STATUS_", ""),
            "at": md.get("createdAt"),
            "model": md.get("generatorModel"),
            "payload_keys": payload_keys,
        }
        if row["type"] == "USER_INPUT":
            row["label"] = ((s.get("userInput") or {}).get("userResponse") or "")[:160]
        elif row["type"] == "PLANNER_RESPONSE":
            pr = s.get("plannerResponse") or {}
            text = pr.get("modifiedResponse") or pr.get("response") or ""
            row["label"] = f"<response {len(text)} chars>"
            tcs = pr.get("toolCalls") or []
            if tcs:
                row["tool_calls"] = compact(tcs)
                row["label"] += " calls: " + ", ".join(str(t.get("name", "?")) for t in tcs)
        else:
            row["label"] = " / ".join(filter(None, (_label(s.get(k)) for k in payload_keys)))
        row["payload"] = compact({k: s.get(k) for k in payload_keys})
        rows.append(row)
    return rows


def write_derived(cap_dir, steps):
    rows = derive_rows(steps)
    with open(os.path.join(cap_dir, "steps.jsonl"), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)
    census = Counter(r["type"] for r in rows)
    lines = ["| # | at | type | status | label |", "|---|---|---|---|---|"]
    for r in rows:
        lab = (r.get("label") or "").replace("|", "\\|").replace("\n", " ")
        at = (r["at"] or "")[11:19]
        lines.append(f"| {r['i']} | {at} | {r['type']} | {r['status']} | {lab} |")
    with open(os.path.join(cap_dir, "steps.md"), "w", encoding="utf-8") as f:
        f.write("## Step census\n\n")
        f.write("\n".join(f"- `{t}`: {n}" for t, n in census.most_common()) + "\n\n")
        f.write("## Steps\n\n" + "\n".join(lines) + "\n")
    return rows, census


# ---------------------------------------------------------------- commands

def cmd_list(a):
    convs = conversations(discover())
    items = sorted(convs.items(), key=lambda kv: kv[1][0].get("lastModifiedTime", ""), reverse=True)
    print(f"{len(convs)} conversation(s)")
    for cid, (s, _) in items[: a.n]:
        print(f"{s.get('lastModifiedTime', '?')[:19]}  {s.get('stepCount', '?')!s:>5}  "
              f"{cid}  {s.get('summary', '')[:60]}")


def cmd_capture(a):
    endpoints = discover()
    convs = conversations(endpoints)
    if a.id == "latest":
        if not convs:
            raise CaptureError("no conversations listed")
        cid = max(convs, key=lambda c: convs[c][0].get("lastModifiedTime", ""))
    else:
        cid = a.id
    summary, ep = convs.get(cid, ({}, endpoints[0]))
    expected = int(summary.get("stepCount") or 0)
    end = expected + 50 if expected else 100000

    data, raw = call(ep["port"], ep["csrf"], "GetCascadeTrajectorySteps",
                     {"cascadeId": cid, "startIndex": 0, "endIndex": end}, timeout=120)
    steps = data.get("steps")
    if steps is None:
        raise CaptureError(f"response has no 'steps' key; keys: {list(data)[:10]}")
    if not steps:
        raise CaptureError(f"zero steps returned for {cid} - nothing written")
    if not expected:
        completeness = "UNKNOWN (conversation not in index)"
    elif len(steps) >= expected:
        completeness = "COMPLETE"
    else:
        completeness = f"SHORT ({len(steps)}/{expected})"

    now = dt.datetime.now().astimezone()
    cap_dir = os.path.join(a.out, cid, now.strftime("%Y%m%dT%H%M%S%z"))
    os.makedirs(cap_dir, exist_ok=False)
    with open(os.path.join(cap_dir, "raw.json"), "wb") as f:
        f.write(raw)  # exact bytes as received; this is the evidence
    manifest = {
        **tool_identity(),
        "python": platform.python_version(),
        "captured_at": now.isoformat(timespec="seconds"),
        "host": platform.node(), "label": a.label,
        "cascade_id": cid, "title": summary.get("summary"),
        "created_time": summary.get("createdTime"),
        "last_modified_time": summary.get("lastModifiedTime"),
        "steps_expected": expected or None, "steps_received": len(steps),
        "completeness": completeness,
        "raw_file": "raw.json", "raw_bytes": len(raw), "raw_sha256": _digest(raw),
        "language_server": {"pid": ep["pid"], "port": ep["port"], "exe": ep["exe"]},
        "summary": summary,
    }
    with open(os.path.join(cap_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    _, census = write_derived(cap_dir, steps)

    print(f"captured  {cid}  '{summary.get('summary', '')}'")
    print(f"steps     {len(steps)}  {completeness}")
    print(f"raw       sha256 {manifest['raw_sha256']}  ({len(raw)} bytes)")
    print(f"dir       {cap_dir}")
    print("census    " + ", ".join(f"{t}={n}" for t, n in census.most_common()))
    if completeness.startswith("SHORT"):
        sys.exit(3)  # written, but flagged - do not cite as complete


def cmd_derive(a):
    raw_path = os.path.join(a.dir, "raw.json")
    with open(raw_path, "rb") as f:
        raw = f.read()
    mpath = os.path.join(a.dir, "manifest.json")
    if os.path.exists(mpath):
        with open(mpath, encoding="utf-8") as f:
            want = json.load(f).get("raw_sha256")
        if want and want != _digest(raw):
            raise CaptureError("raw.json hash does not match manifest - evidence altered")
    _, census = write_derived(a.dir, json.loads(raw).get("steps") or [])
    print("census " + ", ".join(f"{t}={n}" for t, n in census.most_common()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ag-trace", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"ag-trace {TOOL_VERSION} ({TOOL_ID})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list", help="list conversations, newest first")
    p.add_argument("-n", type=int, default=15)
    p.set_defaults(fn=cmd_list)
    p = sub.add_parser("capture", help="capture one conversation as evidence")
    p.add_argument("id", help="cascade id, or 'latest'")
    p.add_argument("--out", default=os.environ.get("AG_TRACE_OUT", "captures"),
                   help="capture root (default: $AG_TRACE_OUT or ./captures)")
    p.add_argument("--label", default=None, help="e.g. TR/TC/step this capture evidences")
    p.set_defaults(fn=cmd_capture)
    p = sub.add_parser("derive", help="regenerate derived files from raw.json")
    p.add_argument("dir")
    p.set_defaults(fn=cmd_derive)
    a = ap.parse_args(argv)
    try:
        a.fn(a)
    except CaptureError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
