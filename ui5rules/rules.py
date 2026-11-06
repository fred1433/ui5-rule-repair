"""The rule format (ours) and its static checks.

A rule is plain JSON: no code, no Python, no JavaScript.  It says how to reach the records
(navigation steps), which elements are the records, and for each output field where its value
is on screen, how to read it and what it must look like (the contracts the runtime validator
checks).  Skan's own engine format is unknown to us; this format is meant to be easy to map.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re

FORMAT = "ui5-rule-repair/rule@1"

FORMAT_DOC = """\
RULE FORMAT  (format id "ui5-rule-repair/rule@1"; plain JSON, no code of any kind)

{
  "format": "ui5-rule-repair/rule@1",
  "name": string,
  "parameters": {"category": "<visible category name>"},   // "{category}" in any string is replaced
  "steps": [ STEP, ... ],          // run in order after the app has loaded
  "items": {
    "locator": LOCATOR,            // matches every record element of the list; all matches are used
    "open": true | false,          // true: click each item to open its detail view before reading
    "detail_ready": LOCATOR | null // after opening, wait until this matches
  },
  "fields": { "<field name>": FIELD, ... },
  "key": "<field name>",           // the field that identifies a record (must be unique)
  "count_check": true | false      // compare the number of items with the number read by a read_count step
}

STEP is one of:
  {"action": "wait_for",   "target": LOCATOR}
  {"action": "click",      "target": LOCATOR, "then_wait_for": LOCATOR | null}
  {"action": "read_count", "target": LOCATOR, "regex": "<regex, group 1 = the number>"}

LOCATOR (exactly one of css / text / role / label, plus optional keys):
  {"css": "<CSS selector>"}
  {"text": "<exact visible text>"}                       // the deepest element whose whole text equals it
  {"role": "<ARIA role>", "name": "<accessible name>"}   // name optional
  {"label": "<visible label text>"}                      // the value shown next to that label
  optional: "within": LOCATOR    // search only inside the element matched by this locator
            "has_text": "<text>" // keep only elements one of whose text lines equals this
            "pick": "single" | "first"
                 // single (default): more than one match is reported as ambiguous and nothing is read
                 // first: the first match in document order is read, other matches are ignored
  Only visible elements match.  Ids that contain "__" are generated at runtime and are refused.

FIELD:
  {
    "from": "item" | "detail" | "url",   // item: inside the list element; detail: the page after opening; url: the page URL
    "locator": LOCATOR,                  // not used when from = "url"
    "regex": "<optional regex; group 1 (or the whole match) is the value>",   // required when from = "url"
    "type": "id" | "decimal" | "currency_code" | "enum" | "text",
    "number_format": {"decimal": ",", "group": "."},  // decimal only
    "map": {"<shown text>": "<code>", ...},           // enum only: shown value -> output code
    "pattern": "<regex the value must fully match>",  // id only, optional
    "anchor": {"text": "<label text>", "max_hops": 3}  // optional contract: that text must be visible
                                                       // within max_hops ancestors of the matched element
  }

Runtime contracts checked by the validator (it only sees the page, never any reference data):
  missing field, ambiguous match (pick=single), value of the wrong type or outside the enum map,
  failed anchor, item count different from the on-screen count, duplicate keys.
  A record with any issue is not exported: it goes to review, with no value invented.
"""

LOCATOR_KINDS = ("css", "text", "role", "label")
LOCATOR_KEYS = set(LOCATOR_KINDS) | {"name", "within", "has_text", "pick"}
FIELD_KEYS = {"from", "locator", "regex", "type", "number_format", "map", "pattern", "anchor"}
TYPES = {"id", "decimal", "currency_code", "enum", "text"}
RULE_KEYS = {"format", "name", "parameters", "steps", "items", "fields", "key", "count_check"}


def _check_locator(loc, where, errs):
    if not isinstance(loc, dict):
        errs.append(f"{where}: locator must be an object")
        return
    kinds = [k for k in LOCATOR_KINDS if k in loc]
    if len(kinds) != 1:
        errs.append(f"{where}: exactly one of css/text/role/label, got {kinds}")
    extra = set(loc) - LOCATOR_KEYS
    if extra:
        errs.append(f"{where}: unknown keys {sorted(extra)}")
    if "css" in loc and "__" in str(loc["css"]):
        errs.append(f"{where}: css uses a generated id (contains '__')")
    if loc.get("pick", "single") not in ("single", "first"):
        errs.append(f"{where}: pick must be single or first")
    if "within" in loc:
        _check_locator(loc["within"], where + ".within", errs)


def check_rule(rule) -> list[str]:
    errs: list[str] = []
    if not isinstance(rule, dict):
        return ["rule must be a JSON object"]
    if rule.get("format") != FORMAT:
        errs.append(f"format must be {FORMAT}")
    extra = set(rule) - RULE_KEYS
    if extra:
        errs.append(f"unknown top-level keys {sorted(extra)}")
    for i, st in enumerate(rule.get("steps", [])):
        a = st.get("action")
        if a not in ("wait_for", "click", "read_count"):
            errs.append(f"steps[{i}]: unknown action {a!r}")
        _check_locator(st.get("target"), f"steps[{i}].target", errs)
        if a == "click" and st.get("then_wait_for"):
            _check_locator(st["then_wait_for"], f"steps[{i}].then_wait_for", errs)
        if a == "read_count":
            try:
                re.compile(st.get("regex", ""))
            except re.error as e:
                errs.append(f"steps[{i}].regex: {e}")
    items = rule.get("items")
    if not isinstance(items, dict):
        errs.append("items missing")
    else:
        _check_locator(items.get("locator"), "items.locator", errs)
        if items.get("detail_ready"):
            _check_locator(items["detail_ready"], "items.detail_ready", errs)
    fields = rule.get("fields")
    if not isinstance(fields, dict) or not fields:
        errs.append("fields missing")
        fields = {}
    for name, f in fields.items():
        w = f"fields.{name}"
        extra = set(f) - FIELD_KEYS
        if extra:
            errs.append(f"{w}: unknown keys {sorted(extra)}")
        if f.get("from") not in ("item", "detail", "url"):
            errs.append(f"{w}: from must be item, detail or url")
        if f.get("from") == "url":
            if not f.get("regex"):
                errs.append(f"{w}: from=url needs a regex")
        else:
            _check_locator(f.get("locator"), w + ".locator", errs)
        if f.get("type") not in TYPES:
            errs.append(f"{w}: unknown type {f.get('type')!r}")
        if f.get("type") == "enum" and not isinstance(f.get("map"), dict):
            errs.append(f"{w}: enum needs a map")
        for k in ("regex", "pattern"):
            if k in f:
                try:
                    re.compile(f[k])
                except re.error as e:
                    errs.append(f"{w}.{k}: {e}")
    if rule.get("key") not in fields:
        errs.append("key must name a field")
    return errs


def with_parameters(rule: dict, params: dict | None = None) -> dict:
    """Returns a copy where "{name}" placeholders are replaced by parameter values."""
    values = dict(rule.get("parameters", {}))
    values.update(params or {})

    def sub(x):
        if isinstance(x, str):
            for k, v in values.items():
                x = x.replace("{" + k + "}", str(v))
            return x
        if isinstance(x, list):
            return [sub(v) for v in x]
        if isinstance(x, dict):
            return {k: (v if k == "parameters" else sub(v)) for k, v in x.items()}
        return x

    return sub(copy.deepcopy(rule))


def canonical(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def sha256(obj) -> str:
    data = obj if isinstance(obj, (bytes, str)) else canonical(obj)
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()
