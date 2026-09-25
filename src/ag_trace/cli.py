"""ag-trace - capture Antigravity conversation traces as test evidence.

Tooling record: TOOL-P058-004 (P058 35_Tooling). Backlog: P058 BLI-037.

Two sources:
    transcript (default)  Antigravity's on-disk transcript. Offline; works for past
                          conversations; step count cross-checked against the .db.
    api                   The live LanguageServer API. Antigravity must be running.

Evidence is stored exactly as read and hashed; everything else is derived and can be
regenerated with `derive`. Every step becomes a row, known type or not. Failure exits
2 with nothing written; a capture that is not demonstrably complete exits 3.

    ag-trace list [-n 15] [--source transcript|api]
    ag-trace capture latest|<cascade_id> [--source ...] [--out DIR] [--label TR-...]
    ag-trace verify <capture_dir>
    ag-trace derive <capture_dir>
"""

import argparse
import os
import sys
from pathlib import Path

from ag_trace import TOOL_ID, __version__, live, transcript
from ag_trace.derive import write_derived
from ag_trace.evidence import CaptureError, load_verified, write_capture


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
    print(f"{len(rows)} conversation transcript(s) under {home / 'brain'}")
    print(f"{'last step (UTC)':<20} {'steps':>5} {'calls':>5}  cascade_id{'':<27} request")
    for r in rows[: a.n]:
        print(f"{(r['last'] or '?')[:19]:<20} {r['steps']:>5} {r['tool_calls']:>5}  "
              f"{r['cascade_id']}  {r['request'][:50]}")


def cmd_capture(a):
    if a.source == "api":
        files, detail = live.capture_api(a.id)
    else:
        files, detail = transcript.capture_transcript(transcript.ag_home(a.ag_home), a.id,
                                                      a.allow_truncated)
    cap, manifest = write_capture(a.out, a.source, files, detail, a.label)
    _, calls, census = write_derived(cap, manifest, files)
    main_file = "api_steps.json" if a.source == "api" else detail["transcript_file"]
    print(f"captured  {detail['cascade_id']}  '{detail.get('title') or ''}'")
    print(f"source    {a.source}  ({len(files)} evidence file(s))")
    print(f"steps     {detail['steps_received']}  {detail['completeness']}")
    print(f"evidence  {main_file} sha256 {manifest['evidence'][main_file]['sha256']}")
    print(f"calls     {len(calls)} requested")
    print(f"dir       {cap}")
    print("census    " + ", ".join(f"{t}={n}" for t, n in census.most_common()))
    if detail["completeness"] != "COMPLETE":
        sys.exit(3)  # written, but not demonstrably complete - do not cite as complete


def cmd_verify(a):
    manifest, files = load_verified(a.dir)
    print(f"OK  {len(files)} evidence file(s) match manifest  "
          f"({manifest.get('source')}, {manifest.get('completeness')})")


def cmd_derive(a):
    manifest, files = load_verified(a.dir)
    _, calls, census = write_derived(Path(a.dir), manifest, files)
    print(f"calls {len(calls)}; census " + ", ".join(f"{t}={n}" for t, n in census.most_common()))


def main(argv=None):
    ap = argparse.ArgumentParser(prog="ag-trace", description=__doc__.splitlines()[0])
    ap.add_argument("--version", action="version", version=f"ag-trace {__version__} ({TOOL_ID})")
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
    p.add_argument("--label", default=None, help="e.g. the TR/TC/step this capture evidences")
    p.add_argument("--allow-truncated", action="store_true",
                   help="accept transcript.jsonl when transcript_full.jsonl is absent (exit 3)")
    p.set_defaults(fn=cmd_capture)

    p = sub.add_parser("verify", help="check evidence files against the manifest")
    p.add_argument("dir")
    p.set_defaults(fn=cmd_verify)

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
