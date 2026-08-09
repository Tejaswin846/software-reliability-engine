from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from reliability_platform.core import ReliabilityPlatform


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail CI when reliability metrics violate release thresholds."
    )
    parser.add_argument(
        "metrics", type=Path, help="JSON file containing release metrics"
    )
    parser.add_argument("--thresholds", type=Path, help="Optional JSON threshold file")
    arguments = parser.parse_args()
    metrics: dict[str, Any] = json.loads(arguments.metrics.read_text(encoding="utf-8"))
    thresholds = (
        json.loads(arguments.thresholds.read_text(encoding="utf-8"))
        if arguments.thresholds
        else None
    )
    result = ReliabilityPlatform.ci_gate(metrics, thresholds)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
