"""Fills copy/sdk from sdk.openui5.org (one fetch per missing file) by walking the demo, then
lists every request the walk still answers with 404.  Run once per version; tests never fetch."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from playwright.sync_api import sync_playwright  # noqa: E402

from ui5rules.engine import _wait_for  # noqa: E402
from ui5rules.server import LocalCopy  # noqa: E402


def walk(lc, version, variant="base", fetch=True):
    missing = set()
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page(viewport={"width": 1440, "height": 900})
        pg.on("response", lambda r: missing.add(r.url.split("/", 3)[3]) if r.status == 404 else None)
        pg.goto(lc.url(variant, version))
        pg.wait_for_selector("text=Laptops", timeout=90000)
        time.sleep(3)
        for cat in ("Laptops", "Mice"):
            print(version, cat, flush=True)
            r = _wait_for(pg, {"text": cat, "within": {"css": '[id$="---homeView"]'}}, 60)
            pg.locator(f'[data-rr="{r["marks"][0]}"]').click()
            for _ in range(30):
                if "/category/" in pg.url:
                    break
                time.sleep(0.5)
            print("  url", pg.url.split("#")[-1][-30:], flush=True)
            time.sleep(2)
            items = pg.locator('[id$="---category--productList"] li.sapMObjLItem')
            for i in range(min(items.count(), 3)):
                items.nth(i).click()
                time.sleep(1.5)
            pg.goto("about:blank")
            pg.goto(lc.url(variant, version))
            time.sleep(3)
        b.close()
    return sorted(missing)


if __name__ == "__main__":
    fetch = "--offline" not in sys.argv
    with LocalCopy(fetch_missing=fetch) as lc:
        for v in [a for a in sys.argv[1:] if not a.startswith("--")]:
            print(v, walk(lc, v))
