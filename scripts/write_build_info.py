"""Write leasekeep/build_info.json so a built wheel knows its build number and commit.

python scripts/write_build_info.py --build-number 42 --git-sha "$(git rev-parse HEAD)"
"""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

TARGET = Path(__file__).resolve().parent.parent / "leasekeep" / "build_info.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-number", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--build-date", default=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    args = parser.parse_args()
    info = {"build_number": args.build_number, "git_sha": args.git_sha, "build_date": args.build_date}
    TARGET.write_text(json.dumps(info, indent=2) + "\n")
    print(f"Wrote {TARGET.name}: {info}")


if __name__ == "__main__":
    main()
