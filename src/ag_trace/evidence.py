"""Evidence handling: tool identity, capture folders, manifests, integrity checks.

A capture folder is:
    <out>/<cascade_id>/<local timestamp>/
        manifest.json        what was captured, by what, and the hash of every evidence file
        evidence/...         source bytes exactly as read; never modified
        derived/...          regenerable from evidence with `ag-trace derive`
"""

import datetime as dt
import hashlib
import json
import platform
import subprocess
from pathlib import Path

from ag_trace import TOOL_ID, __version__


class CaptureError(Exception):
    """Any failure. The CLI turns it into exit code 2 with nothing written."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


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
    return {"tool": TOOL_ID, "tool_version": __version__,
            "tool_sha256": h.hexdigest(), "tool_git": git}


def write_capture(out, source, files, detail, label=None):
    """Write evidence files and manifest. All inputs are validated before this is called,
    so a failure here is an I/O failure, not a partial capture of bad data."""
    if not files:
        raise CaptureError("no evidence files - nothing written")
    now = dt.datetime.now().astimezone()
    cap = Path(out) / detail["cascade_id"] / now.strftime("%Y%m%dT%H%M%S%z")
    cap.mkdir(parents=True, exist_ok=False)
    listing = {}
    for rel, data in sorted(files.items()):
        p = cap / "evidence" / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
        listing[rel] = {"bytes": len(data), "sha256": sha256(data)}
    manifest = {
        **tool_identity(),
        "python": platform.python_version(),
        "captured_at": now.isoformat(timespec="seconds"),
        "host": platform.node(),
        "label": label,
        "source": source,
        **detail,
        "evidence": listing,
    }
    (cap / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                       encoding="utf-8")
    return cap, manifest


def load_verified(cap):
    """Return (manifest, {rel: bytes}) after checking every evidence file against the
    manifest. Missing, altered or unlisted files raise CaptureError."""
    cap = Path(cap)
    try:
        manifest = json.loads((cap / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CaptureError(f"cannot read manifest in {cap}: {e}") from e
    listing = manifest.get("evidence") or {}
    ev = cap / "evidence"
    present = {p.relative_to(ev).as_posix() for p in ev.rglob("*") if p.is_file()} \
        if ev.is_dir() else set()
    problems = [f"unlisted: {r}" for r in sorted(present - set(listing))]
    files = {}
    for rel, want in sorted(listing.items()):
        p = ev / rel
        if not p.is_file():
            problems.append(f"missing: {rel}")
            continue
        data = p.read_bytes()
        if sha256(data) != want["sha256"]:
            problems.append(f"altered: {rel}")
        files[rel] = data
    if problems:
        raise CaptureError("evidence does not match manifest - " + "; ".join(problems[:10]))
    return manifest, files
