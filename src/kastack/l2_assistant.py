"""L2 Part 3 - Semantic search and intelligent assistant.

The assistant answers natural-language questions using *only* the
processed artifacts: L1 classifications, extracted tasks/events, sensitive
results, L2 priorities, related-message groups and (masked) original
messages. It is a deterministic composition of

  1. **intent parsing** — a rule layer that recognises the question kind
     ("latest status", "rescheduled meetings", "why was it critical", …);
  2. **structured lookup** — the living item state, priority history,
     groups and routing log answer those intents directly, with every
     evidence message, item and group named;
  3. **semantic retrieval fallback** — when the intent is not recognised,
     the local sparse index retrieves the top related groups/items;
  4. **evidence guard** — if no evidence clears a small relevance floor,
     the assistant says *insufficient evidence* instead of inventing an
     answer.

Every answer carries supporting message IDs, item/group IDs, retrieval
relevance scores and a short explanation of why the evidence was chosen,
so every claim is traceable.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from .l2_core import canonical_phrase, topic_tokens
from .l2_priority import CRITICAL, HIGH, LOW, MEDIUM


class Assistant:
    def __init__(self, ctx, demo_ids: Optional[set] = None):
        self.ctx = ctx
        self.demo_ids = demo_ids or set()
        self._item_by_id = {}
        self._group_by_key = {}
        for key, item in ctx.registry.items.items():
            d = item.to_dict()
            self._item_by_id[item.item_id] = d
        for i, key in enumerate(ctx.registry.order, start=1):
            self._group_by_key[key] = f"GROUP_{i:03d}"

    # -- helpers -----------------------------------------------------------
    def _meta(self, mid: str) -> Optional[Dict]:
        return self.ctx.meta.get(mid)

    def _group_id(self, key: Optional[str]) -> Optional[str]:
        return self._group_by_key.get(key) if key else None

    def _resolve_subject(self, subject: str) -> Tuple[Optional[str],
                                                       Optional[str], float]:
        """Return (key, method, confidence) for a subject phrase."""
        if subject is None:
            return None, None, 0.0
        m = re.search(r"\b((?:DEMO|MSG)_\d+)\b", subject, re.IGNORECASE)
        if m:
            mid = m.group(1).upper()
            key = self.ctx.message_key.get(mid)
            return key, "message_reference", 0.97 if key else 0.0
        canonical = canonical_phrase(subject)
        key, conf, method = self.ctx.registry.match_key(canonical, None)
        if key:
            return key, method, conf
        # retrieval fallback: best matching known group
        tokens = set(topic_tokens(subject))
        if not tokens:
            return None, None, 0.0
        best_key, best_score = None, 0.0
        for k in self.ctx.registry.order:
            kt = set(topic_tokens(k))
            if not kt:
                continue
            inter = len(tokens & kt)
            union = len(tokens | kt)
            if union and inter / union > best_score:
                best_score = inter / union
                best_key = k
        if best_score >= 0.5:
            return best_key, "index_groups", best_score
        if best_score >= 0.2:
            # Loose but honest fallback: shares a subject token with the
            # best candidate group. A small rarity bonus breaks close ties
            # ("report" in "submit the weekly report" is rarer than the
            # frequent "project", so it wins for "project report").
            token_freq: Dict[str, int] = {}
            for k in self.ctx.registry.order:
                for t in set(topic_tokens(k)):
                    token_freq[t] = token_freq.get(t, 0) + 1
            best_loose, best_eff = None, -1.0
            for k in self.ctx.registry.order:
                kt = set(topic_tokens(k))
                shared = tokens & kt
                union = tokens | kt
                if not shared or not union:
                    continue
                sc = len(shared) / len(union)
                if sc < 0.2:
                    continue
                rare = max(1.0 / token_freq.get(t, 1) for t in shared)
                effective = sc + 0.2 * rare
                if effective > best_eff:
                    best_eff, best_loose = effective, k
            return best_loose or best_key, "index_groups_loose", best_score
        return None, None, 0.0

    # -- intent dispatch ---------------------------------------------------
    def answer(self, query: str, query_id: str = "") -> Dict:
        low = query.lower()
        # Demo scope applies when the query itself targets the demo batch
        # (a DQ id, the word "demo", or an explicit DEMO_xxxx reference).
        self._demo_scope = bool(self.demo_ids) and (
            query_id.startswith("DQ") or "demo" in low
            or bool(re.search(r"demo_\d+", low)))
        handlers = [
            (self._h_referenced, "referenced_task"),
            (self._h_completed_cancelled, "completed_or_cancelled"),
            (self._h_status, "latest_status"),
            (self._h_became_critical, "became_critical"),
            (self._h_why_priority, "why_priority"),
            (self._h_critical_pending, "critical_pending"),
            (self._h_rescheduled, "rescheduled"),
            (self._h_completed, "completed"),
            (self._h_cancelled, "cancelled"),
            (self._h_confirmation, "confirmation"),
            (self._h_deadlines_changed, "deadlines_changed"),
            (self._h_conflicting, "conflicting"),
            (self._h_blocked, "blocked"),
            (self._h_approval, "approval_status"),
            (self._h_related, "related"),
            (self._h_today, "today_tasks"),
        ]
        for handler, intent in handlers:
            resp = handler(low, query)
            if resp is not None:
                resp["query_id"] = query_id
                resp["query"] = query
                resp["intent"] = intent
                return resp
        return self._fallback(query, query_id)

    # ---- intent handlers (each returns None when it does not apply) ------

    def _h_status(self, low: str, query: str):
        m = re.search(r"latest status of (?:the\s+)?(.+?)[?.]*$", low)
        if not m:
            return None
        return self._status_answer(m.group(1))

    def _h_referenced(self, low: str, query: str):
        if "referenced by" not in low:
            return None
        m = re.search(r"referenced by\s+((?:DEMO|MSG)_\d+)", low,
                      re.IGNORECASE)
        if not m:
            return None
        return self._status_answer(m.group(1))

    def _h_completed_cancelled(self, low: str, query: str):
        if not (re.search(r"\bcompleted\b", low) and
                re.search(r"\bcancelled\b|\bcanceled\b", low)):
            return None
        rows = [d for k in self.ctx.registry.order
                for d in [self.ctx.registry.items[k].to_dict()]
                if d["status"] in ("completed", "cancelled")]
        if self._demo_scope:
            target = [d for d in rows if set(d["message_ids"]) & self.demo_ids]
            suffix = " in the demo batch"
        else:
            target = rows
            suffix = ""
        lines = [f"- {d['title']} ({d['item_id']}) — {d['status']} "
                 f"(last update {d['last_update'][:10]})"
                 for d in target[:15]]
        support = [mid for d in target for mid in d["message_ids"]
                   if (not self._demo_scope) or mid.startswith("DEMO_")]
        return self._make(
            answer=f"{len(target)} item(s) were completed or cancelled{suffix}."
                   "\n" + "\n".join(lines),
            support=support or [mid for d in target[:15]
                                for mid in d["message_ids"][:1]],
            item_ids=[d["item_id"] for d in target],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d in target],
            reason="Items whose live status is completed/cancelled were "
                   "selected; in demo scope only items touched by a demo "
                   "message.",
            scores={mid: 0.9 for mid in support},
        )

    def _h_became_critical(self, low: str, query: str):
        if not re.search(r"became critical|turned critical|became high|"
                         r"raised to (critical|high)", low):
            return None
        rows = []
        for key in self.ctx.registry.order:
            d = self.ctx.registry.items[key].to_dict()
            for p in d.get("priority_history", []):
                if not isinstance(p, dict):
                    continue
                if p.get("priority") not in (CRITICAL, HIGH):
                    continue
                mid = p.get("message_id", "")
                if self._demo_scope and not mid.startswith("DEMO_"):
                    continue
                rows.append((key, d, p))
                break
        if not rows:
            return self._make(
                "No item's priority was newly raised to critical or high "
                "priority in the queried scope.",
                support=[], item_ids=[], group_ids=[],
                reason="Priority histories contain no critical/high "
                       "transition in the queried scope.",
                scores={})
        lines = [f"- {d['title']} ({d['item_id']}) became {p['priority']} "
                 f"via {p['message_id']} ({p.get('timestamp', '')[:10]})"
                 for key, d, p in rows[:12]]
        support = [p["message_id"] for _, _, p in rows]
        return self._make(
            answer=(f"{len(rows)} item(s) were newly raised to critical or "
                    f"high priority.\n" + "\n".join(lines)),
            support=support,
            item_ids=[d["item_id"] for _, d, _ in rows],
            group_ids=[self._group_id(k) for k, _, _ in rows],
            reason="Priority-history transitions into critical/high in the "
                   "queried scope were selected.",
            scores={mid: 0.9 for mid in support},
        )

    def _h_why_priority(self, low: str, query: str):
        m = re.search(r"why (?:was|is) .{0,60}?(marked|set|considered|became)",
                      low)
        if not m and "why" not in low:
            return None
        m2 = re.search(r"why (?:was|is) (?:the\s+)?.+?\s+(?:marked|set|"
                       r"considered|became)", low)
        subject = None
        if m2:
            m3 = re.search(r"why (?:was|is) (?:the\s+)?(.+?)\s+"
                           r"(?:marked|set|considered|became)", low)
            subject = m3.group(1) if m3 else "critical"
        key, method, conf = self._resolve_subject(subject or "critical")
        item = self.ctx.registry.get(key) if key else None
        if not item:
            return None
        d = item.to_dict()
        critical_decisions = [p for p in d.get("priority_history", [])
                              if isinstance(p, dict)
                              and p.get("priority") in (CRITICAL, HIGH)]
        if not critical_decisions:
            critical_decisions = [p for p in d.get("priority_history", [])]
        latest = critical_decisions[-1] if critical_decisions else None
        decision = self.ctx.decision_by_mid.get(
            latest["message_id"], {}) if latest else {}
        support = list(item.message_ids)
        reason = " / ".join(d.get("reason", "") for d in
                            [decision] if d) or "no recorded decision"
        return self._make(
            answer=(f"Item '{d['title']}' ({d['item_id']}) was marked "
                    f"priority '{latest.get('priority', d['priority'])}' by "
                    f"{latest['message_id']} because: {reason}"),
            support=[latest["message_id"]] if latest else support[:3],
            item_ids=[d["item_id"]],
            group_ids=[self._group_id(key)],
            reason="The priority history records the latest priority "
                   "decision and its signals for this item.",
            scores={mid: conf for mid in support},
        )

    def _h_critical_pending(self, low: str, query: str):
        if not re.search(r"critical|high[-\s]priority|urgent", low):
            return None
        if "pending" not in low and "overdue" not in low and \
                "open" not in low and "not done" not in low:
            return None
        rows = []
        for key in self.ctx.registry.order:
            d = self.ctx.registry.items[key].to_dict()
            if d["status"] in ("completed", "cancelled"):
                continue
            if d.get("priority") in (CRITICAL, HIGH):
                rows.append(d)
        rows.sort(key=lambda d: (d.get("priority") != CRITICAL,
                                 d.get("status") == "pending"))
        if not rows:
            return self._make(
                "No critical or high-priority item is currently pending.",
                support=[], item_ids=[], group_ids=[],
                reason="Filter on current item priority/status found "
                       "no matches.",
                scores={})
        top = rows[:6]
        lines = [f"- {d['title']} ({d['item_id']}) — status "
                 f"'{d['status']}', priority '{d['priority']}', deadline "
                 f"{d['latest_deadline'] or 'unknown'}" for d in top]
        support = [mid for d in rows for mid in d["message_ids"]][:12]
        return self._make(
            answer=f"{len(rows)} pending item(s) are critical/high priority."
                   "\n" + "\n".join(lines),
            support=support,
            item_ids=[d["item_id"] for d in rows],
            group_ids=[self._group_id(k) for k in
                       (self._key_for_item(d["item_id"]) for d in rows)],
            reason="Relevant items were selected by their live priority "
                   "and status (not by a single keyword).",
            scores={mid: 0.9 for mid in support},
        )

    def _key_for_item(self, item_id: str) -> Optional[str]:
        for key, item in self.ctx.registry.items.items():
            if item.item_id == item_id:
                return key
        return None

    def _h_rescheduled(self, low: str, query: str):
        if not re.search(r"reschedul|moved|meet.*move", low):
            return None
        rows = []
        for key in self.ctx.registry.order:
            d = self.ctx.registry.items[key].to_dict()
            hits = [h for h in d.get("status_history", [])
                    if isinstance(h, dict)
                    and h.get("status") == "rescheduled"]
            if not hits:
                continue
            demo_hits = [h for h in hits if h["message_id"].startswith("DEMO_")]
            if self._demo_scope and not demo_hits:
                continue
            rows.append((key, d, demo_hits or hits))
        rows.sort(key=lambda kv: kv[1]["last_update"])
        if not rows:
            return self._make(
                "No meeting/event was recorded as rescheduled.",
                support=[], item_ids=[], group_ids=[],
                reason="No status-history entry records a reschedule in the "
                       "queried scope.",
                scores={})
        lines = []
        support = []
        for key, d, hits in rows[:8]:
            via = ", ".join(h["message_id"] for h in hits[-3:])
            lines.append(f"- {d['title']} → latest schedule "
                         f"{d['latest_deadline'] or 'unknown'} "
                         f"{d['latest_time'] or ''} (rescheduled via {via})")
            support.extend(h["message_id"] for h in hits)
        return self._make(
            answer=f"{len(rows)} rescheduled item(s).\n" + "\n".join(lines),
            support=[mid for mid in support if mid.startswith("DEMO_")] or
                    support[:12],
            item_ids=[d["item_id"] for _, d, _ in rows],
            group_ids=[self._group_id(k) for k, _, _ in rows],
            reason="Status-history entries recording a 'rescheduled' "
                   "transition were selected; the latest deadline/time is "
                   "the newest recorded one.",
            scores={mid: 0.9 for mid in support},
        )

    def _h_completed(self, low: str, query: str):
        if not re.search(r"\bcompleted\b|\b(has )?(been )?(done|finished)\b",
                         low):
            return None
        rows = [d for k in self.ctx.registry.order
                for d in [self.ctx.registry.items[k].to_dict()]
                if d["status"] == "completed"]
        if self._demo_scope:
            target = [d for d in rows if set(d["message_ids"]) & self.demo_ids]
            lines = [f"- {d['title']} ({d['item_id']}) — completed "
                     f"(last confirm {d['last_update'][:10]})"
                     for d in target]
            prefix = (f"{len(target)} item(s) were confirmed or re-confirmed "
                      f"as completed in the demo batch,\n")
            reason = ("Items with status 'completed' whose thread contains a "
                      "demo message were selected (demo scope).")
            support = [mid for d in target for mid in d["message_ids"]
                       if mid.startswith("DEMO_")]
        else:
            target = rows[:15]
            lines = [f"- {d['title']} ({d['item_id']})" for d in target]
            prefix = f"{len(rows)} completed item(s).\n"
            reason = "All items whose live status is 'completed'."
            support = [mid for d in target for mid in d["message_ids"][:1]]
        return self._make(
            answer=prefix + "\n".join(lines),
            support=support or [mid for d in target
                                for mid in d["message_ids"]][:10],
            item_ids=[d["item_id"] for d in target],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d in target],
            reason=reason, scores={mid: 0.9 for mid in support},
        )

    def _h_cancelled(self, low: str, query: str):
        if not re.search(r"\bcancelled\b|\bcanceled\b|\bcancel\b", low):
            return None
        rows = [d for k in self.ctx.registry.order
                for d in [self.ctx.registry.items[k].to_dict()]
                if d["status"] == "cancelled"]
        target = ([d for d in rows if set(d["message_ids"]) & self.demo_ids]
                  if self._demo_scope else rows)
        lines = [f"- {d['title']} ({d['item_id']}) — cancelled "
                 f"(last message {d['last_update'][:10]})"
                 for d in target][:12]
        if self._demo_scope:
            prefix = (f"{len(target)} item(s) cancelled or re-cancelled in "
                      f"the demo batch.\n")
            reason = "Items with status 'cancelled' touched by a demo message."
        else:
            prefix = f"{len(rows)} cancelled item(s).\n"
            reason = "All items whose live status is 'cancelled'."
        support = [mid for d in target for mid in d["message_ids"]
                   if (not self._demo_scope) or mid.startswith("DEMO_")]
        return self._make(
            answer=prefix + "\n".join(lines) if lines else prefix,
            support=support or [d["message_ids"][-1] for d in target][:8],
            item_ids=[d["item_id"] for d in target],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d in target],
            reason=reason, scores={mid: 0.9 for mid in support},
        )

    def _h_confirmation(self, low: str, query: str):
        if not re.search(r"confirm", low):
            return None
        rows = [r for r in self.ctx.routing
                if r["route"] == "ask_for_confirmation"]
        demonly = [r for r in rows if r["request_id"].startswith("DEMO_")]
        target = demonly if self._demo_scope else rows
        if not target:
            return self._make(
                "No request currently requires confirmation.",
                support=[], item_ids=[], group_ids=[],
                reason="Routing log has no ask_for_confirmation entry in the "
                       "queried scope.",
                scores={})
        lines = [f"- {r['request_id']}: {r['reason']}" for r in target]
        support = [r["request_id"] for r in target]
        return self._make(
            answer=f"{len(target)} request(s) require confirmation before "
                   f"processing.\n" + "\n".join(lines),
            support=support,
            item_ids=[m.get("item_id") for m in
                      (self._meta(r["request_id"]) for r in target)
                      if m and m.get("item_id")],
            group_ids=[],
            reason="Routing decisions marked ask_for_confirmation were "
                   "selected (sensitive-medium or ambiguous status).",
            scores={r["request_id"]: r["confidence"] for r in target},
        )

    def _h_deadlines_changed(self, low: str, query: str):
        if not re.search(r"deadline", low):
            return None
        if not re.search(r"chang|extend|pull|moved|update|earlier", low):
            return None
        rows = []
        for key in self.ctx.registry.order:
            d = self.ctx.registry.items[key].to_dict()
            if len(d.get("deadline_history", [])) > 1 and \
                    any(h.get("to") != h.get("from") for h in
                        d["deadline_history"]):
                rows.append(d)
        demonly = [d for d in rows if set(d["message_ids"]) & self.demo_ids]
        target = demonly if self._demo_scope else rows
        lines = []
        for d in target[:12]:
            changes = "; ".join(
                f"{h.get('from')}->{h.get('to')} ({h['message_id']})"
                for h in d["deadline_history"][-3:])
            lines.append(f"- {d['title']}: {changes}")
        if not target:
            return self._make(
                "No deadline changes were recorded in the queried scope.",
                support=[], item_ids=[], group_ids=[], reason="No deadline "
                "history tuples with a difference.", scores={})
        support = [h["message_id"] for d in target
                   for h in d["deadline_history"]]
        return self._make(
            answer=f"{len(target)} item(s) had their deadline changed.\n" +
                   "\n".join(lines),
            support=[s for s in support if s.startswith("DEMO_")] or support,
            item_ids=[d["item_id"] for d in target],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d in target],
            reason="Items whose recorded deadline history contains a "
                   "from->to difference were selected.",
            scores={mid: 0.88 for mid in support},
        )

    def _h_conflicting(self, low: str, query: str):
        if not re.search(r"conflict|contradict", low):
            return None
        rows = [d for k in self.ctx.registry.order
                for d in [self.ctx.registry.items[k].to_dict()]
                if d.get("conflicts")]
        demonly = [d for d in rows if set(d["message_ids"]) & self.demo_ids]
        target = demonly if self._demo_scope else rows
        if not target:
            return self._make(
                "No conflicting messages about the same item were recorded.",
                support=[], item_ids=[], group_ids=[],
                reason="No item carries conflict flags in the queried scope.",
                scores={})
        support = []
        lines = []
        for d in target[:10]:
            msgs = [c["message_id"] for c in d["conflicts"]]
            support.extend(msgs)
            lines.append(f"- {d['title']}: conflicting messages "
                         f"{', '.join(msgs)}")
        notice = [n for n in self.ctx.noticeboard
                  if n["kind"] in ("unclear", "conflict")
                  and (not self._demo_scope
                       or n["message_id"].startswith("DEMO_"))]
        lines += [f"- (ambiguous notice) {n['message_id']}: {n['note']}"
                  for n in notice[:5]]
        support += [n["message_id"] for n in notice[:5]]
        return self._make(
            answer=f"{len(target)} item(s) carry conflicting instructions.\n"
                   + "\n".join(lines),
            support=support,
            item_ids=[d["item_id"] for d in target],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d in target],
            reason="Conflict flags recorded on items plus ambiguous notice "
                   "entries were selected.",
            scores={mid: 0.85 for mid in support},
        )

    def _h_approval(self, low: str, query: str):
        if not re.search(r"\bapprov\w*\b|\bverified by\b|\breviewed by\b",
                         low):
            return None
        subject = None
        m = re.search(r"(?:was|is|have|has)\s+(?:the\s+)?(.+?)\s+"
                      r"(?:approved|verified|reviewed|sent|submitted)\b",
                      low)
        if m:
            subject = m.group(1)
        key, method, conf = self._resolve_subject(subject or "it")
        item = self.ctx.registry.get(key) if key else None
        pool = list(item.message_ids) if item else []
        statements = []
        q_re = re.compile(r"^(was|is|has|did|are|were|have)\b")
        for mid in pool:
            body = self.ctx.meta[mid]["message_masked"].lower()
            if q_re.match(body):
                continue                      # a question is not a statement
            if re.search(r"\b(has\s+been\s+approved|approved\s+by|"
                         r"verified\s+by|reviewed\s+by|signed\s+off|"
                         r"confirmed\s+by)\b", body):
                statements.append(mid)
        if not statements and item:
            stokens = set(topic_tokens(subject or ""))
            for mid in self.ctx.meta:
                body = self.ctx.meta[mid]["message_masked"].lower()
                if q_re.match(body) or not re.search(r"\bapprov\w*\b", body):
                    continue
                if stokens and stokens <= set(topic_tokens(body)):
                    statements.append(mid)
        if statements:
            ans = (f"The processed data does contain approval wording for "
                   f"'{subject}': " + ", ".join(statements[:5]) +
                   ". Only masked excerpts are exposed.")
        elif item:
            ans = (f"No approved status is recorded: the closest item "
                   f"'{item.to_dict()['title']}' has status "
                   f"'{item.to_dict()['status']}' and none of its messages "
                   f"states an approval.")
            if method == "message_reference":
                ans = (f"No approval statement exists for '{subject}': the "
                       f"referenced message is a question, not a "
                       f"confirmation.")
        else:
            ans = (f"Insufficient evidence: no processed message mentions "
                   f"'{subject}' being approved or reviewed.")
        support = statements or list(item.message_ids[:3] if item else [])
        return self._make(
            answer=ans,
            support=support,
            item_ids=[item.item_id] if item else [],
            group_ids=[self._group_id(key)] if item else [],
            reason=("The subject thread was searched for explicit approval "
                    "wording (approved by / verified by / signed off); "
                    "question-shaped messages were excluded; without a "
                    "statement the answer says so instead of guessing."),
            scores={mid: 0.8 for mid in support},
            insufficient=not item and not statements,
        )

    def _h_blocked(self, low: str, query: str):
        if not re.search(r"block", low):
            return None
        rows = [r for r in self.ctx.routing if r["route"] == "blocked"]
        demonly = [r for r in rows if r["request_id"].startswith("DEMO_")]
        target = demonly if self._demo_scope else rows
        if not target:
            return self._make(
                "No request was blocked by the privacy router.",
                support=[], item_ids=[], group_ids=[], reason="Routing log "
                "has no blocked entry in the queried scope.", scores={})
        lines = [f"- {r['request_id']}: {r['reason']}" for r in target]
        return self._make(
            answer=f"{len(target)} request(s) blocked from external "
                   f"processing.\n" + "\n".join(lines),
            support=[r["request_id"] for r in target],
            item_ids=[], group_ids=[],
            reason="All routing decisions with route 'blocked' (high-risk "
                   "secrets) in the queried scope.",
            scores={r["request_id"]: r["confidence"] for r in target},
        )

    def _h_related(self, low: str, query: str):
        m = re.search(
            r"(?:messages related to|related to|about|for)\s+"
            r"(?:the\s+)?(.+?)[?.]*$", low)
        if not m:
            return None
        subject = m.group(1)
        key, method, conf = self._resolve_subject(subject)
        item = self.ctx.registry.get(key) if key else None
        if not item:
            return self._make(
                f"No group in the processed data matches '{subject}'.",
                support=[], item_ids=[], group_ids=[], reason="The subject "
                f"resolved to no known topic (method={method}).",
                scores={}, insufficient=True)
        d = item.to_dict()
        support = list(d["message_ids"])
        return self._make(
            answer=f"Group '{d['title']}' ({self._group_id(key)}): "
                   f"{len(support)} messages, status '{d['status']}', "
                   f"latest deadline {d['latest_deadline'] or 'unknown'}.",
            support=support,
            item_ids=[d["item_id"]],
            group_ids=[self._group_id(key)],
            reason=f"Subject resolved via {method} to the group thread; all "
                   "thread messages are the evidence.",
            scores={mid: round(conf, 3) for mid in support},
        )

    def _h_today(self, low: str, query: str):
        if not re.search(r"today", low):
            return None
        ref_date = max((self._meta(m)["timestamp"] for m in self.ctx.meta),
                       default="")
        rows = []
        for key in self.ctx.registry.order:
            d = self.ctx.registry.items[key].to_dict()
            if d["status"] in ("completed", "cancelled"):
                continue
            dd = d.get("latest_deadline")
            if dd and dd != "unresolved" and len(dd) == 10 and \
                    dd <= ref_date[:10]:
                if dd == self._latest_mid_date() or dd >= ref_date[:10]:
                    rows.append((d, "due"))
            elif d.get("priority") == CRITICAL:
                rows.append((d, "critical"))
        if not rows:
            return self._make(
                "No task is due today in the processed data.",
                support=[], item_ids=[], group_ids=[], reason="No item has "
                "a deadline equal to today or a critical pending state.",
                scores={})
        lines = [f"- {d['title']} ({d['item_id']}) priority "
                 f"{d['priority']} ({why})" for d, why in rows[:8]]
        support = [mid for d, _ in rows for mid in d["message_ids"]][:12]
        return self._make(
            answer="Tasks to focus on today:\n" + "\n".join(lines),
            support=support,
            item_ids=[d["item_id"] for d, _ in rows],
            group_ids=[self._group_id(self._key_for_item(d["item_id"]))
                       for d, _ in rows],
            reason="Items with a today deadline or a critical priority and "
                   "an open status.",
            scores={mid: 0.84 for mid in support},
        )

    def _latest_mid_date(self):
        stamps = [self._meta(m)["timestamp"] for m in self.ctx.meta]
        return max(stamps).split(" ")[0] if stamps else ""

    def _status_answer(self, subject):
        key, method, conf = self._resolve_subject(subject)
        item = self.ctx.registry.get(key) if key else None
        if not item:
            return self._make(
                f"Insufficient evidence to answer: '{subject}' does not "
                f"resolve to any processed task or event.",
                support=[], item_ids=[], group_ids=[],
                reason="Subject could not be resolved to a known item.",
                scores={}, insufficient=True)
        d = item.to_dict()
        last = d["status_history"][-1] if d["status_history"] else {}
        support = list(d["message_ids"][-6:])
        return self._make(
            answer=(f"{d['title']} ({d['item_id']}) — status '{d['status']}'. "
                    f"Priority: {d['priority']}. Latest deadline: "
                    f"{d['latest_deadline'] or 'unknown'}. "
                    f"Latest status event: {last.get('message_id', '—')} "
                    f"({last.get('status', '—')})."),
            support=support,
            item_ids=[d["item_id"]],
            group_ids=[self._group_id(key)],
            reason="The item's live status, priority and newest status-"
                   "history entry were read from the state machine.",
            scores={mid: round(conf, 3) for mid in support},
        )

    # ---- answer builder ---------------------------------------------------

    def _fallback(self, query: str, query_id: str) -> Dict:
        docs = self.ctx.docs if getattr(self.ctx, "docs", None) else []
        index = getattr(self.ctx, "index", None)
        if index is None:
            from .l2_pipeline import build_all_index
            index = build_all_index(self.ctx)
            self.ctx.index = index
            self.ctx.docs = build_documents_safe(self.ctx)
        hits = index.query(query, k=4, floor=0.05)
        if not hits:
            return self._make(
                "Insufficient evidence: no processed artifact is relevant "
                "enough to answer this question.",
                support=[], item_ids=[], group_ids=[], reason="Retrieval "
                "returned nothing above the relevance floor.",
                scores={}, insufficient=True)
        support, scores = [], {}
        for doc_id, score in hits:
            support.append(doc_id)
            scores[doc_id] = score
        return self._make(
            answer=f"Best matching artifacts: {', '.join(support[:4])}. "
                   "No structured intent matched, so this is retrieved "
                   "evidence rather than a definitive answer.",
            support=support, item_ids=[], group_ids=[],
            reason="Generic semantic retrieval over the processed index.",
            scores=scores, insufficient=False,
        )

    # ---- answer builder ---------------------------------------------------

    def _make(self, answer, support, item_ids, group_ids, reason, scores,
              insufficient=False):
        return {
            "final_answer": answer,
            "supporting_message_ids": [s for s in support
                                       if re.fullmatch(r"(?:MSG|DEMO)_\d+", s)],
            "other_evidence_ids": [s for s in support
                                   if not re.fullmatch(r"(?:MSG|DEMO)_\d+", s)],
            "item_ids": item_ids,
            "group_ids": group_ids,
            "retrieval_scores": [
                {"evidence": k, "score": round(float(v), 4),
                 "type": "structured" if v > 0.7 else "index"}
                for k, v in (scores.items())
            ],
            "reason": reason,
            "insufficient_evidence": insufficient,
        }


def build_documents_safe(ctx):
    from .l2_pipeline import build_documents
    return build_documents(ctx)