from __future__ import annotations

import json
import os
import traceback
from typing import Any

EVENT_PREFIX = "LOGICKG_COMMUNITY_EVENT\t"


def _emit(event: dict[str, Any]) -> None:
    print(EVENT_PREFIX + json.dumps(event, ensure_ascii=False), flush=True)


def main() -> int:
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[name] = str(min(64, int(os.environ.get(name) or "64")))

    from app.community.service import rebuild_global_communities
    from app.ops_config_store import apply_profile_to_settings

    apply_profile_to_settings()

    def progress(stage: str, progress_value: float, message: str | None = None) -> None:
        _emit(
            {
                "event": "progress",
                "stage": str(stage or ""),
                "progress": float(progress_value),
                "message": None if message is None else str(message),
            }
        )

    def log(line: str) -> None:
        _emit({"event": "log", "line": str(line or "")})

    try:
        result = rebuild_global_communities(progress=progress, log=log)
    except Exception as exc:  # noqa: BLE001
        _emit(
            {
                "event": "result",
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )
        return 1

    _emit({"event": "result", "ok": True, "result": result})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
