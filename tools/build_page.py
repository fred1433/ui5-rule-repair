"""Builds site/index.html from results/results.json, the recorded proposals and the crops.

Every number on the page is read from results/results.json (written by `python -m ui5rules replay`).
"""
import difflib
import html
import json
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from ui5rules import agent  # noqa: E402

FOCUS_SCENARIO = "delivered_price"
FOCUS_ID = "HT-1251"
REPO = "https://github.com/fred1433/ui5-rule-repair"
E = html.escape


def eur(v):
    if v is None:
        return "none"
    d = Decimal(str(v)).quantize(Decimal("0.01"))
    s = f"{d:,.2f}"
    return s.replace(",", " ").replace(".", ",").replace(" ", ".")


def scen(stage, sid):
    return next(r for r in stage["results"] if r["id"] == sid)


def row(r, pid):
    return next(x for x in r["bench"]["rows"] if x["product_id"] == pid)


def cell(r):
    b = r["bench"]
    n = b["expected_n"]
    if r["expect"] == "hold_all":
        if b["wrong_accepted_n"] == 0 and b["exported_n"] == 0:
            return "ok", f"{b['held_for_review_n']} of {n} held, none exported"
        return "bad", f"{b['wrong_accepted_n']} of {n} wrong prices exported"
    if r["ok"]:
        return "ok", f"{b['price_exact_n']} of {n} exact"
    if b["wrong_accepted_n"]:
        return "bad", f"{b['price_exact_n']} of {n} exact, {b['wrong_accepted_n']} wrong exported"
    lost = len(b["missing"])
    if lost == n:
        return "held", f"0 of {n}: run stopped, nothing exported"
    return "held", f"{b['price_exact_n']} of {n} exact, {b['held_for_review_n']} held"


ORIGIN = {
    "sap": "SAP release, unmodified",
    "round 1": "Our change, written before the first rule",
    "round 2": "Our change, written after reading it",
}
LABEL = {
    "base": "OpenUI5 1.154.0",
    "reordered": "List sorted Z to A",
    "shipping_attribute": "Shipping line in the product header",
    "shipping_banner": "Shipping amount above the product header",
    "price_hidden": "Product price removed from screen",
    "delivered_price": "List shows price plus shipping",
    "sap_1.96.0": "OpenUI5 1.96.0",
    "base_mice": "OpenUI5 1.154.0",
    "shipping_banner_mice": "Shipping amount above the product header",
    "delivered_price_mice": "List shows price plus shipping",
    "sap_1.96.0_mice": "OpenUI5 1.96.0",
    "sap_1.120.30": "OpenUI5 1.120.30",
    "sap_1.148.0": "OpenUI5 1.148.0",
}


def diff_lines(a, b):
    la = json.dumps(a, indent=2, ensure_ascii=False).splitlines()
    lb = json.dumps(b, indent=2, ensure_ascii=False).splitlines()
    out = []
    for group in difflib.SequenceMatcher(None, la, lb).get_grouped_opcodes(1):
        if out:
            out.append(("gap", "..."))
        for tag, i1, i2, j1, j2 in group:
            if tag == "equal":
                out += [("ctx", x) for x in la[i1:i2]]
            else:
                out += [("del", x) for x in la[i1:i2]]
                out += [("add", x) for x in lb[j1:j2]]
    return out


