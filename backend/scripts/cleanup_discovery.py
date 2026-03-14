from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest.rebuild import cleanup_legacy_discovery_artifacts


def main() -> int:
    report = cleanup_legacy_discovery_artifacts()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if bool(report.get('ok')) else 1


if __name__ == '__main__':
    raise SystemExit(main())
