"""Audit two local planner captures; no database, network or device access."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "smartbox"))
from migration_plan_audit import audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ew_capture", type=Path)
    parser.add_argument("zenai_capture", type=Path)
    args = parser.parse_args()
    try:
        captures = []
        for path in (args.ew_capture, args.zenai_capture):
            with path.open("rb") as stream:
                raw = stream.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError("Capture exceeds size limit")
            captures.append(json.loads(raw.decode("utf-8")))
        result = audit(*captures)
    except (OSError, ValueError, TypeError, KeyError, OverflowError, RecursionError):
        parser.error("Invalid or unsupported migration captures; check the documented capture contract")
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
