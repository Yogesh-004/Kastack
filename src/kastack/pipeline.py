"""Pipeline orchestration: message order -> Part1 -> Part2 -> Part3.

All output files contain only *masked* message text; raw sensitive values
never reach logs, files or the web UI.
"""

from __future__ import annotations

import csv
import json
import os
from collections import Counter
from typing import Dict, List

from .classifier import classify
from .common import display_text
from .extractor import extract
from .sensitive import detect_sensitive, mask_message
from .sensitive import build_records


def load_messages(csv_path: str) -> List[Dict[str, str]]:
    """Load the dataset and sort messages chronologically (stable order)."""
    rows = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            rows.append({
                "message_id": row["message_id"].strip(),
                "timestamp": row["timestamp"].strip(),
                "sender": row["sender"].strip(),
                "message": row["message"].strip(),
            })
    rows.sort(key=lambda r: (r["timestamp"], r["message_id"]))
    return rows


def load_mandatory_ids(csv_path: str) -> List[str]:
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return [row["message_id"].strip() for row in reader]


def run_pipeline(messages: List[Dict[str, str]],
                 mandatory_ids: List[str]) -> Dict[str, List]:
    """Process every message in chronological order.

    Returns {classification, tasks_events, sensitive, mandatory}.
    """
    classification: List[Dict] = []
    tasks_events: List[Dict] = []
    sensitive: List[Dict] = []
    mandatory_rows: List[Dict] = []

    task_no = 0
    event_no = 0
    mandatory_set = set(mandatory_ids)

    for row in messages:
        mid = row["message_id"]
        text = row["message"]
        ts = row["timestamp"]
        sender = row["sender"]

        # Part 3 first: one detection pass, one masking pass per message.
        raw_detections = detect_sensitive(text)
        secrets = [d["secret"] for d in raw_detections]
        masked_text = display_text(mask_message(text, secrets))
        detections = build_records(mid, text)

        # Part 1 (sensitive flag steers the classifier).
        result = classify(text, sender, sensitive_detected=bool(raw_detections))

        # Part 2.
        items = extract(mid, text, sender, ts, result["category"])

        entry = {
            "message_id": mid,
            "timestamp": ts,
            "sender": sender,
            "category": result["category"],
            "confidence": result["confidence"],
            "uncertain": result["uncertain"],
            "reason": result["reason"],
            "message_masked": masked_text,
            "is_mandatory": mid in mandatory_set,
        }
        classification.append(entry)

        for item in items:
            task_no, event_no = _assign_item_id(item, task_no, event_no)
            item["description"] = masked_text
            for key in ("description",):
                if isinstance(item.get(key), str):
                    item[key] = display_text(item[key])
            tasks_events.append(item)

        sensitive.extend(detections)

        if mid in mandatory_set:
            mandatory_rows.append({
                "message_id": mid,
                "timestamp": ts,
                "sender": sender,
                "message_masked": masked_text,
                "classification": {
                    "category": result["category"],
                    "confidence": result["confidence"],
                    "uncertain": result["uncertain"],
                    "reason": result["reason"],
                },
                "items": items,
                "sensitive": detections,
            })

    return {
        "classification": classification,
        "tasks_events": tasks_events,
        "sensitive": sensitive,
        "mandatory": mandatory_rows,
    }


def _assign_item_id(item: Dict, task_no: int, event_no: int):
    if item["type"] == "task":
        task_no += 1
        item["item_id"] = f"TASK_{task_no:03d}"
    else:
        event_no += 1
        item["item_id"] = f"EVENT_{event_no:03d}"
    return task_no, event_no


def write_outputs(processed: Dict[str, List], out_dir: str,
                  mandatory_ids: List[str]) -> Dict[str, int]:
    """Write the JSON/CSV deliverables and return summary counters."""
    os.makedirs(out_dir, exist_ok=True)

    classification = processed["classification"]
    tasks_events = processed["tasks_events"]
    sensitive = processed["sensitive"]
    mandatory = processed["mandatory"]

    def dump(name: str, data) -> None:
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)

    dump("classification.json", classification)
    dump("tasks_events.json", tasks_events)
    dump("sensitive_detections.json", sensitive)
    dump("mandatory_results.json", mandatory)

    # CSV convenience copies of the same (masked) data
    with open(os.path.join(out_dir, "classification.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["message_id", "timestamp", "sender", "category",
                            "confidence", "uncertain", "reason",
                            "message_masked", "is_mandatory"])
        writer.writeheader()
        writer.writerows(classification)

    with open(os.path.join(out_dir, "tasks_events.csv"), "w", newline="",
              encoding="utf-8") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["item_id", "type", "title", "description",
                            "deadline", "time", "person", "priority",
                            "location", "notes", "source_message_id"])
        writer.writeheader()
        for item in tasks_events:
            writer.writerow({k: json.dumps(v) if isinstance(v, list)
                             else v for k, v in item.items()})

    stats = {
        "total_messages": len(classification),
        "categories": dict(Counter(c["category"] for c in classification)),
        "uncertain_count": sum(1 for c in classification if c["uncertain"]),
        "tasks": sum(1 for it in tasks_events if it["type"] == "task"),
        "events": sum(1 for it in tasks_events if it["type"] == "event"),
        "unresolved_dates": sum(
            1 for it in tasks_events if it["deadline"] == "unresolved"),
        "sensitive_messages": len(sensitive),
        "sensitive_by_risk": dict(Counter(s["risk"] for s in sensitive)),
        "sensitive_by_type": dict(
            Counter(s["sensitivity_type"] for s in sensitive)),
        "mandatory_ids_found": len(
            [m for m in mandatory if m["message_id"]]),
        "mandatory_missing": sorted(
            set(mandatory_ids) - {m["message_id"] for m in mandatory}),
    }
    dump("summary.json", stats)
    return stats