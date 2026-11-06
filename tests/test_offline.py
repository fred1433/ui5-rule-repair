"""Fast tests: no browser, no network."""
import copy
import json
from pathlib import Path

import pytest

from ui5rules import agent, bench, oracle
from ui5rules.engine import parse_value
from ui5rules.rules import check_rule, sha256, with_parameters
from ui5rules.validator import validate

ROOT = Path(__file__).resolve().parent.parent
TEST_RULE = json.loads((ROOT / "tests/fixtures/engine_test_rule.json").read_text())


def test_every_recorded_rule_passes_the_static_check():
    for folder in agent.chain():
        rule, meta = agent.load(folder)
        assert check_rule(rule) == [], folder.name
        assert meta["static_check_errors"] == []


def test_rules_refuse_generated_ids_and_unknown_keys():
    bad = copy.deepcopy(TEST_RULE)
    bad["items"]["locator"] = {"css": "#__item5-container-cart---category--productList-0"}
    bad["fields"]["price"]["script"] = "return 1"
    errs = check_rule(bad)
    assert any("generated id" in e for e in errs)
    assert any("unknown keys" in e for e in errs)


def test_parameters_are_substituted_everywhere():
    r = with_parameters(TEST_RULE, {"category": "Mice"})
    assert r["steps"][1]["target"] == {"text": "Mice"}
    assert r["parameters"] == {"category": "Laptops"}


@pytest.mark.parametrize("raw,value", [("989,00", "989.00"), ("1.003,90", "1003.90"), ("1.249,00 EUR", "1249.00")])
def test_decimal_parsing_with_german_separators(raw, value):
    f = {"type": "decimal", "number_format": {"decimal": ",", "group": "."}}
    assert parse_value(f, raw) == (value, None)


@pytest.mark.parametrize("raw,fmt,value", [
    ("-5,00", {"decimal": ",", "group": "."}, "-5.00"),
    ("\u22125,00", {"decimal": ",", "group": "."}, "-5.00"),
    ("1.003,90", None, None),            # German text read with the default (English) format: refused
    ("1.003.90", {"decimal": ",", "group": "."}, None),
    ("1.0.0,9", {"decimal": ",", "group": "."}, None),
    ("10.03,90", {"decimal": ",", "group": "."}, None),
    ("1,003.90", None, "1003.90"),
    ("989.00", None, "989.00"),
])
def test_decimal_parsing_keeps_the_sign_and_refuses_misplaced_separators(raw, fmt, value):
    f = {"type": "decimal", **({"number_format": fmt} if fmt else {})}
    got, issue = parse_value(f, raw)
    assert got == value
    assert (issue is None) == (value is not None)


def test_two_numbers_in_one_text_is_a_type_issue_not_a_guess():
    f = {"type": "decimal", "number_format": {"decimal": ",", "group": "."}}
    value, issue = parse_value(f, "989,00 EUR incl. 14,90 EUR shipping")
    assert value is None and issue["kind"] == "type"


def test_unknown_enum_value_is_held():
    f = {"type": "enum", "map": {"Available": "A"}}
    assert parse_value(f, "Discontinued")[1]["kind"] == "type"


def _run(prices, screen_count=None, issue_on=None):
    items = []
    for i, (pid, price) in enumerate(prices):
        fields = {
            "product_id": {"raw": pid, "value": pid, "candidates": None, "issue": None},
            "price": {"raw": price, "value": price, "candidates": None, "issue": None},
            "currency": {"raw": "EUR", "value": "EUR", "candidates": None, "issue": None},
            "availability": {"raw": "?", "value": STATUS.get(pid, "A"), "candidates": None, "issue": None},
        }
        if issue_on == pid:
            fields["price"].update(value=None, candidates=["989,00", "14,90"], issue={"kind": "ambiguous", "detail": "2 elements matched", "candidates": ["989,00", "14,90"]})
        items.append({"index": i, "fields": fields, "url_hash": ""})
    return {"screen_count": screen_count, "items": items, "batch_issues": []}


