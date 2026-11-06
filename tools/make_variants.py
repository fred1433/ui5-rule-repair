"""Builds copy/variants/ from the cached SAP files by exact, asserted text replacements.

Each variant is a named change to the SAP demo, written down here BEFORE the first rule was
generated (see git history).  Nothing in here reads or depends on a generated rule.
"""
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "copy/sdk/1.154.0/test-resources/sap/m/demokit/cart/webapp"
OUT = ROOT / "copy/variants"


def read(rel):
    return (APP / rel).read_text(encoding="utf-8")


def replace_once(text, old, new):
    assert text.count(old) == 1, f"anchor not unique or missing: {old[:60]!r}"
    return text.replace(old, new)


def write(variant, rel, text):
    p = OUT / variant / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def shipping_cost(product):
    """Delivery fee by weight band (our invention, only present in the modified copies)."""
    w = float(product["Weight"])
    return "4.90" if w < 1 else "9.90" if w < 4 else "14.90"


def products_with_shipping():
    data = json.loads(read("localService/mockdata/Products.json"))
    for p in data:
        p["ShippingCost"] = shipping_cost(p)
    return json.dumps(data, indent="\t", ensure_ascii=False)


PRICE_NUMBER = """				number="{
					path : 'Price',
					formatter : '.formatter.price'
				}"
				numberUnit="EUR">"""

HEADER_OPEN = """			<ObjectHeader
				title="{Name}\""""

FIRST_ATTRIBUTE = """				<attributes>
					<ObjectAttribute
						title="{i18n>productSupplierAttributeText}\""""

SHIPPING_BANNER = """			<HBox class="sapUiSmallMarginBeginEnd sapUiTinyMarginTop" alignItems="Center" renderType="Bare">
				<Label text="Shipping" class="sapUiTinyMarginEnd"/>
				<ObjectNumber
					number="{
						path : 'ShippingCost',
						formatter : '.formatter.price'
					}"
					unit="EUR"/>
			</HBox>
"""

LIST_NUMBER = """						number="{
							path : 'Price',
							formatter : '.formatter.price'
						}"
						numberUnit="{CurrencyCode}\""""


def main():
    if OUT.exists():
        for child in OUT.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
    product = read("view/Product.view.xml")
    category = read("view/Category.view.xml")

    # (a) reordered: the category list is sorted by name, descending, instead of ascending.
    write("reordered", "view/Category.view.xml", replace_once(
        category, "path : 'Name',\n\t\t\t\t\t\tdescending : false", "path : 'Name',\n\t\t\t\t\t\tdescending : true"))

    # (b1) shipping_attribute: a labelled "Shipping" attribute becomes the first line of the product header.
    write("shipping_attribute", "localService/mockdata/Products.json", products_with_shipping())
    write("shipping_attribute", "view/Product.view.xml", replace_once(product, FIRST_ATTRIBUTE, """				<attributes>
					<ObjectAttribute
						title="Shipping"
						text="{
							path : 'ShippingCost',
							formatter : '.formatter.price'
						} EUR"/>
					<ObjectAttribute
						title="{i18n>productSupplierAttributeText}\""""))

    # (b2) shipping_banner: a labelled shipping amount (Label + ObjectNumber) is shown above the product header.
    write("shipping_banner", "localService/mockdata/Products.json", products_with_shipping())
    write("shipping_banner", "view/Product.view.xml", replace_once(product, HEADER_OPEN, SHIPPING_BANNER + HEADER_OPEN))

    # (c) price_hidden: as shipping_banner, but the product price is no longer shown, neither in the
    #     product header nor in the category list.  The only amount left on the product page is shipping.
    write("price_hidden", "localService/mockdata/Products.json", products_with_shipping())
    hidden = replace_once(product, HEADER_OPEN, SHIPPING_BANNER + HEADER_OPEN)
    hidden = replace_once(hidden, PRICE_NUMBER, "				>")
    write("price_hidden", "view/Product.view.xml", hidden)
    write("price_hidden", "view/Category.view.xml", replace_once(category, LIST_NUMBER, ""))


# ---------------------------------------------------------------------------------------------
# ROUND 2, written AFTER reading the first generated rule (proposals/01-generate), which reads the
# price in the category list row and was therefore not reached by the round 1 shipping changes.
# This change targets the list row on purpose; the page and the README say so.
# ---------------------------------------------------------------------------------------------

def round_two():
    product = read("view/Product.view.xml")
    category = read("view/Category.view.xml")
    data = json.loads(read("localService/mockdata/Products.json"))
    for p in data:
        p["ShippingCost"] = shipping_cost(p)
        p["DeliveredPrice"] = f"{float(p['Price']) + float(p['ShippingCost']):.2f}"
    write("delivered_price", "localService/mockdata/Products.json", json.dumps(data, indent="\t", ensure_ascii=False))
    # (d) delivered_price: the list row shows the delivered price (product + shipping), with a line
    #     "incl. 14,90 EUR shipping"; the product page keeps the product price in its header and
    #     gains a "Shipping: 14,90 EUR" attribute.
    row = replace_once(category, "path : 'Price',\n\t\t\t\t\t\t\tformatter : '.formatter.price'",
                       "path : 'DeliveredPrice',\n\t\t\t\t\t\t\tformatter : '.formatter.price'")
    row = replace_once(row, """						<attributes>
							<ObjectAttribute visible="true\"""", """						<attributes>
							<ObjectAttribute text="incl. {
								path : 'ShippingCost',
								formatter : '.formatter.price'
							} EUR shipping"/>
							<ObjectAttribute visible="true\"""")
    write("delivered_price", "view/Category.view.xml", row)
    write("delivered_price", "view/Product.view.xml", replace_once(product, FIRST_ATTRIBUTE, """				<attributes>
					<ObjectAttribute
						title="Shipping"
						text="{
							path : 'ShippingCost',
							formatter : '.formatter.price'
						} EUR"/>
					<ObjectAttribute
						title="{i18n>productSupplierAttributeText}\""""))


if __name__ == "__main__":
    main()
    round_two()
    for v in sorted(p.name for p in OUT.iterdir() if p.is_dir()):
        print(v, sorted(str(f.relative_to(OUT / v)) for f in (OUT / v).rglob("*") if f.is_file()))
