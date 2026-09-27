"""ag-trace - capture Antigravity conversation traces as test evidence.

Two sources:
    transcript (default)  Antigravity's on-disk transcript. Offline; works for past
                          conversations; step count cross-checked against the .db.
    api                   The live LanguageServer API. Antigravity must be running.

Evidence is stored exactly as read and hashed; everything else is derived and can be
regenerated with `derive`. Every step becomes a row, known type or not. Failure exits
2 with nothing written; a capture that is not demonstrably complete exits 3.

    ag-trace list [-n 15] [--source transcript|api]
    ag-trace capture latest|<cascade_id> [--source ...] [--out DIR] [--label TEXT]
                     [--host-label TEXT]
    ag-trace verify <capture_dir | capture.zip>
    ag-trace derive <capture_dir>
    ag-trace pack <capture_dir>

`capture` also writes <cascade_id>-<timestamp>-<hash>.zip beside the folder: the one
file to attach to a test evidence record.
"""

import argparse
import os
import sys
from collections import Counter
from pathlib import Path

from ag_trace import TOOL_ID, __version__, live, transcript
from ag_trace.derive import write_derived
from ag_trace.evidence import CaptureError, load_verified, write_capture
from ag_trace.pack import pack, verify_zip


def cmd_list(a):
    if a.source == "api":
        convs = live.conversations(live.discover())
        items = sorted(convs.items(), key=lambda kv: kv[1][0].get("lastModifiedTime", ""),
                       reverse=True)
        print(f"{len(convs)} conversation(s) listed by the LanguageServer")
        for cid, (s, _) in items[: a.n]:
            print(f"{s.get('lastModifiedTime', '?')[:19]}  {s.get('stepCount', '?')!s:>5}  "
                  f"{cid}  {s.get('summary', '')[:60]}")
        return
    home = transcript.ag_home(a.ag_home)
    rows = transcript.list_local(home)
    n_trunc = sum(r["truncated"] for r in rows)
    print(f"{len(rows)} conversation(s) under {home / 'brain'} "
          f"({len(rows) - n_trunc} full transcript, {n_trunc} truncated only)")
    print(f"{'last step (UTC)':<20} {'steps':>5} {'calls':>5} {'file':<5}  "
          f"cascade_id{'':<27} request")
    for r in rows[: a.n]:
        kind = "TRUNC" if r["truncated"] else "full"
        print(f"{(r['last'] or '?')[:19]:<20} {r['steps']:>5} {r['tool_calls']:>5} {kind:<5}  "
              f"{r['cascade_id']}  {r['request'][:50]}")


def cmd_capture(a):
    if a.source == "api":
        files, detail = live.capture_api(a.id)
    else:
        files, detail = transcript.capture_transcript(transcript.ag_home(a.ag_home), a.id,
                                                      a.allow_truncated)
    cap, manifest = write_capture(a.out, a.source, files, detail, a.label, a.host_label)
    _, calls, census, skills = write_derived(cap, manifest, files)
    main_file = "api_steps.json" if a.source == "api" else detail["transcript_file"]
    print(f"captured  {detail['cascade_id']}  '{detail.get('title') or ''}'")
    print(f"source    {a.source}  ({len(files)} evidence file(s))")
    print(f"steps     {detail['steps_received']}  {detail['completeness']}")
    print(f"evidence  {main_file} sha256 {manifest['evidence'][main_file]['sha256']}")
    print(f"calls     {len(calls)} requested")
    for turn in sorted({c["turn"] for c in calls}):
        by = Counter(c["tool"] for c in calls if c["turn"] == turn)
        mcp = Counter(c["server"] for c in calls if c["turn"] == turn and c["server"])
        mcp_s = ", ".join(f"{s}={n}" for s, n in mcp.most_common()) or "none"
        print(f"  turn {turn:<3} {sum(by.values()):>3} calls; MCP by server: {mcp_s}")
    if skills is not None:
        if skills["available"] is None:
            print("skills    offered: unknown (no skills list in the .db)")
        else:
            read = ", ".join(f"{r['name']} (turn {r['turn']}, step {r['step']})"
                             for r in skills["read"]) or "none"
            print(f"skills    offered {len(skills['available'])}; SKILL.md read: {read}")
        if skills["other_skill_md_reads"]:
            print(f"          + {len(skills['other_skill_md_reads'])} other SKILL.md read(s)")
    absent = (manifest.get("cross_check") or {}).get("absent_from_transcript") or []
    for ab in absent:
        if isinstance(ab, dict):
            err = (ab.get("db_error") or [""])[0][:100]
            print(f"absent    step {ab['step_index']}: db status {ab['db_status']}"
                  + (f" - {err}" if err else ""))
    print("steps     by type: " + ", ".join(f"{t}={n}" for t, n in census.most_common()))
    print(f"dir       {cap}")
    print(f"detail    {cap / 'derived' / 'summary.md'}")
    if not a.no_zip:
        z = pack(cap)
        print(f"attach    {z}")
    if detail["completeness"] != "COMPLETE":
        sys.exit(3)  # written, but not demonstrably complete - do not cite as complete


def cmd_verify(a):
    if a.dir.lower().endswith(".zip"):
        manifest, files = verify_zip(a.dir)
        what = "zip name matches its bytes; "
    else:
        manifest, files = load_verified(a.dir)
        what = ""
    print(f"OK  {what}{len(files)} evidence file(s) match manifest  "
          f"({manifest.get('cascade_id')}, {manifest.get('source')}, "
          f"{manifest.get('completeness')})")


def cmd_pack(a):
    print(f"attach    {pack(a.dir, a.to)}")


def cmd_derive(a):
    manifest, files = load_verified(a.dir)
    _, calls, census, _ = write_derived(Path(a.dir), manifest, files)
    print(f"calls {len(calls)}; census " + ", ".join(f"{t}={n}" for t, n in census.most_common()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ag-trace", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"{TOOL_ID} {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add_source(p):
        p.add_argument("--source", choices=["transcript", "api"], default="transcript")
        p.add_argument("--ag-home", default=None,
                       help="Antigravity data dir (default: $AG_HOME or ~/.gemini/antigravity)")

    p = sub.add_parser("list", help="list conversations, newest first")
    p.add_argument("-n", type=int, default=15)
    add_source(p)
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("capture", help="capture one conversation as evidence")
    p.add_argument("id", help="cascade id, or 'latest'")
    add_source(p)
    p.add_argument("--out", default=os.environ.get("AG_TRACE_OUT", "captures"),
                   help="capture root (default: $AG_TRACE_OUT or ./captures)")
    p.add_argument("--label", default=None,
                   help="free text recorded in the manifest, e.g. the test and step this evidences")
    p.add_argument("--host-label", default=None,
                   help="recorded as the host instead of the machine name "
                        "(default: $AG_TRACE_HOST, else the machine name)")
    p.add_argument("--no-zip", action="store_true", help="skip writing the zip")
    p.add_argument("--allow-truncated", action="store_true",
                   help="accept transcript.jsonl when transcript_full.jsonl is absent (exit 3)")
    p.set_defaults(fn=cmd_capture)

    p = sub.add_parser("verify", help="check a capture folder or zip")
    p.add_argument("dir", help="capture folder, or a capture .zip")
    p.set_defaults(fn=cmd_verify)

    p = sub.add_parser("pack", help="zip an existing capture folder, hash in the name")
    p.add_argument("dir")
    p.add_argument("--to", default=None, help="output folder (default: the capture root)")
    p.set_defaults(fn=cmd_pack)

    p = sub.add_parser("derive", help="verify, then regenerate derived/ from evidence")
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
