"""Launch the app-local point-cloud demo through the normal desktop runtime.

Run this manually, confirm that the point cloud appears, then close the window.
"""

from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "examples" / "extensions" / "cnv_pointcloud_demo"


def main() -> None:
    subprocess.run(
        [sys.executable, str(FIXTURE / "demo.py")],
        check=True,
        cwd=FIXTURE,
    )


if __name__ == "__main__":
    main()
