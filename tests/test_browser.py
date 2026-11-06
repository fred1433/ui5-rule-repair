"""Browser tests on the local copy (offline: the server never fetches from sdk.openui5.org here)."""
import json
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright

from ui5rules import bench
from ui5rules.server import LocalCopy

ROOT = Path(__file__).resolve().parent.parent
TEST_RULE = json.loads((ROOT / "tests/fixtures/engine_test_rule.json").read_text())


@pytest.fixture(scope="module")
def env():
    with LocalCopy() as local, sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser, local
        browser.close()


def sc(id_):
    return next(s for s in bench.SCENARIOS if s["id"] == id_)


def test_local_copy_is_offline_and_marks_its_variants(env):
    _, local = env
    import urllib.request, urllib.error
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(local.base + "/base/1.154.0/resources/not-in-the-copy.js")
    with pytest.raises(urllib.error.HTTPError):
        urllib.request.urlopen(local.base + "/base/1.154.0/test-resources/sap/m/demokit/cart/webapp/Component-preload.js")


def test_engine_reads_all_laptops_on_the_unmodified_app(env):
    browser, local = env
    r = bench.run_scenario(browser, local, TEST_RULE, sc("base"))
    assert r["ok"] and r["bench"]["price_exact_n"] == 11 == r["bench"]["expected_n"]


def test_price_removed_means_every_record_is_held(env):
    browser, local = env
    r = bench.run_scenario(browser, local, TEST_RULE, sc("price_hidden"))
    assert r["bench"]["exported_n"] == 0 and r["bench"]["held_for_review_n"] == 11
    assert r["bench"]["wrong_accepted_n"] == 0
