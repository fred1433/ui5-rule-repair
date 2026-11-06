"""The agent's two model calls (write a rule, repair a rule) and how their answers are frozen.

Calls go through the `claude -p` command line on a Claude subscription (no API key; the script
refuses to run if ANTHROPIC_API_KEY is set), with every tool disabled and an empty working
folder, so the model sees only the prompt.  Each answer is stored under proposals/ with the
SHA-256 of the input it answered (observations for a new rule, failure report for a repair).
Replay re-computes that input and refuses a proposal whose hash no longer matches.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from .rules import FORMAT_DOC, canonical, check_rule, sha256

ROOT = Path(__file__).resolve().parent.parent
PROPOSALS = ROOT / "proposals"

TASK = (
    "For each laptop in this product catalog, extract: product_id (the product reference), "
    "price (the product's price, as a decimal number), currency (ISO 4217 code) and availability "
    "(output code: A = available, O = out of stock, D = discontinued). "
    "Write the rule for the category \"Laptops\": put the category name in parameters.category and "
    "write \"{category}\" wherever the rule needs it, so that the same rule can run on another category."
)

SYSTEM = (
    "You write and maintain extraction rules for a web scraping engine. A Python program drives a real "
    "browser and executes your rule; the rule itself is declarative JSON and contains no code. "
    "Answer with exactly one JSON object in a ```json block and nothing else."
)


def generate_prompt(observations: dict) -> str:
    return "\n\n".join([
        "TASK\n" + TASK,
        FORMAT_DOC,
        "OBSERVATIONS (a scripted walk through the running app; for each step, the URL fragment and the "
        "distilled DOM of the view it opened)\n" + _steps_text(observations),
        "Write the rule.",
    ])


def repair_prompt(rule: dict, report: dict, observations: dict) -> str:
    return "\n\n".join([
        "TASK the rule serves\n" + TASK,
        "The rule below was run on modified versions of the app and failed. The failure report says what "
        "the runtime validator saw on the page and what the comparison with known-good records found "
        "(reference values are withheld). Propose a corrected rule in the same format. It must still work "
        "on the unmodified app and must hold a record for review rather than output a value it cannot "
        "tell apart.",
        "CURRENT RULE\n```json\n" + json.dumps(rule, indent=2, ensure_ascii=False) + "\n```",
        "FAILURE REPORT\n```json\n" + json.dumps(report, indent=2, ensure_ascii=False) + "\n```",
        FORMAT_DOC,
        "OBSERVATIONS of the modified versions where the rule failed\n" + _steps_text(observations),
        "Write the corrected rule.",
    ])


def _steps_text(observations: dict) -> str:
    parts = []
    for block in observations.get("walks", [observations]):
        if "variant" in block:
            parts.append(f"=== app version: {block['variant']} ===")
        for st in block["steps"]:
            parts.append(f"--- step: {st['step']}  (URL fragment: {st['url_fragment']})\n{st['dom']}")
    return "\n".join(parts)


def call_model(prompt: str) -> dict:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        raise SystemExit("Refusing to run: an API key is set. Proposals are made on a Claude subscription via `claude -p`.")
    exe = shutil.which("claude")
    if not exe:
        raise SystemExit("The `claude` command line is needed to make a new proposal (replay does not need it).")
    env = {k: v for k, v in os.environ.items() if k not in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")}
    cmd = [exe, "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", "--setting-sources", "", "--system-prompt", SYSTEM]
    with tempfile.TemporaryDirectory() as d:
        p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, cwd=d, env=env, timeout=1200)
    if p.returncode != 0:
        raise SystemExit(f"claude -p failed: {p.stderr[:500]}")
    out = json.loads(p.stdout)
    return {"text": out["result"], "models": sorted(out.get("modelUsage", {}).keys()),
            "duration_ms": out.get("duration_ms")}


def extract_json(text: str) -> dict:
    m = re.search(r"```json\s*(\{.*\})\s*```", text, re.S) or re.search(r"(\{.*\})", text, re.S)
    if not m:
        raise ValueError("no JSON object in the answer")
    return json.loads(m.group(1))


def record(kind: str, prompt: str, input_obj: dict, input_name: str, answer: dict, parent: dict | None) -> Path:
    PROPOSALS.mkdir(exist_ok=True)
    n = len([p for p in PROPOSALS.iterdir() if p.is_dir()]) + 1
    folder = PROPOSALS / f"{n:02d}-{kind}"
    folder.mkdir()
    rule = extract_json(answer["text"])
    errors = check_rule(rule)
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    (folder / input_name).write_text(json.dumps(input_obj, indent=1, ensure_ascii=False), encoding="utf-8")
    (folder / "answer.txt").write_text(answer["text"], encoding="utf-8")
    (folder / "rule.json").write_text(json.dumps(rule, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    meta = {
        "kind": kind,
        "created_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "made_with": "claude -p (Claude subscription, all tools disabled, empty working folder)",
        "models": answer["models"],
        "duration_ms": answer["duration_ms"],
        "input_file": input_name,
        "input_sha256": sha256(input_obj),
        "prompt_sha256": sha256(prompt),
        "parent_rule_sha256": sha256(parent) if parent else None,
        "rule_sha256": sha256(rule),
        "static_check_errors": errors,
    }
    (folder / "meta.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return folder


def chain() -> list[Path]:
    if not PROPOSALS.exists():
        return []
    return sorted(p for p in PROPOSALS.iterdir() if p.is_dir() and (p / "meta.json").exists())


def load(folder: Path) -> tuple[dict, dict]:
    meta = json.loads((folder / "meta.json").read_text())
    rule = json.loads((folder / "rule.json").read_text())
    if sha256(rule) != meta["rule_sha256"]:
        raise SystemExit(f"{folder.name}: rule.json does not match its recorded hash")
    return rule, meta


__all__ = ["generate_prompt", "repair_prompt", "call_model", "record", "chain", "load", "canonical"]
