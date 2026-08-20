"""L2 Part 2 - Related-message grouping.

A *group* is the full message thread of one canonical item (task or
event). Messages are joined to a group by meaning and chronology, never by
a single shared keyword alone: the L2 core first resolves *what* a message
is about (canonical subject), then the group gathers every message that
resolves to the same subject in timestamp order.

One thread shows the full lifecycle: original request -> follow-ups ->
deadline changes -> completion/cancellation. A group whose subject could
not be identified with high confidence is marked `uncertain`; the summary
is generated from the item's recorded event timeline, so it is always
explainable.
"""

from __future__ import annotations

from typing import Dict, List

from .common import first_upper
from .l2_core import ItemRegistry


def _bulletize(item: Dict, message_count: int) -> List[str]:
    bullets = []
    if item["status_history"]:
        for entry in item["status_history"][-6:]:
            when = entry.get("timestamp", "")[:10]
            bullets.append(
                f"{when} {entry['message_id']} -> status "
                f"'{entry['status']}' ({entry.get('reason', '')})")
    for entry in item["deadline_history"][-4:]:
        if entry.get("kind") == "time":
            bullets.append(
                f"{entry.get('timestamp', '')[:10]} {entry['message_id']} -> "
                f"time set to {entry['to']}")
        else:
            bullets.append(
                f"{entry.get('timestamp', '')[:10]} {entry['message_id']} -> "
                f"deadline {entry.get('from')} -> {entry.get('to')}")
    for conf in item.get("conflicts", [])[-3:]:
        bullets.append(
            f"{conf.get('timestamp', '')[:10]} {conf['message_id']} -> "
            f"conflict: {conf.get('notes', '')}")
    return bullets


def build_groups(registry: ItemRegistry, message_meta: Dict[str, Dict],
                 demo_ids: set) -> List[Dict]:
    """Materialise one group record per canonical item, in creation order.

    `message_meta` maps message_id -> {timestamp, sender, category,
    masked, key, priority, ...} so the group can reference masked text
    without touching raw values.
    """
    groups = []
    for seq, key in enumerate(registry.order, start=1):
        item = registry.items[key]
        d = item.to_dict()
        message_ids = list(item.message_ids)
        demo_touched = bool(set(message_ids) & demo_ids)

        summary_parts = []
        if d["source_message_id"]:
            src_ts = message_meta.get(d["source_message_id"], {}).get(
                "timestamp", "")
            summary_parts.append(
                f"First mentioned in {d['source_message_id']} "
                f"({src_ts[:10]}).")
        if len(message_ids) > 1:
            summary_parts.append(
                f"The thread contains {len(message_ids)} messages in "
                f"chronological order.")
        bullets = _bulletize(d, len(message_ids))
        if bullets:
            summary_parts.append("Timeline: " + "; ".join(bullets))
        if not bullets and message_ids:
            summary_parts.append(
                "No status or deadline changes were recorded; the item has "
                "not been updated since it was created.")

        groups.append({
            "group_id": f"GROUP_{seq:03d}",
            "title": first_upper(d["title"]),
            "canonical_key": d["key"],
            "item_type": d["type"],
            "related_message_ids": message_ids,
            "related_item_ids": d["related_item_ids"],
            "item_id": d["item_id"],
            "status": d["status"],
            "latest_deadline": d["latest_deadline"],
            "latest_time": d["latest_time"],
            "summary": " ".join(summary_parts),
            "confidence": d["resolution_confidence"],
            "conflicts": len(d["conflicts"]),
            "demo_touched": demo_touched,
        })
    return groups