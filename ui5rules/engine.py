"""Runs a rule in a real browser (Playwright) and records what each field read.

The engine reads the screen only: visible elements and the page URL.  It never reads the UI5
models, the OData responses or the mock data files.  Parsing a value into its type is done here;
judging the record (missing, ambiguous, wrong type, counts) is the validator's job.
"""
from __future__ import annotations

import re
import time
from decimal import Decimal, InvalidOperation

from playwright.sync_api import Page

from .rules import with_parameters

RESOLVER_JS = r"""
() => {
  if (window.__rr) return;
  let counter = 0;
  const HIDDEN_CLASSES = ['sapUiPseudoInvisibleText', 'sapUiInvisibleText', 'sapUiHiddenPlaceholder'];
  const rr = {
    visible(el) {
      if (!el || !el.isConnected) return false;
      const r = el.getBoundingClientRect();
      if (r.width < 1 || r.height < 1) return false;
      for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
        const s = getComputedStyle(e);
        if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
        if (HIDDEN_CLASSES.some(c => e.classList.contains(c))) return false;
      }
      return true;
    },
    text(el) { return (el.innerText || '').replace(/\s+/g, ' ').trim(); },
    lines(el) { return (el.innerText || '').split('\n').map(s => s.replace(/\s+/g, ' ').trim()).filter(Boolean); },
    role(el) {
      const r = el.getAttribute('role');
      if (r) return r;
      const t = el.tagName.toLowerCase();
      if (t === 'button') return 'button';
      if (t === 'a' && el.hasAttribute('href')) return 'link';
      if (t === 'li') return 'listitem';
      if (/^h[1-6]$/.test(t)) return 'heading';
      if (t === 'input') return el.type === 'search' ? 'searchbox' : 'textbox';
      return null;
    },
    accName(el) {
      const al = el.getAttribute('aria-label');
      if (al) return al.trim();
      const lb = el.getAttribute('aria-labelledby');
      if (lb) {
        const t = lb.split(/\s+/).map(id => document.getElementById(id)).filter(Boolean)
          .map(e => (e.textContent || '').trim()).join(' ').replace(/\s+/g, ' ').trim();
        if (t) return t;
      }
      return this.text(el);
    },
    deepestWithText(root, text) {
      const out = [];
      for (const el of root.querySelectorAll('*')) {
        if (this.text(el) !== text) continue;
        if ([...el.children].some(c => this.text(c) === text)) continue;
        out.push(el);
      }
      return out;
    },
    labelValue(labelEl) {
      for (let e = labelEl; e && e.nodeType === 1; e = e.parentElement) {
        for (let s = e.nextElementSibling; s; s = s.nextElementSibling) {
          const t = this.text(s);
          if (t && t !== ':' && this.visible(s)) return s;
        }
      }
      return null;
    },
    find(spec, scope) {
      let root = scope || document.body;
      if (spec.within) {
        const w = this.find(spec.within, scope);
        if (w.els.length === 0) return {els: [], scope: 'missing'};
        if (w.els.length > 1 && (spec.within.pick || 'single') === 'single') return {els: [], scope: 'ambiguous', scope_n: w.els.length};
        root = w.els[0];
      }
      let c = [];
      if (spec.css !== undefined) c = [...root.querySelectorAll(spec.css)];
      else if (spec.text !== undefined) c = this.deepestWithText(root, spec.text);
      else if (spec.role !== undefined) c = [...root.querySelectorAll('*')].filter(e => this.role(e) === spec.role && (spec.name === undefined || this.accName(e) === spec.name));
      else if (spec.label !== undefined) {
        const labels = [...this.deepestWithText(root, spec.label), ...this.deepestWithText(root, spec.label + ':')];
        c = labels.filter(l => this.visible(l)).map(l => this.labelValue(l)).filter(Boolean);
      }
      c = [...new Set(c)].filter(e => this.visible(e));
      if (spec.has_text !== undefined) c = c.filter(e => this.lines(e).includes(spec.has_text));
      return {els: c};
    },
    run(spec, scopeMark) {
      const scope = scopeMark ? document.querySelector(`[data-rr="${scopeMark}"]`) : null;
      if (scopeMark && !scope) return {marks: [], texts: [], scope: 'lost'};
      const r = this.find(spec, scope);
      const marks = r.els.map(e => { const m = 'm' + (++counter); e.setAttribute('data-rr', m); return m; });
      return {marks, texts: r.els.map(e => this.text(e)), scope: r.scope || null, scope_n: r.scope_n || null};
    },
    anchored(mark, text, hops) {
      let e = document.querySelector(`[data-rr="${mark}"]`);
      for (let i = 0; e && i <= hops; i++, e = e.parentElement) {
        if (this.deepestWithText(e, text).some(x => this.visible(x)) || this.deepestWithText(e, text + ':').some(x => this.visible(x))) return true;
      }
      return false;
    },
  };
  window.__rr = rr;
}
"""

