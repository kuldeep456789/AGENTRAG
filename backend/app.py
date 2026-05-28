import os
import sys
from pathlib import Path


def ensure_project_venv() -> None:
    """Re-launch with the repo .venv when started via system Python."""
    if os.environ.get("AI_BACKEND_VENV") == "1":
        return

    repo_root = Path(__file__).resolve().parent.parent
    venv_python = repo_root / ".venv" / "Scripts" / "python.exe"
    if not venv_python.exists():
        return

    current_python = Path(sys.executable).resolve()
    if current_python == venv_python.resolve():
        os.environ["AI_BACKEND_VENV"] = "1"
        return

    env = os.environ.copy()
    env["AI_BACKEND_VENV"] = "1"
    import subprocess

    completed = subprocess.run([str(venv_python), str(Path(__file__).resolve()), *sys.argv[1:]], env=env)
    raise SystemExit(completed.returncode)


if __name__ == "__main__":
    ensure_project_venv()

    import uvicorn

    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=True)
