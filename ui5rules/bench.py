"""Runs a rule on every scenario and builds the failure report a repair is asked from."""
from __future__ import annotations

from playwright.sync_api import Browser

from . import oracle
from .engine import run_rule
from .rules import sha256
from .validator import validate

# Each scenario: an app version (SAP release, and our variant of 1.154.0), a category, a role.
# "seen": the model may see its failures.  "held_out": never shown to the model.
# round 1 = written before the first rule; round 2 = written after reading it; "sap" = SAP's own
# published releases of the same demo, unmodified.
def S(id_, variant, version, code, role, origin):
    return {"id": id_, "variant": variant, "version": version, "category": code, "role": role, "origin": origin}


SCENARIOS = [
    S("base", "base", "1.154.0", "LT", "seen", "sap"),
    S("reordered", "reordered", "1.154.0", "LT", "seen", "round 1"),
    S("shipping_attribute", "shipping_attribute", "1.154.0", "LT", "seen", "round 1"),
    S("shipping_banner", "shipping_banner", "1.154.0", "LT", "seen", "round 1"),
    S("price_hidden", "price_hidden", "1.154.0", "LT", "seen", "round 1"),
    S("delivered_price", "delivered_price", "1.154.0", "LT", "seen", "round 2"),
    S("sap_1.96.0", "base", "1.96.0", "LT", "seen", "sap"),
    S("base_mice", "base", "1.154.0", "MI", "held_out", "sap"),
    S("shipping_banner_mice", "shipping_banner", "1.154.0", "MI", "held_out", "round 1"),
    S("delivered_price_mice", "delivered_price", "1.154.0", "MI", "held_out", "round 2"),
    S("sap_1.96.0_mice", "base", "1.96.0", "MI", "held_out", "sap"),
    S("sap_1.120.30", "base", "1.120.30", "LT", "held_out", "sap"),
    S("sap_1.148.0", "base", "1.148.0", "LT", "held_out", "sap"),
]
# What a correct system does: export every price exactly, or hold every record (price not on screen).
EXPECT = {"price_hidden": "hold_all"}


def new_page(browser: Browser):
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, locale="en-US", timezone_id="UTC")
    return ctx, ctx.new_page()


def run_scenario(browser: Browser, local, rule: dict, sc: dict) -> dict:
    variant, code = sc["variant"], sc["category"]
    ctx, page = new_page(browser)
    try:
        run = run_rule(page, local.url(variant, sc["version"]), rule, {"category": oracle.category_name(code)})
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
    return {**sc, "category_name": oracle.category_name(code),
            "expect": expect, "ok": ok, "run": run, "validator": report, "bench": score}


def run_all(browser: Browser, local, rule: dict, only=None) -> list[dict]:
    return [run_scenario(browser, local, rule, sc) for sc in SCENARIOS if not only or sc["id"] in only]


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
            "scenario": r["id"],
            "app_version": f"OpenUI5 {r['version']}" + ("" if r["variant"] == "base" else f", modified copy '{r['variant']}'"),
            "category": r["category_name"],
            "expected_behaviour": "hold every record for review: the product price is not on screen"
            if r["expect"] == "hold_all" else "export every product with its exact price",
            "runtime_validator": {"status": v["status"], "record_issues": rec_issues, "batch_issues": [
                {k: (i[k].split(":")[0] if i["kind"] == "engine_error" and k == "detail" else i[k]) for k in i}
                for i in v["batch_issues"]]},
            "known_good_check": {
                "note": "comparison with reference records kept by the bench; reference values are withheld",
                "records_expected": b["expected_n"], "records_exported": b["exported_n"],
                "exported_but_wrong": wrong,
                "missing_ids": b["missing"], "unexpected_ids": b["unexpected"], "duplicated_ids": b["duplicated"],
            },
        })
    return {"rule_sha256": sha256(rule), "failing_scenarios": scen}