SETTLE_JS = r"""
(quietMs) => new Promise(resolve => {
  let timer = setTimeout(done, quietMs);
  const hard = setTimeout(done, 4000);
  const obs = new MutationObserver(() => { clearTimeout(timer); timer = setTimeout(done, quietMs); });
  obs.observe(document.body, {subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ['class', 'style']});
  function done() { obs.disconnect(); clearTimeout(timer); clearTimeout(hard); resolve(true); }
})
"""


class RuleRuntimeError(Exception):
    pass


def _find(page: Page, spec: dict, scope_mark: str | None = None) -> dict:
    page.evaluate(RESOLVER_JS)
    return page.evaluate("([s, m]) => window.__rr.run(s, m)", [spec, scope_mark])


def _wait_for(page: Page, spec: dict, timeout_s: float = 20.0) -> dict:
    t0 = time.time()
    while True:
        r = _find(page, spec)
        if r["marks"]:
            return r
        if time.time() - t0 > timeout_s:
            raise RuleRuntimeError(f"timeout waiting for {spec}")
        time.sleep(0.2)


def settle(page: Page, quiet_ms: int = 300):
    page.evaluate(SETTLE_JS, quiet_ms)


def _pick(spec: dict, r: dict):
    """Returns (mark, issue)."""
    if r.get("scope") == "missing":
        return None, {"kind": "missing", "detail": "scope not found"}
    if r.get("scope") == "ambiguous":
        return None, {"kind": "ambiguous", "detail": f"scope matched {r['scope_n']} elements"}
    if r.get("scope") == "lost":
        return None, {"kind": "missing", "detail": "item element no longer on screen"}
    n = len(r["marks"])
    if n == 0:
        return None, {"kind": "missing", "detail": "no visible element matched"}
    if n > 1 and spec.get("pick", "single") == "single":
        return None, {"kind": "ambiguous", "detail": f"{n} elements matched", "candidates": r["texts"][:6]}
    return r["marks"][0], None


NUM_TOKEN = re.compile(r"\d(?:[\d.,  ]*\d)?")


def parse_value(f: dict, raw: str):
    """Returns (value, issue). value is a JSON-friendly string for decimals."""
    t = f["type"]
    if f.get("regex") and f.get("from") != "url":
        m = re.search(f["regex"], raw)
        if not m:
            return None, {"kind": "type", "detail": f"regex did not match {raw!r}"}
        raw = m.group(1) if m.groups() else m.group(0)
    raw = raw.strip()
    if t == "decimal":
        nf = f.get("number_format") or {"decimal": ".", "group": ","}
        tokens = NUM_TOKEN.findall(raw)
        if len(tokens) != 1:
            return None, {"kind": "type", "detail": f"expected one number in {raw!r}, found {len(tokens)}"}
        s = tokens[0].replace(" ", "").replace(" ", "")
        if nf.get("group"):
            s = s.replace(nf["group"], "")
        s = s.replace(nf.get("decimal", "."), ".")
        try:
            return str(Decimal(s)), None
        except InvalidOperation:
            return None, {"kind": "type", "detail": f"not a decimal: {raw!r}"}
    if t == "currency_code":
        codes = re.findall(r"\b[A-Z]{3}\b", raw)
        if len(codes) != 1:
            return None, {"kind": "type", "detail": f"expected one currency code in {raw!r}"}
        return codes[0], None
    if t == "enum":
        if raw not in f["map"]:
            return None, {"kind": "type", "detail": f"{raw!r} is not in the enum map"}
        return f["map"][raw], None
    if t == "id":
        if f.get("pattern") and not re.fullmatch(f["pattern"], raw):
            return None, {"kind": "type", "detail": f"{raw!r} does not match the id pattern"}
        return raw, None
    return raw, None


