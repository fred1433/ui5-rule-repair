# Modified copies of the SAP demo

`copy/sdk/` is an unmodified byte-for-byte cache of the files that https://sdk.openui5.org/1.154.0/
serves for the OpenUI5 Shopping Cart demo (`test-resources/sap/m/demokit/cart/webapp/`) and the UI5
runtime it loads. OpenUI5 is licensed under the Apache License 2.0 (`copy/LICENSE-OpenUI5.txt`,
third-party notices in `copy/THIRDPARTY-OpenUI5.txt`).

The folders here are **our modifications**, built by `tools/make_variants.py` from the cached files
with asserted text replacements. They were written and committed before the first rule was generated.

| Variant | What we changed |
|---|---|
| `reordered` | The category list sorts products by name, descending (SAP: ascending). |
| `shipping_attribute` | Each product gets a `ShippingCost` (4,90 / 9,90 / 14,90 EUR by weight band). The product header shows it as its first attribute, `Shipping: 14,90 EUR`. |
| `shipping_banner` | Same `ShippingCost`; a labelled line `Shipping 14,90 EUR` (sap.m Label + ObjectNumber) sits above the product header. |
| `price_hidden` | As `shipping_banner`, but the product price is removed from the product header and from the category list. |

The local server never serves the app's `Component-preload.js` (in any variant, base included), so that
UI5 loads the individual view files and an override is always the file in use.
