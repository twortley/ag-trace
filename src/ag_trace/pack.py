"""One-file captures: a zip whose name carries its own hash.

    <cascade_id>-<timestamp>-<sha256[:16]>.zip
    └── <cascade_id>/<timestamp>/manifest.json, evidence/..., derived/...

The name is what a TE embeds, so the link itself says which bytes it means: a
re-capture of the same conversation, a swapped file or a damaged copy cannot carry
the same name. `verify` checks the name against the bytes, then the manifest against
the evidence inside.

This binds a record to a file. It does not prove who made the file: anyone who can
edit the zip can rename it. Tamper evidence would need the hash held somewhere the
vault cannot change.

The zip is deterministic (sorted entries, fixed timestamps), so packing the same
capture twice gives the same bytes and the same name.
"""

import re
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from ag_trace.evidence import CaptureError, load_verified, sha256

HASH_LEN = 16
_NAME = re.compile(r"^(?P<cid>.+)-(?P<ts>\d{8}T\d{6}[+-]\d{4})-(?P<h>[0-9a-f]{"
                   + str(HASH_LEN) + r"})\.zip$")
_FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def pack(cap_dir, dest_dir=None):
    """Zip a capture folder <root>/<cid>/<ts>. Verifies it first. Returns the zip path."""
    cap = Path(cap_dir).resolve()
    manifest, _ = load_verified(cap)
    cid, ts = cap.parent.name, cap.name
    if manifest.get("cascade_id") != cid:
        raise CaptureError(f"folder {cid} does not match manifest cascade_id "
                           f"{manifest.get('cascade_id')}")
    dest = Path(dest_dir) if dest_dir else cap.parent.parent
    dest.mkdir(parents=True, exist_ok=True)
    tmp = dest / f".{cid}-{ts}.zip.partial"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(p for p in cap.rglob("*") if p.is_file()):
                arc = f"{cid}/{ts}/{f.relative_to(cap).as_posix()}"
                info = zipfile.ZipInfo(arc, date_time=_FIXED_TIME)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o644 << 16
                z.writestr(info, f.read_bytes())
        digest = sha256(tmp.read_bytes())
        out = dest / f"{cid}-{ts}-{digest[:HASH_LEN]}.zip"
        tmp.replace(out)
    except OSError as e:
        raise CaptureError(f"could not write zip in {dest}: {e}") from e
    finally:
        if tmp.exists():
            tmp.unlink()
    return out


def verify_zip(path):
    """Check name against bytes, then the capture inside. Returns (manifest, files)."""
    path = Path(path)
    m = _NAME.match(path.name)
    if not m:
        raise CaptureError(f"{path.name} is not an ag-trace zip name "
                           "(<cascade_id>-<timestamp>-<hash>.zip)")
    digest = sha256(path.read_bytes())
    if digest[:HASH_LEN] != m["h"]:
        raise CaptureError(f"zip contents do not match its name: name says {m['h']}, "
                           f"bytes hash to {digest[:HASH_LEN]}")
    prefix = f"{m['cid']}/{m['ts']}/"
    with zipfile.ZipFile(path) as z, tempfile.TemporaryDirectory() as tmp:
        names = z.namelist()
        bad = [n for n in names if not n.startswith(prefix)
               or ".." in PurePosixPath(n).parts or n.startswith("/")]
        if bad:
            raise CaptureError(f"zip holds entries outside {prefix}: {bad[:3]}")
        z.extractall(tmp)
        manifest, files = load_verified(Path(tmp) / m["cid"] / m["ts"])
    if manifest.get("cascade_id") != m["cid"]:
        raise CaptureError("zip name and manifest name different conversations")
    return manifest, files