def _read_field(page: Page, name: str, f: dict, item_mark: str | None) -> dict:
    out = {"raw": None, "value": None, "candidates": None, "issue": None}
    if f["from"] == "url":
        url = page.url
        m = re.search(f["regex"], url)
        if not m:
            out["issue"] = {"kind": "missing", "detail": "regex did not match the URL"}
            return out
        raw = m.group(1) if m.groups() else m.group(0)
    else:
        loc = f["locator"]
        r = _find(page, loc, item_mark if f["from"] == "item" else None)
        out["candidates"] = r["texts"][:6]
        mark, issue = _pick(loc, r)
        if issue:
            out["issue"] = issue
            return out
        raw = r["texts"][r["marks"].index(mark)]
        a = f.get("anchor")
        if a and not page.evaluate("([m,t,h]) => window.__rr.anchored(m,t,h)", [mark, a["text"], int(a.get("max_hops", 3))]):
            out["raw"] = raw
            out["issue"] = {"kind": "anchor", "detail": f"label {a['text']!r} not found near the value"}
            return out
    out["raw"] = raw
    out["value"], out["issue"] = parse_value(f, raw)
    return out


def run_rule(page: Page, app_url: str, rule: dict, params: dict | None = None) -> dict:
    """Executes the rule. Returns a run record; never raises for rule problems."""
    rule = with_parameters(rule, params)
    run = {"screen_count": None, "items": [], "batch_issues": []}
    try:
        page.goto(app_url)
        page.wait_for_load_state("load")
        for i, st in enumerate(rule.get("steps", [])):
            if st["action"] == "wait_for":
                _wait_for(page, st["target"])
            elif st["action"] == "click":
                r = _wait_for(page, st["target"])
                mark, issue = _pick(st["target"], r)
                if issue:
                    raise RuleRuntimeError(f"step {i} click target {issue['kind']}: {issue['detail']}")
                page.locator(f'[data-rr="{mark}"]').click()
                if st.get("then_wait_for"):
                    _wait_for(page, st["then_wait_for"])
                settle(page)
            elif st["action"] == "read_count":
                r = _wait_for(page, st["target"])
                mark, issue = _pick(st["target"], r)
                if issue:
                    raise RuleRuntimeError(f"step {i} count target {issue['kind']}: {issue['detail']}")
                m = re.search(st["regex"], r["texts"][r["marks"].index(mark)])
                if not m:
                    raise RuleRuntimeError(f"step {i} count regex did not match")
                run["screen_count"] = int(m.group(1))
        items = rule["items"]
        first = _wait_for(page, items["locator"])
        n = len(first["marks"])
        for idx in range(n):
            r = _find(page, items["locator"])
            if len(r["marks"]) != n:
                run["batch_issues"].append({"kind": "unstable_list", "detail": f"list had {n} items, then {len(r['marks'])}"})
                break
            mark = r["marks"][idx]
            rec = {"index": idx, "item_text": r["texts"][idx][:120], "fields": {}}
            for name, f in rule["fields"].items():
                if f["from"] == "item":
                    rec["fields"][name] = _read_field(page, name, f, mark)
            if items.get("open"):
                page.locator(f'[data-rr="{mark}"]').click()
                settle(page)
                if items.get("detail_ready"):
                    try:
                        _wait_for(page, items["detail_ready"], timeout_s=10)
                    except RuleRuntimeError:
                        pass
                    settle(page)
            rec["url_hash"] = "#" + page.url.split("#", 1)[1] if "#" in page.url else ""
            for name, f in rule["fields"].items():
                if f["from"] != "item":
                    rec["fields"][name] = _read_field(page, name, f, None)
            run["items"].append(rec)
    except RuleRuntimeError as e:
        run["batch_issues"].append({"kind": "navigation", "detail": str(e)})
    except Exception as e:  # browser-level failure: reported, not hidden
        run["batch_issues"].append({"kind": "engine_error", "detail": f"{type(e).__name__}: {str(e)[:1500]}"})
    return run
