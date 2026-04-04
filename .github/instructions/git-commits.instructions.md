---
description: "Use when committing changes to the SCALPER-AI project. Enforces CHANGELOG.md logging and git_helper usage."
---

# Git & Changelog Rules

## Every commit must:

1. Have a descriptive message prefixed with `[SCALPER-AI]`
2. Append an entry to `CHANGELOG.md` with UTC timestamp
3. Stage changed files + CHANGELOG.md
4. Push to origin/main

## Use `utils/git_helper.py`:

```python
from utils.git_helper import log_and_commit
log_and_commit("Implemented feature X", ["path/to/file1.py", "path/to/file2.py"])
```

## CHANGELOG format:

```markdown
## [2025-01-15 14:32 UTC]
Description of change
Files: path/to/changed/files
```

## Rules:
- One concern per commit — don't batch unrelated changes
- Commit after implementing each feature/fix/tune
- Never commit `.env`, `__pycache__`, `node_modules`, or `.db` files
