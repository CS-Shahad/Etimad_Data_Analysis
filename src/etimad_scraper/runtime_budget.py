"""Shared wall-clock time budget resolution for scripts that get run both
interactively (Codespace/local - unbounded) and as a scheduled GitHub
Actions job (bounded well under the 6-hour hard cap).
"""

import os
from typing import Optional


def resolve_max_runtime_seconds(env_var: str, cfg_value) -> Optional[float]:
    """Resolves an optional time budget in seconds.

    env_var (set by the GitHub Actions workflow) takes priority over
    cfg_value (config.yaml's max_runtime_minutes, left unset for
    unbounded local/Codespace runs). Both are in minutes; None/0/unset
    means no limit.
    """
    env_value = os.environ.get(env_var)
    minutes = env_value if env_value is not None else cfg_value
    return float(minutes) * 60 if minutes else None
