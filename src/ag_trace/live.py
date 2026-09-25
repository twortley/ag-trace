"""Live source: the Antigravity LanguageServer API (Antigravity must be running).

Approach (process discovery, CSRF token, LanguageServer endpoints) derived from
https://github.com/neo1027144-creator/antigravity-history at commit
4046f8f7e808be28b8d5b8cc57bf2ec39d2cc9bd (v0.2.6), Apache-2.0. Re-written, not
copied: stdlib transport, exact-PID port match, errors raised instead of
swallowed, no step-type whitelist.
"""

import json
import platform
import re
import ssl
import subprocess
import urllib.request

from ag_trace.evidence import CaptureError

SERVICE = "exa.language_server_pb.LanguageServerService"


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


def capture_api(cid):
    """Fetch one conversation. Returns (files, detail). Raises CaptureError."""
    endpoints = discover()
    convs = conversations(endpoints)
    if cid == "latest":
        if not convs:
            raise CaptureError("the LanguageServer lists no conversations")
        cid = max(convs, key=lambda c: convs[c][0].get("lastModifiedTime", ""))
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
        completeness = "UNVERIFIED (conversation not in index)"
    elif len(steps) >= expected:
        completeness = "COMPLETE"
    else:
        completeness = f"SHORT ({len(steps)}/{expected})"
    detail = {
        "cascade_id": cid, "title": summary.get("summary"),
        "steps_expected": expected or None, "steps_received": len(steps),
        "completeness": completeness,
        "language_server": {"pid": ep["pid"], "port": ep["port"], "exe": ep["exe"]},
        "summary": summary,
    }
    return {"api_steps.json": raw}, detail
