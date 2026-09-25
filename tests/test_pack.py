"""Zipped captures: the name carries the hash; verify checks name, then contents."""

import hashlib
import io
import re
import zipfile
from pathlib import Path

from test_transcript import CID, make_home, run

NAME = re.compile(rf"^{CID}-\d{{8}}T\d{{6}}[+-]\d{{4}}-[0-9a-f]{{16}}\.zip$")


def capture(tmp_path, *extra):
    home = make_home(tmp_path)
    out = tmp_path / "out"
    code = run(["capture", CID, "--ag-home", str(home), "--out", str(out), *extra])
    return code, out


def the_zip(out):
    (z,) = list(Path(out).glob("*.zip"))
    return z


def rename_to_hash(path):
    """Give a (tampered) zip the name its bytes now hash to."""
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:16]
    new = path.with_name(re.sub(r"-[0-9a-f]{16}\.zip$", f"-{h}.zip", path.name))
    path.rename(new)
    return new


def rewrite(path, edit):
    """Rebuild a zip with edit(name, data) -> (name, data) | None applied to each entry."""
    src = zipfile.ZipFile(path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for n in src.namelist():
            r = edit(n, src.read(n))
            if r:
                z.writestr(r[0], r[1])
    src.close()
    path.write_bytes(buf.getvalue())


def test_capture_writes_named_zip_that_verifies(tmp_path, capsys):
    code, out = capture(tmp_path)
    assert code == 0
    z = the_zip(out)
    assert NAME.match(z.name)
    assert f"attach    {z}" in capsys.readouterr().out
    assert run(["verify", str(z)]) == 0


def test_no_zip_flag(tmp_path):
    _, out = capture(tmp_path, "--no-zip")
    assert not list(Path(out).glob("*.zip"))


def test_pack_is_deterministic(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    first = z.read_bytes()
    cap = next(p for p in (out / CID).iterdir() if p.is_dir())
    assert run(["pack", str(cap), "--to", str(tmp_path / "again")]) == 0
    (z2,) = list((tmp_path / "again").glob("*.zip"))
    assert z2.name == z.name and z2.read_bytes() == first


def test_renamed_zip_fails(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    bad = z.with_name(z.name[:-8] + "00000000.zip")
    z.rename(bad)
    assert run(["verify", str(bad)]) == 2


def test_modified_zip_fails_on_name(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    with open(z, "ab") as f:
        f.write(b"x")
    assert run(["verify", str(z)]) == 2


def test_altered_evidence_fails_even_with_matching_name(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    rewrite(z, lambda n, d: (n, d + b" ") if n.endswith("transcript_full.jsonl") else (n, d))
    assert run(["verify", str(rename_to_hash(z))]) == 2


def test_entry_outside_capture_fails(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    with zipfile.ZipFile(z, "a") as zz:
        zz.writestr("../escape.txt", "x")
    assert run(["verify", str(rename_to_hash(z))]) == 2


def test_zip_name_for_other_conversation_fails(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    other = "99999999-2222-3333-4444-555555555555"
    rewrite(z, lambda n, d: (n.replace(CID, other, 1), d))
    moved = z.with_name(z.name.replace(CID, other, 1))
    z.rename(moved)
    assert run(["verify", str(rename_to_hash(moved))]) == 2


def test_non_ag_trace_name_fails(tmp_path):
    _, out = capture(tmp_path)
    z = the_zip(out)
    plain = z.with_name(f"{CID}.zip")
    z.rename(plain)
    assert run(["verify", str(plain)]) == 2
