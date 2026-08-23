"""Report or enforce the Cloud V1 composition gate."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from dotmac_cloud.composition import (
    CompositionBlocked,
    CompositionReport,
    evaluate,
    require_production_ready,
)


def _payload(report: CompositionReport) -> dict[str, object]:
    return {
        "ready": report.ready,
        "component_count": len(report.components),
        "blockers": [
            {
                "distribution": blocker.distribution,
                "code": blocker.code,
            }
            for blocker in report.blockers
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", dest="as_json")
    parser.add_argument("--require-ready", action="store_true")
    args = parser.parse_args(argv)

    report = evaluate()
    if args.as_json:
        print(json.dumps(_payload(report), indent=2, sort_keys=True))
    else:
        state = "ready" if report.ready else "blocked"
        print(f"Cloud V1 composition: {state}")
        for blocker in report.blockers:
            print(f"- {blocker.distribution}: {blocker.code}")

    if args.require_ready:
        try:
            require_production_ready(report)
        except CompositionBlocked:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
