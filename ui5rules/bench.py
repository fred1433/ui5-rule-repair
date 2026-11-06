"""Runs a rule on every scenario and builds the failure report a repair is asked from."""
from __future__ import annotations

from playwright.sync_api import Browser

from . import oracle
from .engine import run_rule
from .rules import sha256
from .validator import validate

# (variant, category code, role).  "held_out" scenarios are never shown to the model.
SCENARIOS = [
    ("base", "LT", "seen"),
    ("reordered", "LT", "seen"),
    ("shipping_attribute", "LT", "seen"),
    ("shipping_banner", "LT", "seen"),
    ("price_hidden", "LT", "seen"),
    ("base", "MI", "held_out"),
    ("shipping_banner", "MI", "held_out"),
]
# What a correct system does in each variant: export every price exactly, or hold every record.
EXPECT = {"price_hidden": "hold_all"}


def new_page(browser: Browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US", timezone_id="UTC")
    return ctx, ctx.new_page()


def run_scenario(browser: Browser, local, rule: dict, variant: str, code: str) -> dict:
    ctx, page = new_page(browser)
    try:
        run = run_rule(page, local.url(variant), rule, {"category": oracle.category_name(code)})
    finally:
        ctx.close()
    report = validate(rule, run)
    score = oracle.score(code, report)
    expect = EXPECT.get(variant, "export_all")
    if expect == "hold_all":
        ok = score["wrong_accepted_n"] == 0 and score["exported_n"] == 0
    else:
        ok = score["price_exact_n"] == score["expected_n"] and score["wrong_accepted_n"] == 0 \
            and not score["missing"] and not score["unexpected"] and not score["duplicated"]
    return {"variant": variant, "category": code, "category_name": oracle.category_name(code),
            "expect": expect, "ok": ok, "run": run, "validator": report, "bench": score}


def run_all(browser: Browser, local, rule: dict, only=None) -> list[dict]:
    out = []
    for variant, code, role in SCENARIOS:
        if only and (variant, code) not in only:
            continue
        r = run_scenario(browser, local, rule, variant, code)
        r["role"] = role
        out.append(r)
    return out


def failure_report(rule: dict, results: list[dict]) -> dict:
    """Deterministic summary of what failed on the scenarios the model may see.

    It holds what the page showed (raw texts, candidates) and which records the bench found
    wrong, never the reference values themselves.
    """
    scen = []
    for r in results:
        if r["role"] != "seen" or r["ok"]:
            continue
        v, b = r["validator"], r["bench"]
        rec_issues = [{"key": rec["key"], "field": i["field"], "kind": i["kind"], "detail": i["detail"],
                       **({"candidates": i["candidates"]} if i.get("candidates") else {})}
                      for rec in v["records"] for i in rec["issues"]]
        wrong = [{"product_id": row["product_id"], "fields": row["wrong_fields"],
                  "extracted": {f: row["got"][f] for f in row["wrong_fields"]}}
                 for row in b["rows"] if row["exported"] and row["wrong_fields"]]
        scen.append({
            "variant": r["variant"],
            "category": r["category_name"],
            "expected_behaviour": "hold every record for review: the product price is not on screen"
            if r["expect"] == "hold_all" else "export every product with its exact price",
            "runtime_validator": {"status": v["status"], "batch_issues": v["batch_issues"], "record_issues": rec_issues},
            "known_good_check": {
                "note": "comparison with reference records kept by the bench; reference values are withheld",
                "records_expected": b["expected_n"], "records_exported": b["exported_n"],
                "exported_but_wrong": wrong,
                "missing_ids": b["missing"], "unexpected_ids": b["unexpected"], "duplicated_ids": b["duplicated"],
            },
        })
    return {"rule_sha256": sha256(rule), "failing_scenarios": scen}
