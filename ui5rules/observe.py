"""What the agent observes before writing or repairing a rule.

The exploration path is scripted (open the app, open the category by its visible name, open the
first two products).  At each step the observer records the URL fragment and a distilled view of
the rendered DOM: visible elements only, their tag, classes, role, ARIA label and own text.  Ids
that contain "__" are generated at runtime by UI5 and are dropped from the observation.

Only the UI5 views that the step opened are distilled (home, category, product), found by their
stable view ids.  The welcome view shows randomly promoted products and is left out, so that two
observations of the same app are identical and can be compared by hash.
"""
from __future__ import annotations

import time

from playwright.sync_api import Page

from .engine import RESOLVER_JS, _wait_for, settle

DISTILL_JS = r"""
([rootSel, maxLines]) => {
  const root = document.querySelector(rootSel);
  if (!root) return null;
  const SKIP = new Set(['SCRIPT', 'STYLE', 'SVG', 'IMG', 'NOSCRIPT', 'TEMPLATE']);
  const lines = [];
  const own = el => [...el.childNodes].filter(n => n.nodeType === 3).map(n => n.textContent).join(' ').replace(/\s+/g, ' ').trim();
  function walk(el, depth) {
    if (lines.length >= maxLines) return;
    if (SKIP.has(el.tagName.toUpperCase())) return;
    if (!window.__rr.visible(el)) return;
    const id = el.id && !el.id.includes('__') ? el.id : '';
    const role = el.getAttribute('role') || '';
    const aria = el.getAttribute('aria-label') || '';
    const text = own(el);
    const kids = [...el.children];
    const silent = !id && !role && !aria && !text && el.classList.length === 0;
    if (silent && kids.length === 1) { walk(kids[0], depth); return; }
    let s = '  '.repeat(depth) + el.tagName.toLowerCase();
    if (id) s += '#' + id;
    const cls = [...el.classList].slice(0, 6);
    if (cls.length) s += '.' + cls.join('.');
    if (role) s += ` [role=${role}]`;
    if (aria) s += ` [aria-label="${aria.slice(0, 60)}"]`;
    if (text) s += ` "${text.slice(0, 90)}"`;
    lines.push(s);
    for (const k of kids) walk(k, depth + 1);
  }
  walk(root, 0);
  return lines.join('\n');
}
"""

VIEW_ROOTS = {
    "home": '[id$="---homeView"]',
    "category": '[id$="---category"]',
    "product": '[id$="---product"]',
}


def distill(page: Page, view: str, max_lines: int = 420) -> str:
    page.evaluate(RESOLVER_JS)
    out = page.evaluate(DISTILL_JS, [VIEW_ROOTS[view], max_lines])
    return out or f"(view {view} not on screen)"


def _hash(page: Page) -> str:
    return "#" + page.url.split("#", 1)[1] if "#" in page.url else "#"


def _click_text(page: Page, text: str):
    _wait_for(page, {"text": text}, timeout_s=60)
    settle(page)
    r = _wait_for(page, {"text": text}, timeout_s=60)
    if len(r["marks"]) != 1:
        raise RuntimeError(f"observer: {len(r['marks'])} visible elements show {text!r}")
    before = page.url
    page.locator(f'[data-rr="{r["marks"][0]}"]').click()
    settle(page)
    if page.url == before:  # some UI5 releases swallow the first click: one retry
        r = _wait_for(page, {"text": text}, timeout_s=10)
        page.locator(f'[data-rr="{r["marks"][0]}"]').click()


def observe(page: Page, app_url: str, category: str, products: int = 2) -> dict:
    """Scripted walk; returns the observation record given to the model."""
    page.goto(app_url)
    _wait_for(page, {"text": category, "within": {"css": VIEW_ROOTS["home"]}}, timeout_s=60)
    settle(page)
    steps = [{"step": "app loaded", "url_fragment": _hash(page), "view": "home", "dom": distill(page, "home")}]
    _click_text(page, category)
    page.wait_for_selector(VIEW_ROOTS["category"] + " li", timeout=30000)
    settle(page)
    steps.append({"step": f"clicked the visible text {category!r}", "url_fragment": _hash(page), "view": "category",
                  "dom": distill(page, "category")})
    for i in range(products):
        page.evaluate(RESOLVER_JS)
        items = page.evaluate("([s]) => window.__rr.run(s, null)", [{"css": VIEW_ROOTS["category"] + " ul > li"}])
        before = page.url
        page.locator(f'[data-rr="{items["marks"][i]}"]').click()
        settle(page)
        if page.url == before:  # one retry, as for the category click
            items = page.evaluate("([s]) => window.__rr.run(s, null)", [{"css": VIEW_ROOTS["category"] + " ul > li"}])
            page.locator(f'[data-rr="{items["marks"][i]}"]').click()
        page.wait_for_selector(VIEW_ROOTS["product"], timeout=30000)
        settle(page)
        time.sleep(0.2)
        steps.append({"step": f"clicked list item {i + 1} of the category list", "url_fragment": _hash(page),
                      "view": "product", "dom": distill(page, "product")})
    return {"app": "OpenUI5 Shopping Cart demo 1.154.0 (local copy)", "viewport": "1440x900", "steps": steps}