def main():
    res = json.loads((ROOT / "results/results.json").read_text())
    crops = json.loads((ROOT / "site/img/crops.json").read_text())
    stages = res["stages"]
    first, last = stages[0], stages[-1]
    f_sc, l_sc = scen(first, FOCUS_SCENARIO), scen(last, FOCUS_SCENARIO)
    f_row, l_row = row(f_sc, FOCUS_ID), row(l_sc, FOCUS_ID)
    f_rec = next(x for x in f_sc["validator"]["records"] if x["key"] == FOCUS_ID)
    links = agent.chain()
    rule0 = json.loads((links[0] / "rule.json").read_text())
    models = sorted({m for st in stages for m in st["meta"]["models"]})
    n_seen = sum(1 for r in first["results"] if r["role"] == "seen")
    n_all = len(first["results"])

    # repair steps
    steps_html = []
    for i in range(1, len(stages)):
        prev, cur = stages[i - 1], stages[i]
        rep = prev["failure_report"]
        fails = rep["failing_scenarios"]
        lines = []
        for s in fails:
            v = s["runtime_validator"]
            k = s["known_good_check"]
            if k["exported_but_wrong"]:
                what = f"{len(k['exported_but_wrong'])} of {k['records_expected']} records exported with a wrong value; runtime validator status: {v['status']}"
            elif v["batch_issues"]:
                what = "run stopped: " + v["batch_issues"][0]["kind"] + (f" ({v['batch_issues'][0]['detail'][:90]})" if v["batch_issues"][0]["kind"] != "engine_error" else "")
            else:
                kinds = sorted({x["kind"] for x in v["record_issues"]})
                what = f"{len(v['record_issues'])} field issues ({', '.join(kinds)}), {k['records_exported']} of {k['records_expected']} exported"
            lines.append(f"<li><strong>{E(LABEL.get(s['scenario'], s['scenario']))}</strong>: {E(what)}</li>")
        d = diff_lines(prev["rule"], cur["rule"])
        dl = "".join(f'<span class="d-{t}">{"+ " if t == "add" else "- " if t == "del" else "  "}{E(x)}</span>' for t, x in d)
        steps_html.append(f"""
      <div class="round">
        <p class="round-h">Repair {i}, recorded {E(cur['meta']['created_utc'][:10])}</p>
        <ol class="steps">
          <li class="step">
            <h3>Failure report</h3>
            <p>Built from the runs the model may see ({n_seen} of the {n_all} scenarios). It holds what the page showed and which records disagreed with SAP's data, never SAP's values.</p>
            <ul class="fails">{''.join(lines)}</ul>
            <p class="hash">SHA-256 <code>{E(prev['failure_report_sha256'])}</code><br>Replay rebuilds this report from a fresh run and refuses the recorded repair if one character differs.</p>
          </li>
          <li class="step">
            <h3>What the repair changed in the rule</h3>
            <pre class="diff">{dl}</pre>
          </li>
        </ol>
      </div>""")

    # new extraction table for the focus scenario
    trs = []
    for x in l_sc["bench"]["rows"]:
        got = x["got"]["price"] if x["exported"] else None
        okp = x["exported"] and "price" not in x["wrong_fields"]
        old = row(f_sc, x["product_id"])
        trs.append(f"<tr><td>{E(x['name'])}<span class='pid'>{E(x['product_id'])}</span></td>"
                   f"<td class='num was'>{eur(old['got']['price']) if old['exported'] else 'held'}</td>"
                   f"<td class='num'>{eur(got) if got is not None else 'held'}</td><td class='num'>{eur(x['expected']['price'])}</td>"
                   f"<td class='mark {'ok' if okp else 'bad'}'>{'match' if okp else 'differs'}</td></tr>")
    lb = l_sc["bench"]

    # scoreboard
    sb = []
    for r0 in first["results"]:
        rl = scen(last, r0["id"])
        c0, t0 = cell(r0)
        c1, t1 = cell(rl)
        held = " <span class='tag'>held out</span>" if r0["role"] == "held_out" else ""
        sb.append(f"<tr><td><strong>{E(LABEL[r0['id']])}</strong>{held}<span class='sub'>{E(r0['category_name'])}. {E(ORIGIN[r0['origin']])}</span></td>"
                  f"<td class='c-{c0}'>{E(t0)}</td><td class='c-{c1}'>{E(t1)}</td></tr>")
    tot = lambda st: (sum(r["bench"]["price_exact_n"] for r in st["results"] if r["expect"] != "hold_all"),
                      sum(r["bench"]["expected_n"] for r in st["results"] if r["expect"] != "hold_all"),
                      sum(r["bench"]["wrong_accepted_n"] for r in st["results"]))
    t_first, t_last = tot(first), tot(last)

    rh = crops["row"]
    hh = crops["header"]
    refused = res.get("refused")

    page = TEMPLATE
    for k, v in {
        "{{ROW_W}}": f"{rh['w']}", "{{ROW_H}}": f"{rh['h']}",
        "{{RN_X}}": f"{rh['number']['x'] / rh['w'] * 100:.2f}", "{{RN_Y}}": f"{rh['number']['y'] / rh['h'] * 100:.2f}",
        "{{RN_W}}": f"{rh['number']['w'] / rh['w'] * 100:.2f}", "{{RN_H}}": f"{rh['number']['h'] / rh['h'] * 100:.2f}",
        "{{HN_X}}": f"{hh['number']['x'] / hh['w'] * 100:.2f}", "{{HN_Y}}": f"{hh['number']['y'] / hh['h'] * 100:.2f}",
        "{{HN_W}}": f"{hh['number']['w'] / hh['w'] * 100:.2f}", "{{HN_H}}": f"{hh['number']['h'] / hh['h'] * 100:.2f}",
        "{{HDR_W}}": f"{hh['w']}", "{{HDR_H}}": f"{hh['h']}",
        "{{OLD_PRICE}}": eur(f_row["got"]["price"]), "{{OLD_PRICE_RAW}}": E(f_rec["raw"]["price"] or ""),
        "{{OLD_PRICE_JSON}}": E(str(f_row["got"]["price"])),
        "{{SAP_PRICE}}": eur(f_row["expected"]["price"]), "{{SAP_PRICE_JSON}}": E(str(f_row["expected"]["price"])),
        "{{AVAIL}}": E(str(f_row["got"]["availability"])),
        "{{F_STATUS}}": "passed" if f_sc["validator"]["status"] == "pass" else "flagged it",
        "{{F_EXACT}}": str(f_sc["bench"]["price_exact_n"]), "{{F_N}}": str(f_sc["bench"]["expected_n"]),
        "{{F_WRONG}}": str(f_sc["bench"]["wrong_accepted_n"]),
        "{{L_EXACT}}": str(lb["price_exact_n"]), "{{L_N}}": str(lb["expected_n"]), "{{L_WRONG}}": str(lb["wrong_accepted_n"]),
        "{{NEW_PRICE}}": eur(l_row["got"]["price"]) if l_row["exported"] else "held",
        "{{STEPS}}": "\n".join(steps_html), "{{TRS}}": "\n".join(trs), "{{SB}}": "\n".join(sb),
        "{{N_ALL}}": str(n_all), "{{N_REPAIRS}}": "the repair" if len(stages) == 2 else f"{len(stages) - 1} repairs",
        "{{T0_E}}": str(t_first[0]), "{{T0_N}}": str(t_first[1]), "{{T0_W}}": str(t_first[2]),
        "{{T1_E}}": str(t_last[0]), "{{T1_N}}": str(t_last[1]), "{{T1_W}}": str(t_last[2]),
        "{{GEN_DATE}}": E(first["meta"]["created_utc"][:10]), "{{MODELS}}": E(", ".join(models)),
        "{{REPO}}": REPO, "{{RULE0_PRICE}}": E(json.dumps(rule0["fields"]["price"]["locator"])),
        "{{REFUSED}}": "" if not refused else f"<p class='refused'>Last replay refused {E(refused['proposal'])}: {E(refused['reason'])}.</p>",
    }.items():
        page = page.replace(k, v)
    assert "{{" not in page, page[page.index("{{"):page.index("{{") + 40]
    (ROOT / "site/index.html").write_text(page, encoding="utf-8")
    print("site/index.html written")


TEMPLATE = (Path(__file__).resolve().parent / "page_template.html").read_text(encoding="utf-8")

if __name__ == "__main__":
    main()
