# ui5-rule-repair

An agent that writes a JSON extraction rule for a real enterprise web app (SAP's OpenUI5 Shopping Cart demo), checks it in a browser, and repairs it when the app changes. Every price it exports is compared with SAP's own data.

```bash
git clone https://github.com/fred1433/ui5-rule-repair && cd ui5-rule-repair
pip install -r requirements.txt && python -m playwright install chromium
python -m ui5rules replay        # about 4 minutes, no API key, no model call
```

Result of the last replay (`results/TABLE.md` holds the raw table, `results/results.json` every record):

| App version | Category | Origin | First rule (01-generate) | Repaired rule (02-repair) |
|---|---|---|---|---|
| OpenUI5 1.154.0 | Laptops | SAP release, unmodified | 11 of 11 exact | 11 of 11 exact |
| List sorted Z to A | Laptops | Our change, written before the first rule | 11 of 11 exact | 11 of 11 exact |
| Shipping line in the product header | Laptops | Our change, written before the first rule | 11 of 11 exact | 11 of 11 exact |
| Shipping amount above the product header | Laptops | Our change, written before the first rule | 11 of 11 exact | 11 of 11 exact |
| Product price removed from screen | Laptops | Our change, written before the first rule | 11 of 11 held, none exported | 11 of 11 held, none exported |
| List shows price plus shipping | Laptops | Our change, written after reading it | 0 of 11 exact, 11 wrong exported | 11 of 11 exact |
| OpenUI5 1.96.0 | Laptops | SAP release, unmodified | 0 of 11: run stopped, nothing exported | 11 of 11 exact |
| OpenUI5 1.154.0 | Mice (held out) | SAP release, unmodified | 7 of 7 exact | 7 of 7 exact |
| Shipping amount above the product header | Mice (held out) | Our change, written before the first rule | 7 of 7 exact | 7 of 7 exact |
| List shows price plus shipping | Mice (held out) | Our change, written after reading it | 0 of 7 exact, 7 wrong exported | 7 of 7 exact |
| OpenUI5 1.96.0 | Mice (held out) | SAP release, unmodified | 0 of 7: run stopped, nothing exported | 7 of 7 exact |
| OpenUI5 1.120.30 | Laptops (held out) | SAP release, unmodified | 11 of 11 exact | 11 of 11 exact |
| OpenUI5 1.148.0 | Laptops (held out) | SAP release, unmodified | 11 of 11 exact | 11 of 11 exact |

Totals over the 12 runs where every price should be exported: **80 of 116 prices exact, 18 wrong values exported** with the first rule; **116 of 116 exact, 0 wrong** after one repair. In the 13th run the product price is removed from the screen: both rules hold all 11 records for review and export nothing.

Page: https://theaipipe.com/demos/ui5-rule-repair/

## What happened

1. **Generation.** The agent opened the app, walked to the Laptops category and two products, and recorded a distilled view of the rendered DOM (`proposals/01-generate/observations.json`). From that and a business task ("for each laptop: reference, price, currency, availability") the model wrote the first rule. Nobody edited it.
2. **Round 1 changes, written before the rule existed** (`tools/make_variants.py`, first commit): list reordered, a shipping line in the product header, a shipping amount above the header, the product price removed. The first rule survived all four: it reads the price in the category **list row**, which none of them touched.
3. **Round 2 change, written after reading the rule, aimed at it on purpose:** the list row shows the delivered price (product plus shipping). The rule exported 1003.90 for a 989 EUR laptop, 11 of 11 laptops wrong, and its runtime checks passed. Only the comparison with SAP's data caught it.
4. **A real break, not ours:** SAP's own 1.96.0 release of the same demo uses `listbox`/`option` roles where 1.154.0 uses `list`/`listitem`. The rule's first wait never ended; nothing was exported (no wrong value).
5. **Repair.** The failure report (what the page showed, which records disagreed with SAP, never SAP's values) went to the model with fresh observations of the two failing versions. The repaired rule reads price, currency and availability on the product page and no longer depends on the list role. Replay re-runs it on all 13 scenarios, including 6 the model never saw (Mice category, SAP 1.120.30 and 1.148.0).

## Two checks, kept apart

* **Runtime validator** (`ui5rules/validator.py`) sees only the page: missing field, ambiguous match (two candidates), wrong type, value outside the enum, item count different from the counter on screen, duplicate ids. A flagged record is held for review; nothing is invented. It cannot see a single, well-formed, wrong amount.
* **Oracle** (`ui5rules/oracle.py`) is SAP's `localService/mockdata/Products.json` pinned at 1.154.0 (123 products, 11 laptops, 7 mice). Only the bench reads it. Join on ProductId taken from the URL after the click, price compared as a decimal, currency separately. A test checks that 1.96.0, 1.120.30 and 1.148.0 ship the same products and prices.

## Frozen model output, linked by hash

`proposals/NN-*/` holds the prompt, the model's raw answer, the rule and `meta.json` (SHA-256 of the input, prompt, parent rule and rule). Proposals were made with `python -m ui5rules generate` and `python -m ui5rules repair`, which call `claude -p` on a Claude subscription with every tool disabled, in an empty folder (they refuse to run if `ANTHROPIC_API_KEY` is set). Model: claude-opus-5-5. API cost: 0 $.

Replay calls no model. It re-observes the app and checks the observation hash of the generation, rebuilds the failure report from fresh runs and **refuses the recorded repair if the report's hash differs** (`tests/test_replay_refusal.py`).

## The rule format

Ours, documented in `ui5rules/rules.py` (`FORMAT_DOC`): plain JSON, no code. Navigation steps (`wait_for`, `click`, `read_count`), an item locator, and per field: where it is (`item`, `detail`, `url`), a locator by CSS, exact text, ARIA role or visible label, a type (`id`, `decimal` with its separators, `currency_code`, `enum` with a map, `text`) and optional contracts (`pick: single`, label anchor). Generated UI5 ids (`__xmlview0--…`, `__item5-…`) are refused by the static check. The format of your own engine is unknown to us; mapping one rule to it is a small, concrete exercise.

## The app copy

`copy/sdk/` is a byte-for-byte cache of the files sdk.openui5.org serves for the demo and its UI5 runtime (1.96.0, 1.120.30, 1.148.0, 1.154.0), Apache License 2.0 (`copy/LICENSE-OpenUI5.txt`, `NOTICE`). `copy/variants/` holds our modifications, listed in `copy/variants/README.md`. `ui5rules/server.py` serves them on 127.0.0.1 only and never fetches from SAP during runs or tests, so repeated runs put no load on sdk.openui5.org. The app's `Component-preload.js` is not served, in any variant, so that the individual (possibly modified) view files are the ones in use.

The engine settles the DOM before each click and retries a click once when nothing happened: UI5 1.96.0 swallows the first click on a list item in headless Chromium. That policy applies to every rule alike.

## Tests

```bash
python -m pytest -q
```

Offline tests (parsing, validator contracts, oracle join, hashes, refusal of a mismatched repair, SAP data identical across releases) and browser tests on the local copy.

## Not done

* A second OpenUI5 app (Worklist) was not attempted; the multi-app claim rests on four SAP releases and two categories of one app.
* The runs are desktop only (1440x900); phone layouts were not tested.
* One generation and one repair were recorded. How often the model writes a rule that reads the list row (rather than the product page) was not measured.

Built by Frederic de Lavenne de Choulot, The AI Pipe. A 15-minute call: https://cal.theaipipe.com
