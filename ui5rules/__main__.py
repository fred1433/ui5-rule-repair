"""Command line.

  python -m ui5rules replay     # no model, no key: re-runs browser, extraction, validation, bench
  python -m ui5rules generate   # asks the model for the first rule (needs the `claude` CLI)
  python -m ui5rules repair     # asks the model to repair the latest rule (needs the `claude` CLI)
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from . import agent, bench
from .observe import observe
from .rules import sha256
from .server import LocalCopy

ROOT = Path(__file__).resolve().parent.parent
RESULTS = ROOT / "results"


def _observe(browser, local, variant: str, version: str = "1.154.0") -> dict:
    ctx, page = bench.new_page(browser)
    try:
        return observe(page, local.url(variant, version), "Laptops")
    finally:
        ctx.close()


def _summary_rows(stage_name: str, results: list[dict]) -> list[str]:
    rows = []
    for r in results:
        b = r["bench"]
        rows.append(f"| {stage_name} | {r['id']} ({r['origin']}) | {r['category_name']}{' (held out)' if r['role'] == 'held_out' else ''} "
                    f"| {b['price_exact_n']}/{b['expected_n']} | {b['held_for_review_n']} | {b['wrong_accepted_n']} "
                    f"| {len(b['missing'])}/{len(b['unexpected'])}/{len(b['duplicated'])} "
                    f"| {'as expected' if r['ok'] else 'FAILED'} |")
    return rows


def _compact(results: list[dict]) -> list[dict]:
    out = []
    for r in results:
        out.append({k: r[k] for k in ("id", "variant", "version", "origin", "category", "category_name", "role", "expect", "ok")} | {
            "bench": r["bench"],
            "validator": {k: r["validator"][k] for k in ("status", "batch_issues", "review_n", "screen_count")}
                         | {"records": r["validator"]["records"]},
        })
    return out


def replay(write: bool = True) -> int:
    links = agent.chain()
    if not links:
        print("No recorded proposal under proposals/.")
        return 2
    stages, refused = [], None
    with LocalCopy() as local, sync_playwright() as p:
        browser = p.chromium.launch()
        rule, meta = agent.load(links[0])
        obs = _observe(browser, local, "base")
        obs_ok = sha256(obs) == meta["input_sha256"]
        print(f"{links[0].name}: observations of the app {'match' if obs_ok else 'DIFFER FROM'} the recorded ones "
              f"(sha256 {sha256(obs)[:12]})")
        if not obs_ok:
            refused = {"proposal": links[0].name, "reason": "observations differ", "expected": meta["input_sha256"], "got": sha256(obs)}
        else:
            results = bench.run_all(browser, local, rule)
            stages.append({"proposal": links[0].name, "meta": meta, "rule": rule, "results": results})
            for link in links[1:]:
                report = bench.failure_report(rule, results)
                h = sha256(report)
                new_rule, new_meta = agent.load(link)
                if h != new_meta["input_sha256"]:
                    refused = {"proposal": link.name, "reason": "failure report differs from the one the repair answered",
                               "expected": new_meta["input_sha256"], "got": h}
                    print(f"{link.name}: REFUSED, failure report sha256 {h[:12]} != recorded {new_meta['input_sha256'][:12]}")
                    break
                print(f"{link.name}: failure report matches (sha256 {h[:12]}); applying the recorded repair")
                stages[-1]["failure_report"] = report
                stages[-1]["failure_report_sha256"] = h
                rule, meta = new_rule, new_meta
                results = bench.run_all(browser, local, rule)
                stages.append({"proposal": link.name, "meta": meta, "rule": rule, "results": results})
        browser.close()
    table = ["| Rule | Scenario | Category | Prices exact / expected | Held for review | Wrong values exported "
             "| Missing / unexpected / duplicated ids | Result |", "|---|---|---|---|---|---|---|---|"]
    for st in stages:
        table += _summary_rows(st["proposal"], st["results"])
    print("\n".join(table))
    if refused:
        print("REFUSED:", json.dumps(refused))
    if write:
        RESULTS.mkdir(exist_ok=True)
        doc = {"refused": refused, "stages": [{k: v for k, v in st.items() if k != "results"} | {"results": _compact(st["results"])}
                                              for st in stages]}
        (RESULTS / "results.json").write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        (RESULTS / "TABLE.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    return 1 if refused else 0


def generate() -> int:
    if agent.chain():
        print("proposals/ already holds a chain; generation is recorded once.")
        return 2
    with LocalCopy() as local, sync_playwright() as p:
        browser = p.chromium.launch()
        obs = _observe(browser, local, "base")
        browser.close()
    prompt = agent.generate_prompt(obs)
    answer = agent.call_model(prompt)
    folder = agent.record("generate", prompt, obs, "observations.json", answer, None)
    print("recorded", folder)
    return 0


def repair() -> int:
    links = agent.chain()
    with LocalCopy() as local, sync_playwright() as p:
        browser = p.chromium.launch()
        rule, _ = agent.load(links[-1])
        results = bench.run_all(browser, local, rule)
        report = bench.failure_report(rule, results)
        if not report["failing_scenarios"]:
            print("Nothing to repair: every scenario shown to the model behaves as expected.")
            return 0
        by_id = {sc["id"]: sc for sc in bench.SCENARIOS}
        walks = []
        for s in report["failing_scenarios"]:
            sc = by_id[s["scenario"]]
            walks.append(dict(_observe(browser, local, sc["variant"], sc["version"]), variant=s["app_version"]))
        browser.close()
    prompt = agent.repair_prompt(rule, report, {"walks": walks})
    answer = agent.call_model(prompt)
    folder = agent.record("repair", prompt, report, "failure_report.json", answer, rule)
    (folder / "observations.json").write_text(json.dumps({"walks": walks}, indent=1, ensure_ascii=False), encoding="utf-8")
    print("recorded", folder)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m ui5rules")
    ap.add_argument("command", choices=["replay", "generate", "repair"])
    a = ap.parse_args(argv)
    return {"replay": replay, "generate": generate, "repair": repair}[a.command]()


if __name__ == "__main__":
    sys.exit(main())
