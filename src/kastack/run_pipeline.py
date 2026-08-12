"""Command-line entry point.

Usage:
    python -m kastack.run_pipeline data/messages.csv data/mandatory_demo_ids.csv outputs/

Prints only masked content (no raw sensitive values ever appear in logs).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from .pipeline import (
    load_mandatory_ids,
    load_messages,
    run_pipeline,
    write_outputs,
)


def _masked(value: str) -> str:
    return value


def main(argv=None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if len(argv) != 3:
        print("Usage: python -m kastack.run_pipeline "
              "<messages.csv> <mandatory_ids.csv> <output_dir>")
        return 2

    messages_path, mandatory_path, out_dir = map(Path, argv)

    print(f"[1/4] Loading {messages_path} ...")
    messages = load_messages(str(messages_path))
    mandatory_ids = load_mandatory_ids(str(mandatory_path))
    print(f"      {len(messages)} messages, "
          f"{len(mandatory_ids)} mandatory IDs to verify")

    print("[2/4] Running classification + extraction + sensitive scan ...")
    processed = run_pipeline(messages, mandatory_ids)

    print(f"[3/4] Writing deliverables to {out_dir} ...")
    stats = write_outputs(processed, str(out_dir), mandatory_ids)

    print("[4/4] Summary")
    for key, value in stats.items():
        if key in ("categories", "sensitive_by_risk", "sensitive_by_type"):
            print(f"      {key}: {json.dumps(value)}")
        else:
            print(f"      {key}: {value}")

    print("\nMandatory IDs (masked view):")
    header = (f"{'ID':<10} {'category':<24} {'conf':<6} {'uncertain':<10} "
              f"message (masked)")
    print(header)
    print("-" * len(header))
    for row in processed["mandatory"]:
        cl = row["classification"]
        print(f"{row['message_id']:<10} {cl['category']:<24} "
              f"{cl['confidence']:<6} {str(cl['uncertain']):<10} "
              f"{row['message_masked'][:60]}")

    if stats.get("mandatory_missing"):
        print(f"\nWARNING: mandatory IDs not found: {stats['mandatory_missing']}")
        return 1
    print("\nAll {} mandatory IDs processed.".format(len(mandatory_ids)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())