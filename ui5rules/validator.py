"""(A) The runtime validator: what the agent itself can know, from the page only.

It sees the run record (what each field read on screen) and the rule's contracts.  It never sees
reference data.  So it can catch a field that is missing, ambiguous, of the wrong type, or a
count that disagrees with the screen; it cannot catch a single, well-formed, wrong amount.
"""
from __future__ import annotations

from collections import Counter


def validate(rule: dict, run: dict) -> dict:
    key = rule["key"]
    issues = [dict(i, scope="batch") for i in run["batch_issues"]]
    records = []
    for rec in run["items"]:
        rec_issues = []
        for name, fr in rec["fields"].items():
            if fr["issue"]:
                rec_issues.append({"field": name, **fr["issue"]})
        k = rec["fields"].get(key, {}).get("value")
        records.append({"index": rec["index"], "key": k, "issues": rec_issues,
                        "values": {n: fr["value"] for n, fr in rec["fields"].items()},
                        "raw": {n: fr["raw"] for n, fr in rec["fields"].items()},
                        "candidates": {n: fr["candidates"] for n, fr in rec["fields"].items() if fr.get("candidates") and len(fr["candidates"]) > 1},
                        "url_hash": rec.get("url_hash", "")})
    keys = [r["key"] for r in records if r["key"] is not None]
    dups = sorted(k for k, c in Counter(keys).items() if c > 1)
    if dups:
        issues.append({"scope": "batch", "kind": "duplicate_key", "detail": f"{len(dups)} duplicated keys", "keys": dups})
    if rule.get("count_check") and run["screen_count"] is not None and run["screen_count"] != len(records):
        issues.append({"scope": "batch", "kind": "count_mismatch",
                       "detail": f"screen shows {run['screen_count']}, extracted {len(records)}"})
    if rule.get("count_check") and run["screen_count"] is None and not run["batch_issues"]:
        issues.append({"scope": "batch", "kind": "count_unread", "detail": "no read_count step ran"})
    batch_blocked = bool(issues)
    exported, review = [], []
    for r in records:
        if r["issues"] or batch_blocked:
            review.append(r)
        else:
            exported.append(r)
    return {
        "status": "pass" if not batch_blocked and not review else "needs_review",
        "batch_issues": issues,
        "records": records,
        "exported": [{"key": r["key"], **{n: v for n, v in r["values"].items()}} for r in exported],
        "review_n": len(review),
        "screen_count": run["screen_count"],
    }
