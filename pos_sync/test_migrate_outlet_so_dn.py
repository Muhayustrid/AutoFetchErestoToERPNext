"""Self-check mapper SO/DN outlet->JURI (tanpa jaringan).

Jalankan: .venv/bin/python pos_sync/test_migrate_outlet_so_dn.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_outlet_so_dn_to_juri import (ITEM_MAP, build_dn, build_so,  # noqa
                                          cc_map, wh_map)

ITEMS = {
    "BB26009": {"name": "BB26009", "stock_uom": "Botol",
                "uoms": [{"uom": "Botol", "conversion_factor": 1.0}]},
    "PJ260013": {"name": "PJ260013", "stock_uom": "Pcs",
                 "uoms": [{"uom": "Pcs", "conversion_factor": 1.0},
                          {"uom": "Pack", "conversion_factor": 12.0}]},
    "BB260047": {"name": "BB260047", "stock_uom": "g",
                 "uoms": [{"uom": "g", "conversion_factor": 1.0},
                          {"uom": "kg", "conversion_factor": 1000.0}]},
    "PEL260071": {"name": "PEL260071", "stock_uom": "Pcs",
                  "uoms": [{"uom": "Pcs", "conversion_factor": 1.0},
                           {"uom": "slop", "conversion_factor": 50.0}]},
}
CUST = {"CUST260044": "CUST-260210"}


def so_src(items, name="SLS-011026-002", icr="PO226.290926.001", ds=1):
    return {"name": name, "company": "PT. JUARA ROTI INDONESIA",
            "customer": "CUST260044", "transaction_date": "2026-09-29",
            "delivery_date": "2026-10-01", "currency": "IDR",
            "conversion_rate": 1.0, "selling_price_list": "Harga Outlet",
            "set_warehouse": "Gudang Barang Jadi - ROPI",
            "inter_company_order_reference": icr, "docstatus": ds,
            "grand_total": 100.0, "items": items}


def dn_src(items, name="DN-011026-008", ds=1, so="SLS-011026-002"):
    for r in items:
        r.setdefault("against_sales_order", so)
    return {"name": name, "company": "PT. JUARA ROTI INDONESIA",
            "customer": "CUST260044", "posting_date": "2026-10-01",
            "posting_time": "07:30:00", "currency": "IDR",
            "conversion_rate": 1.0, "selling_price_list": "Harga Outlet",
            "set_warehouse": "Gudang Barang Jadi - ROPI", "docstatus": ds,
            "grand_total": 100.0, "items": items}


def row(code, qty, uom, cf, rate=1000.0):
    return {"item_code": code, "qty": qty, "uom": uom,
            "conversion_factor": cf, "rate": rate, "amount": qty * rate,
            "warehouse": "Gudang Barang Jadi - ROPI",
            "cost_center": "Main - ROPI", "price_list_rate": rate}


def main():
    # 1. wh/cc map
    assert wh_map("Gudang Barang Jadi - ROPI") == "Gudang Barang Jadi - JURI"
    assert cc_map("Main - ROPI") == "Main - JURI"
    assert wh_map(None) is None

    # 2. SO: customer dipetakan, gudang JURI, link PO + row PO
    po_rows = {"PO226.290926.001": {"PJ260013": "bk3a1"}}
    p, al = build_so(so_src([row("PJ260013", 2, "Pack", 12.0)]), ITEMS, CUST, {},
                     po_rows)
    assert p["customer"] == "CUST-260210", p["customer"]
    assert p["set_warehouse"] == "Gudang Barang Jadi - JURI"
    assert p["inter_company_order_reference"] == "PO226.290926.001"
    assert p["title"] == "ERESTO SLS-011026-002"
    r0 = p["items"][0]
    assert r0["purchase_order"] == "PO226.290926.001"
    assert r0["purchase_order_item"] == "bk3a1"
    assert r0["warehouse"] == "Gudang Barang Jadi - JURI"
    assert r0["cost_center"] == "Main - JURI"
    assert r0["conversion_factor"] == 12.0 and r0["stock_uom"] == "Pcs"

    # 3. SO: remap bentrok kode BB260059 -> BB26009 + row PO ikut remap
    po_rows2 = {"PO226.290926.001": {"BB26009": "bk9"}}
    p, al = build_so(so_src([row("BB260059", 10, "Botol", 250.0, rate=9000)]),
                     ITEMS, CUST, {}, po_rows2)
    r0 = p["items"][0]
    assert r0["item_code"] == "BB26009" == ITEM_MAP["BB260059"]
    assert r0["uom"] == "Botol" and r0["conversion_factor"] == 1.0
    assert r0["purchase_order_item"] == "bk9", r0.get("purchase_order_item")

    # 4. SO: Kg -> kg, factor dari master
    p, _ = build_so(so_src([row("BB260047", 1, "Kg", 1000.0)]), ITEMS, CUST, {},
                    {"PO226.290926.001": {"BB260047": "x"}})
    assert p["items"][0]["uom"] == "kg"

    # 5. SO: tanpa baris PO pasangan -> alert (tidak gagal)
    p, al = build_so(so_src([row("PJ260013", 1, "Pack", 12.0)]), ITEMS, CUST, {},
                     {})
    assert any("tidak ada baris PO" in a for a in al), al

    # 6. DN: set_posting_time, title, link SO + so_detail dari row SO target
    so_rows = {"SLS-011026-002": {"PJ260013": "row-so-1"}}
    p, al = build_dn(dn_src([row("PJ260013", 2, "Pack", 12.0)]), ITEMS, CUST, {},
                     so_rows)
    assert p["set_posting_time"] == 1
    assert p["title"] == "ERESTO DN-011026-008"
    assert p["set_warehouse"] == "Gudang Barang Jadi - JURI"
    r0 = p["items"][0]
    assert r0["against_sales_order"] == "SLS-011026-002"
    assert r0["so_detail"] == "row-so-1", r0.get("so_detail")

    # 7. DN: item tanpa so_detail -> alert
    p, al = build_dn(dn_src([row("PJ260013", 1, "Pack", 12.0)]), ITEMS, CUST, {},
                     {})
    assert any("so_detail tidak ketemu" in a for a in al), al

    # 8. DN: remap kode ikut terbawa
    p, _ = build_dn(dn_src([row("BB260059", 4, "Botol", 250.0)]), ITEMS, CUST, {},
                    {"SLS-011026-002": {"BB26009": "r9"}})
    assert p["items"][0]["item_code"] == "BB26009"
    assert p["items"][0]["so_detail"] == "r9"

    print("SEMUA SELF-CHECK LOLOS (8/8)")


if __name__ == "__main__":
    main()
