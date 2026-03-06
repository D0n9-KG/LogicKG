import json
import sys
from pathlib import Path

# Allow running as a script: `python scripts/run_ingest.py ..`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingest.pipeline import ingest_path


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else ".."
    res = ingest_path(root)
    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
