"""(B) The demo's oracle: SAP's own mock data, pinned at OpenUI5 1.154.0.

Only the bench reads this file.  The agent, the engine and the validator never do.  Records are
joined on ProductId (taken from the URL the visible click led to), never on position.  Prices are
compared as decimals, currency separately, availability as SAP's status code.
"""
from __future__ import annotations

import json
from collections import Counter
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCK = ROOT / "copy/sdk/1.154.0/test-resources/sap/m/demokit/cart/webapp/localService/mockdata"
FIELDS = {"price": "Price", "currency": "CurrencyCode", "availability": "Status"}


def load_products() -> list[dict]:
    return json.loads((MOCK / "Products.json").read_text(encoding="utf-8"))


def category_name(code: str) -> str:
    cats = json.loads((MOCK / "ProductCategories.json").read_text(encoding="utf-8"))
    return next(c["CategoryName"] for c in cats if c["Category"] == code)


def expected(code: str) -> dict[str, dict]:
    return {p["ProductId"]: p for p in load_products() if p["Category"] == code}


def _same(field: str, got, want) -> bool:
    if got is None:
        return False
    if field == "price":
        return Decimal(str(got)) == Decimal(str(want))
    return str(got) == str(want)


def score(code: str, report: dict) -> dict:
    """Compares the validator's report (exported and held records) with SAP's data."""
    exp = expected(code)
    seen = [r["key"] for r in report["records"] if r["key"] is not None]
    counts = Counter(seen)
    exported = {r["key"]: r for r in report["exported"]}
    rows = []
    price_exact = wrong_accepted = 0
    for pid in sorted(exp):
        want = exp[pid]
        got = exported.get(pid)
        row = {"product_id": pid, "name": want["Name"], "exported": got is not None,
               "expected": {f: want[src] for f, src in FIELDS.items()},
               "got": {f: (got or {}).get(f) for f in FIELDS}}
        if got is not None:
            bad = [f for f, src in FIELDS.items() if not _same(f, got.get(f), want[src])]
            row["wrong_fields"] = bad
            if "price" not in bad and "currency" not in bad:
                price_exact += 1
            if bad:
                wrong_accepted += 1
        else:
            held = next((r for r in report["records"] if r["key"] == pid), None)
            row["wrong_fields"] = []
            row["held_raw"] = held["raw"] if held else None
        rows.append(row)
    return {
        "category": code,
        "expected_n": len(exp),
        "price_exact_n": price_exact,
        "exported_n": len(exported),
        "held_for_review_n": report["review_n"],
        "wrong_accepted_n": wrong_accepted,
        "missing": sorted(set(exp) - set(seen)),
        "unexpected": sorted(set(seen) - set(exp)),
        "duplicated": sorted(k for k, c in counts.items() if c > 1),
        "rows": rows,
    }