LT = sorted(oracle.expected("LT").items())
STATUS = {pid: p["Status"] for pid, p in LT}


def test_the_runtime_validator_cannot_see_a_single_wrong_amount_but_the_oracle_does():
    prices = [(pid, str(float(p["Price"]) + 14.90)) for pid, p in LT]
    report = validate(TEST_RULE, _run(prices, screen_count=len(prices)))
    assert report["status"] == "pass"
    score = oracle.score("LT", report)
    assert score["wrong_accepted_n"] == len(LT) and score["price_exact_n"] == 0


def test_ambiguous_record_is_held_and_nothing_is_invented():
    prices = [(pid, p["Price"]) for pid, p in LT]
    report = validate(TEST_RULE, _run(prices, screen_count=len(prices), issue_on="HT-1251"))
    assert report["status"] == "needs_review" and report["review_n"] == 1
    assert "HT-1251" not in {r["key"] for r in report["exported"]}
    score = oracle.score("LT", report)
    assert score["price_exact_n"] == len(LT) - 1 and score["wrong_accepted_n"] == 0


def test_count_mismatch_and_duplicates_block_the_whole_batch():
    prices = [(pid, p["Price"]) for pid, p in LT][:3]
    prices.append(prices[0])
    report = validate(TEST_RULE, _run(prices, screen_count=11))
    kinds = {i["kind"] for i in report["batch_issues"]}
    assert {"count_mismatch", "duplicate_key"} <= kinds
    assert report["exported"] == []


def test_oracle_counts_come_from_the_pinned_sap_file():
    products = oracle.load_products()
    assert len(products) == 123
    assert len(oracle.expected("LT")) == 11
    assert oracle.expected("LT")["HT-1000"]["Price"] == "956"
    assert oracle.expected("LT")["HT-1251"]["Price"] == "989"


def test_failure_report_withholds_reference_values():
    prices = [(pid, str(float(p["Price"]) + 14.90)) for pid, p in LT]
    run = _run(prices, screen_count=len(prices))
    v = validate(TEST_RULE, run)
    results = [{"id": "delivered_price", "variant": "delivered_price", "version": "1.154.0", "role": "seen",
                "ok": False, "expect": "export_all", "category_name": "Laptops", "validator": v, "bench": oracle.score("LT", v)}]
    rep = bench.failure_report(TEST_RULE, results)
    text = json.dumps(rep)
    assert '"989"' not in text and "956" not in text
    assert rep["failing_scenarios"][0]["known_good_check"]["exported_but_wrong"][0]["fields"] == ["price"]
    assert sha256(rep) == sha256(json.loads(text))


def test_chain_links_each_repair_to_its_parent_rule():
    links = agent.chain()
    assert links and links[0].name.endswith("generate")
    prev = None
    for folder in links:
        rule, meta = agent.load(folder)
        if prev is not None:
            assert meta["kind"] == "repair"
            assert meta["parent_rule_sha256"] == sha256(prev)
            report = json.loads((folder / "failure_report.json").read_text())
            assert sha256(report) == meta["input_sha256"]
            assert report["rule_sha256"] == sha256(prev)
        prev = rule


def test_sap_data_is_identical_in_every_release_used():
    """The oracle file is pinned at 1.154.0; the other SAP releases ship the same products."""
    ref = {p["ProductId"]: (p["Price"], p["CurrencyCode"], p["Status"], p["Category"]) for p in oracle.load_products()}
    for version in ("1.96.0", "1.120.30", "1.148.0"):
        folder = ROOT / f"copy/sdk/{version}/test-resources/sap/m/demokit/cart/webapp/localService/mockdata"
        f = folder / "Products.json" if (folder / "Products.json").exists() else folder / "Product.json"
        other = {p["ProductId"]: (p["Price"], p["CurrencyCode"], p["Status"], p["Category"]) for p in json.loads(f.read_text())}
        assert other == ref, version
