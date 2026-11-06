"""Captures the two crops of the modified SAP demo used by the page (local copy, offline)."""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402

from ui5rules.engine import _wait_for, settle  # noqa: E402
from ui5rules.server import LocalCopy  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "site" / "img"


def box(el, origin):
    b = el.bounding_box()
    return {k: round(v, 1) for k, v in {"x": b["x"] - origin["x"], "y": b["y"] - origin["y"], "w": b["width"], "h": b["height"]}.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {}
    with LocalCopy() as lc, sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=2, locale="en-US")
        page = ctx.new_page()
        page.goto(lc.url("delivered_price"))
        _wait_for(page, {"text": "Laptops", "within": {"css": '[id$="---homeView"]'}}, 60)
        page.get_by_text("Laptops", exact=True).click()
        _wait_for(page, {"css": '[id$="---category--productList"] li.sapMObjLItem', "pick": "first"})
        settle(page)
        row = page.locator('[id$="---category--productList"] li.sapMObjLItem').first
        row.click()
        _wait_for(page, {"css": '[id$="---product"] .sapMOH'})
        settle(page)
        time.sleep(0.5)
        page.mouse.move(5, 895)
        rb = row.bounding_box()
        row.screenshot(path=str(OUT / "row.png"))
        meta["row"] = {"w": rb["width"], "h": rb["height"],
                       "number": box(row.locator(".sapMObjectNumber").first, rb),
                       "shipping": box(row.get_by_text("incl.", exact=False).first, rb)}
        head = page.locator('[id$="---product"] .sapMOH').first
        hb = head.bounding_box()
        head.screenshot(path=str(OUT / "header.png"))
        meta["header"] = {"w": hb["width"], "h": hb["height"],
                          "number": box(head.locator(".sapMOHNumberDiv").first, hb),
                          "shipping": box(head.locator(".sapMObjectAttributeDiv").first, hb)}
        page.screenshot(path=str(OUT / "app.png"))
        b.close()
    (OUT / "crops.json").write_text(json.dumps(meta, indent=1))
    print(json.dumps(meta))


if __name__ == "__main__":
    main()
