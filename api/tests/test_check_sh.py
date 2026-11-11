"""tools/check.sh builds api/venv with python3.12 (what the VPS runs), falls
back to python3, and fails in one line when no interpreter can make a venv.

Each test runs a copy of check.sh under a PATH that holds only the tools it
needs plus fake interpreters. A fake that "works" logs its call and writes
stub venv/bin/{python,pip}; a fake that "fails" exits 1 the way python3 3.14
without ensurepip does. Nothing touches the network or the real api/venv.
"""
import shutil
import subprocess
from pathlib import Path

CHECK_SH = Path(__file__).resolve().parents[2] / "tools" / "check.sh"
TOOLS = ["bash", "basename", "dirname", "sha256sum", "cut", "cat", "rm", "mkdir", "chmod"]

WORKS = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
[ "$1 $2" = "-m venv" ] || exit 2
mkdir -p "$3/bin"
printf '#!/bin/sh\\necho "pip $*" >> "$LOG"\\n' > "$3/bin/pip"
printf '#!/bin/sh\\necho "venv-python $*" >> "$LOG"\\n' > "$3/bin/python"
chmod +x "$3/bin/pip" "$3/bin/python"
"""

# Like python3 3.14 with no ensurepip: leaves venv/bin/python behind, no pip.
FAILS = """#!/bin/sh
echo "$(basename "$0") $*" >> "$LOG"
mkdir -p "$3/bin" && : > "$3/bin/python" && chmod +x "$3/bin/python"
echo "The virtual environment was not created successfully because ensurepip is not available." >&2
exit 1
"""


def run_check(tmp_path, interpreters, half_venv=False):
    """Run a copy of check.sh with only `interpreters` ({name: script}) on PATH."""
    root = tmp_path / "repo"
    (root / "tools").mkdir(parents=True)
    (root / "api").mkdir()
    shutil.copy(CHECK_SH, root / "tools" / "check.sh")
    (root / "api" / "requirements.txt").write_text("fastapi\n")
    if half_venv:
        (root / "api" / "venv" / "bin").mkdir(parents=True)
        (root / "api" / "venv" / "bin" / "python").write_text("")
        (root / "api" / "venv" / "bin" / "python").chmod(0o755)

    bindir = tmp_path / "bin"
    bindir.mkdir()
    for tool in TOOLS:
        (bindir / tool).symlink_to(shutil.which(tool))
    for name, script in interpreters.items():
        (bindir / name).write_text(script)
        (bindir / name).chmod(0o755)

    log = tmp_path / "calls.log"
    log.write_text("")
    proc = subprocess.run(
        [str(bindir / "bash"), str(root / "tools" / "check.sh"), "-q"],
        env={"PATH": str(bindir), "LOG": str(log)},
        capture_output=True, text=True, timeout=30,
    )
    return proc, log.read_text().splitlines(), root / "api" / "venv"


def test_venv_is_built_with_python312_not_python3(tmp_path):
    proc, calls, _ = run_check(tmp_path, {"python3.12": WORKS, "python3": FAILS})
    assert proc.returncode == 0, proc.stderr
    assert calls == [
        "python3.12 -m venv venv",
        "pip install -q -r requirements.txt",
        "venv-python -m pytest -q",
    ]


def test_falls_back_to_python3_when_python312_is_absent(tmp_path):
    proc, calls, _ = run_check(tmp_path, {"python3": WORKS})
    assert proc.returncode == 0, proc.stderr
    assert calls[0] == "python3 -m venv venv"


def test_no_interpreter_that_can_make_a_venv_fails_in_one_line(tmp_path):
    proc, calls, venv = run_check(tmp_path, {"python3": FAILS})
    assert proc.returncode == 1
    lines = proc.stderr.strip().splitlines()
    assert len(lines) == 1, proc.stderr
    assert "/python3 cannot create a venv" in lines[0]
    assert "python3.12" in lines[0]
    assert not venv.exists()  # no half venv left to trip the next run


def test_no_python_on_path_fails_in_one_line(tmp_path):
    proc, calls, _ = run_check(tmp_path, {})
    assert proc.returncode == 1
    assert proc.stderr.strip() == "check.sh: neither python3.12 nor python3 is on PATH"


def test_half_built_venv_from_a_failed_run_is_rebuilt(tmp_path):
    proc, calls, _ = run_check(tmp_path, {"python3.12": WORKS}, half_venv=True)
    assert proc.returncode == 0, proc.stderr
    assert calls[0] == "python3.12 -m venv venv"
