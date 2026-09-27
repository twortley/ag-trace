#!/usr/bin/env python3
"""
Compose a release's notes from CHANGELOG.md, and refuse a tag that disagrees with
the code.

    python ci/release_notes.py v1.0.0 > notes.md

The tag must equal `v` + ag_trace.__version__, and CHANGELOG.md must have a
`## <version>` section; that section is the notes. Exits 1 naming what is missing.
"""
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: release_notes.py <tag>", file=sys.stderr)
        return 2
    tag = sys.argv[1]
    init = (ROOT / "src" / "ag_trace" / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__ = "([^"]+)"', init, re.M)
    version = m.group(1) if m else None
    problems = []
    if tag != f"v{version}":
        problems.append(f"tag {tag} does not match __version__ {version}")
    lines = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines()
    body, inside = [], False
    for line in lines:
        if line.startswith("## "):
            if inside:
                break
            inside = line[3:].split()[0] == str(version)
            continue
        if inside:
            body.append(line)
    if not inside and not body:
        problems.append(f"CHANGELOG.md has no '## {version}' section")
    if problems:
        for p in problems:
            print(f"  FAIL  {p}", file=sys.stderr)
        return 1
    print("\n".join(body).strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
