"""Version and build metadata.

The semantic version lives in :data:`leasekeep.__version__`. Build metadata
(build number, git commit, build date) is injected by CI, either through
environment variables (Docker images) or a ``build_info.json`` file written
next to this module before a wheel is built.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path

from leasekeep import __version__

BUILD_INFO_FILE = Path(__file__).with_name("build_info.json")


@dataclass(frozen=True)
class BuildInfo:
    version: str
    build_number: str
    git_sha: str
    build_date: str

    @property
    def short_sha(self) -> str:
        return self.git_sha[:7] if self.git_sha else ""

    @property
    def label(self) -> str:
        parts = [f"v{self.version}"]
        if self.build_number:
            parts.append(f"build {self.build_number}")
        if self.short_sha:
            parts.append(self.short_sha)
        return " · ".join(parts)

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


@lru_cache(maxsize=1)
def get_build_info() -> BuildInfo:
    data: dict[str, str] = {}
    if BUILD_INFO_FILE.exists():
        try:
            data = json.loads(BUILD_INFO_FILE.read_text())
        except (OSError, ValueError):
            data = {}
    return BuildInfo(
        version=__version__,
        build_number=os.environ.get("LEASEKEEP_BUILD_NUMBER") or data.get("build_number", "dev"),
        git_sha=os.environ.get("LEASEKEEP_GIT_SHA") or data.get("git_sha", ""),
        build_date=os.environ.get("LEASEKEEP_BUILD_DATE") or data.get("build_date", ""),
    )
