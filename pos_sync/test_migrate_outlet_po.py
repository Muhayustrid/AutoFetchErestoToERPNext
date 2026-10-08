"""Self-check mapper PO outlet->JURI (tanpa jaringan).

Jalankan: .venv/bin/python pos_sync/test_migrate_outlet_po.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_outlet_po_to_juri import (ITEM_MAP, SKIP_ROWS, build_payload,  # noqa
                                       target_wh_for, wh_target)


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
    "PEL260072": {"name": "PEL260072", "stock_uom": "Pcs",
                  "uoms": [{"uom": "Pcs", "conversion_factor": 1.0},
                           {"uom": "Pack", "conversion_factor": 10.0}]},
}


def src(name="POX.011026.001", items=None, docstatus=1, gt=100.0):
    return {
        "name": name, "company": "RS CONTOH", "transaction_date": "2026-10-01",
        "schedule_date": "2026-10-02", "currency": "IDR", "conversion_rate": 1.0,
        "buying_price_list": "Harga Outlet", "set_warehouse": "Goods In Transit - X",
        "docstatus": docstatus, "grand_total": gt,
        "items": items if items is not None else [],
    }


def row(code, qty, uom, cf, rate=1000.0, amount=None):
    return {"item_code": code, "qty": qty, "rate": rate, "uom": uom,
            "conversion_factor": cf, "stock_uom": "?", "amount": amount or qty * rate,
            "warehouse": "Goods In Transit - X",
            "expense_account": "4210.000 - HPP Pembelian - X",
            "cost_center": "Main - X", "schedule_date": "2026-10-02"}


def main():
    # 1. ID + title idempotensi + supplier tetap JURI
    p, sk, al = build_payload(src(items=[row("PJ260013", 2, "Pack", 12)]), ITEMS)
    assert p["title"] == "ERESTO POX.011026.001", p["title"]
    assert p["supplier"] == "PT. JUARA ROTI INDONESIA"
    assert sk == [] and al == []
    r0 = p["items"][0]
    assert r0["uom"] == "Pack" and r0["conversion_factor"] == 12.0
    assert r0["stock_uom"] == "Pcs"

    # 2. remap bentrok kode BB260059 -> BB26009 (uom Botol jadi stock_uom, cf=1)
    p, sk, al = build_payload(src(items=[row("BB260059", 10, "Botol", 250.0,
                                              rate=9000)]), ITEMS)
    r0 = p["items"][0]
    assert r0["item_code"] == "BB26009" == ITEM_MAP["BB260059"]
    assert r0["uom"] == "Botol" and r0["conversion_factor"] == 1.0
    assert r0["stock_uom"] == "Botol"
    assert any("factor 250.0 -> 1.0" in a for a in al), al

    # 3. Kg -> kg + factor dari master
    p, _, al = build_payload(src(items=[row("BB260047", 1, "Kg", 1000.0)]), ITEMS)
    r0 = p["items"][0]
    assert r0["uom"] == "kg" and r0["conversion_factor"] == 1000.0
    assert r0["stock_uom"] == "g"

    # 4. UOM absen & cf==1 -> balik ke stock_uom (artefak Pack utk item Pcs)
    p, _, al = build_payload(src(items=[row("PEL260071", 2, "Pack", 1.0)]), ITEMS)
    r0 = p["items"][0]
    assert r0["uom"] == "Pcs" and r0["conversion_factor"] == 1.0
    assert any("absen & cf=1" in a for a in al), al

    # 5. UOM ditambahkan di master -> factor ikut master (Pack=10)
    p, _, _ = build_payload(src(items=[row("PEL260072", 5, "Pack", 10.0)]), ITEMS)
    r0 = p["items"][0]
    assert r0["uom"] == "Pack" and r0["conversion_factor"] == 10.0

    # 6. baris skip terdokumentasi → hilang dari payload, ada di `skipped`
    s = src(name="PO185.051026.001",
            items=[row("PEL260007", 1, "Pack", 100.0, rate=158000.0),
                   row("PJ260013", 1, "Pack", 12.0)])
    assert "PEL260007" in SKIP_ROWS["PO185.051026.001"]
    p, sk, _ = build_payload(s, ITEMS)
    assert [i["item_code"] for i in p["items"]] == ["PJ260013"]
    assert sk[0]["item"] == "PEL260007" and sk[0]["amount"] == 158000.0

    # 7. akun legacy CoGS -> HPP Pembelian
    r = row("PJ260013", 1, "Pack", 12.0)
    r["expense_account"] = "Cost of Goods Sold - RFB"
    r["cost_center"] = "Main - RFB"
    p, _, _ = build_payload(src(items=[r]), ITEMS)
    assert p["items"][0]["expense_account"] == "4210.000 - HPP Pembelian - RFB"

    # 8. gudang target = 'Stores - <ABBR>' (revisi user 2026-10-08), head+rows
    p, _, _ = build_payload(src(items=[row("PJ260013", 1, "Pack", 12.0)]), ITEMS)
    assert p["set_warehouse"] == "Stores - X", p["set_warehouse"]
    assert p["items"][0]["warehouse"] == "Stores - X", p["items"][0]["warehouse"]
    assert wh_target("Goods In Transit - RFB", "RFB") == "Stores - RFB"
    assert wh_target(None, "RRSC") == "Stores - RRSC"
    # abbr dari argumen menang atas suffix nama gudang sumber
    p2, _, _ = build_payload(src(items=[row("PJ260013", 1, "Pack", 12.0)]),
                             ITEMS, {"RS CONTOH": "RCONTOH"})
    assert p2["set_warehouse"] == "Stores - RCONTOH", p2["set_warehouse"]
    assert p2["items"][0]["warehouse"] == "Stores - RCONTOH"

    # 9. REGRESI: company tidak ada di peta abbr -> JANGAN pakai nama company
    #    (bug lama 'Stores - RS CONTOH'); harus fallback ke suffix gudang sumber.
    assert target_wh_for({}, "RS CONTOH", "Goods In Transit - RCONTOH") \
        == "Stores - RCONTOH"
    assert target_wh_for({"RS CONTOH": "RCONTOH"}, "RS CONTOH",
                         "Goods In Transit - RFB") == "Stores - RCONTOH"
    p3, _, _ = build_payload(src(items=[row("PJ260013", 1, "Pack", 12.0)]),
                             ITEMS, {})
    assert p3["set_warehouse"] == "Stores - X", p3["set_warehouse"]
    assert p3["items"][0]["warehouse"] == "Stores - X"

    print("SEMUA SELF-CHECK LOLOS (9/9)")


if __name__ == "__main__":
    main()
