"""Resume support for the full-collection scripts.

A checkpoint records the scraped_at timestamp for the in-progress snapshot
and the last page successfully written to SQLite, so a run interrupted by
a crash, a Ctrl-C, or the server refusing to unblock after max_retries can
pick up from where it left off instead of re-fetching from page 1 and
doubling the load on the server.
"""

import json
from pathlib import Path
from typing import Optional


def load_checkpoint(path) -> Optional[dict]:
    p = Path(path)
    if not p.exists():
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def save_checkpoint(path, data: dict) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def clear_checkpoint(path) -> None:
    p = Path(path)
    if p.exists():
        p.unlink()
