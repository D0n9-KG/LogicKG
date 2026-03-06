import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.rag.service import ask  # noqa: E402


def main() -> int:
    q = "What new dimensionless number do the authors define, and what is it based on?"
    res = ask(q, k=8)
    print(
        json.dumps(
            {
                "question": q,
                "answer": res["answer"],
                "evidence_count": len(res["evidence"]),
                "evidence_mode": [e.get("mode") for e in res["evidence"]],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
