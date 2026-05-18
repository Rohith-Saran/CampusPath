import shutil
import subprocess
from typing import Tuple


def _run(cmd: list, cwd: str) -> Tuple[int, str]:
    p = subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return p.returncode, p.stdout


def run_cpp() -> str:
    """Compile mutex_demo.cpp and run the produced binary.

    Returns formatted combined output (compile + run).
    """
    here = __file__
    # Path of repo root is same dir as this file
    import os

    repo_dir = os.path.dirname(os.path.abspath(here))
    src = os.path.join(repo_dir, "mutex_demo.cpp")
    bin_path = os.path.join(repo_dir, "mutex_demo")

    if shutil.which("g++") is None:
        return (
            "g++ not found. Please install g++ (e.g., Xcode Command Line Tools):\n"
            "xcode-select --install\n"
        )

    compile_cmd = ["g++", "-std=c++17", "-pthread", "mutex_demo.cpp", "-o", "mutex_demo"]
    rc, out = _run(compile_cmd, cwd=repo_dir)

    if rc != 0:
        return "=== COMPILATION FAILED ===\n" + out

    rc2, run_out = _run([bin_path], cwd=repo_dir)
    return "=== COMPILATION SUCCEEDED ===\n" + out + "\n=== PROGRAM OUTPUT ===\n" + run_out

