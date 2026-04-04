from __future__ import annotations

import subprocess
from datetime import datetime, timezone

CHANGELOG_PATH = "CHANGELOG.md"


def log_and_commit(change_description: str, files_changed: list[str]) -> None:
    """Append to CHANGELOG, stage, commit, push."""
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    entry = (
        f"\n## [{timestamp}]\n"
        f"{change_description}\n"
        f"Files: {', '.join(files_changed)}\n"
    )

    with open(CHANGELOG_PATH, "a") as f:
        f.write(entry)

    subprocess.run(
        ["git", "add"] + files_changed + [CHANGELOG_PATH],
        check=True,
    )
    subprocess.run(
        ["git", "commit", "-m", f"[SCALPER-AI] {change_description[:72]}"],
        check=True,
    )
    subprocess.run(["git", "push", "origin", "main"], check=True)
