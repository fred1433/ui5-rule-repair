| Rule | Scenario | Category | Prices exact / expected | Held for review | Wrong values exported | Missing / unexpected / duplicated ids | Result |
|---|---|---|---|---|---|---|---|
| 01-generate | base (sap) | Laptops | 11/11 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | reordered (round 1) | Laptops | 11/11 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | shipping_attribute (round 1) | Laptops | 11/11 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | shipping_banner (round 1) | Laptops | 11/11 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | price_hidden (round 1) | Laptops | 0/11 | 11 | 0 | 0/0/0 | as expected |
| 01-generate | delivered_price (round 2) | Laptops | 0/11 | 0 | 11 | 0/0/0 | FAILED |
| 01-generate | sap_1.96.0 (sap) | Laptops | 0/11 | 0 | 0 | 11/0/0 | FAILED |
| 01-generate | base_mice (sap) | Mice (held out) | 7/7 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | shipping_banner_mice (round 1) | Mice (held out) | 7/7 | 0 | 0 | 0/0/0 | as expected |
| 01-generate | delivered_price_mice (round 2) | Mice (held out) | 0/7 | 0 | 7 | 0/0/0 | FAILED |
| 01-generate | sap_1.96.0_mice (sap) | Mice (held out) | 0/7 | 0 | 0 | 7/0/0 | FAILED |
| 01-generate | sap_1.120.30 (sap) | Laptops (held out) | 0/11 | 0 | 0 | 11/0/0 | FAILED |
| 01-generate | sap_1.148.0 (sap) | Laptops (held out) | 11/11 | 0 | 0 | 0/0/0 | as expected |
