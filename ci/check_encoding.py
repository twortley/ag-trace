#!/usr/bin/env python3
"""
Repo Text & Encoding check: every tracked text file is UTF-8 with no BOM, no CR
bytes and no non-breaking spaces (C2 A0).

    python ci/check_encoding.py

Exits 1 and names each offending file and byte offset. Binary files are those
.gitattributes marks `binary`; everything else tracked is held to the rule. A file
.gitattributes declares `eol=crlf` (a PowerShell script, say) is exempt from the
CR rule only -- it is CRLF on purpose.
Run in CI because the defect is invisible in an editor and recurs with every
unfamiliar tool that touches a file.
"""
import fnmatch
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def binary_patterns() -> list[str]:
    attrs = ROOT / ".gitattributes"
    if not attrs.exists():
        return []
    out = []
    for line in attrs.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) >= 2 and not line.lstrip().startswith("#") and "binary" in parts[1:]:
            out.append(parts[0])
    return out


def main() -> int:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True,
                           capture_output=True).stdout.decode().split("\0")
    binary = binary_patterns()
    names = [n for n in files if n]
    attrs = subprocess.run(["git", "check-attr", "-z", "eol", "--"] + names, cwd=ROOT,
                           check=True, capture_output=True).stdout.decode().split("\0")
    crlf = {attrs[i] for i in range(0, len(attrs) - 2, 3) if attrs[i + 2] == "crlf"}
    problems: list[str] = []
    checked = 0
    for name in filter(None, files):
        if any(fnmatch.fnmatch(pathlib.PurePosixPath(name).name, p) for p in binary):
            continue
        data = (ROOT / name).read_bytes()
        checked += 1
        if data.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{name}: UTF-8 BOM")
        for label, needle in (("CR byte", b"\r"), ("non-breaking space", b"\xc2\xa0")):
            if needle == b"\r" and name in crlf:
                continue
            at = data.find(needle)
            if at >= 0:
                problems.append(f"{name}: {label} at byte {at} "
                                f"({data.count(needle)} in file)")
        try:
            data.decode("utf-8")
        except UnicodeDecodeError as exc:
            problems.append(f"{name}: not UTF-8 ({exc.reason} at byte {exc.start})")
    # A check that inspected nothing would pass; refuse that.
    if checked == 0:
        print("ENCODING CHECK FAILED: no tracked text files were found to check")
        return 1
    for p in problems:
        print(f"  FAIL  {p}")
    print(f"{checked} text files checked, {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
