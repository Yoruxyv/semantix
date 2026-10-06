"""Launch the offline validator in the existing locked cache environment."""

import subprocess
import sys
from pathlib import Path

package = Path(__file__).resolve().parents[2] / "packages/cache"
interpreter = (
    package
    / ".venv"
    / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
)
if not interpreter.is_file():
    sys.exit(
        "Reuse-quality hook needs the existing cache environment: run uv sync --locked --extra dev in packages/cache."
    )
sys.exit(
    subprocess.run(  # noqa: S603 -- fixed local interpreter and validation command
        [
            str(interpreter),
            "-B",
            "-m",
            "benchmarks.reuse_quality.benchmark",
            "validate",
        ],
        cwd=package,
        check=False,
        timeout=30,
    ).returncode
)
