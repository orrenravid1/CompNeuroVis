"""Launch the external point-cloud demo through the normal desktop runtime.

Run this manually, confirm that the point cloud appears, then close the window.
The fixture is installed into a temporary site directory so the repository and
the active Poetry environment remain untouched.
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="cnv-pointcloud-desktop-") as raw_temp:
        temp_dir = Path(raw_temp)
        fixture_copy = temp_dir / "fixture"
        shutil.copytree(FIXTURE, fixture_copy)
        target = temp_dir / "site"
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-deps",
                "--no-build-isolation",
                "--target",
                str(target),
                str(fixture_copy),
            ],
            check=True,
        )
        environment = dict(os.environ)
        existing_pythonpath = environment.get("PYTHONPATH")
        environment["PYTHONPATH"] = os.pathsep.join(
            part for part in (str(target), existing_pythonpath) if part
        )
        subprocess.run(
            [sys.executable, str(fixture_copy / "demo.py")],
            check=True,
            env=environment,
        )


if __name__ == "__main__":
    main()
