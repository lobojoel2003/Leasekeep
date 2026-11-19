"""Release helpers used by CI.

python scripts/release_tools.py version              # print the package version
python scripts/release_tools.py check-tag v1.2.3     # tag must match version and CHANGELOG
python scripts/release_tools.py notes v1.2.3 > notes.md
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def version() -> str:
    text = (ROOT / "leasekeep" / "__init__.py").read_text()
    match = re.search(r'^__version__ = "([^"]+)"', text, re.MULTILINE)
    if not match:
        sys.exit("Could not find __version__ in leasekeep/__init__.py")
    return match.group(1)


def changelog_section(ver: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text()
    match = re.search(rf"^## \[{re.escape(ver)}\][^\n]*\n(.*?)(?=^## \[|\Z)", text, re.MULTILINE | re.DOTALL)
    if not match:
        sys.exit(f"CHANGELOG.md has no section for [{ver}]")
    return match.group(1).strip()


def check_tag(tag: str) -> None:
    if not re.fullmatch(r"v\d+\.\d+\.\d+(?:-[0-9A-Za-z.]+)?", tag):
        sys.exit(f"Tag {tag!r} is not a semantic version tag like v1.2.3")
    ver = version()
    if tag != f"v{ver}":
        sys.exit(f"Tag {tag} does not match leasekeep.__version__ {ver}. Bump the version first.")
    changelog_section(ver)
    print(f"Tag {tag} matches version {ver} and CHANGELOG.md")


def main() -> None:
    command, *args = sys.argv[1:] or ["version"]
    if command == "version":
        print(version())
    elif command == "check-tag":
        check_tag(args[0])
    elif command == "notes":
        print(changelog_section(args[0].removeprefix("v")))
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
