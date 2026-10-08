import os
"""Sinkronisasi rantai transaksi Intercompany Delanggu (1-7 Oktober 2026) ke ERPNext Cloud Baru.

Rantai Dokumen:
1. Purchase Order: POO85.021026.001 (RS PKU MUHAMMADIYAH DELANGGU -> PT. JUARA ROTI INDONESIA)
2. Sales Order: SLS-051026-006 (PT. JUARA ROTI INDONESIA -> RS PKU MUHAMMADIYAH DELANGGU)
3. Delivery Note: DN-051026-008 (PT. JUARA ROTI INDONESIA -> RS PKU MUHAMMADIYAH DELANGGU)
4. Purchase Receipt: PR-071026-013 (RS PKU MUHAMMADIYAH DELANGGU <- PT. JUARA ROTI INDONESIA)
"""

import json
import requests
import sys

PROD_BASE = "https://ropierpnext.frappe.cloud"
PROD_KEY = os.environ.get("ERPNEXT_API_KEY", "")

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

class ERPClient:
    def __init__(self, base, key):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Authorization": f"token {key}"})

    def get(self, path, params=None):
        r = self.s.get(self.base + path, params=params, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def post(self, doctype, data):
        r = self.s.post(f"{self.base}/api/resource/{doctype}", json=data, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def put(self, doctype, name, data):
        r = self.s.put(f"{self.base}/api/resource/{doctype}/{name}", json=data, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def rename(self, doctype, old_name, new_name):
        r = self.s.post(
            f"{self.base}/api/method/frappe.client.rename_doc",
            data={"doctype": doctype, "old_name": old_name, "new_name": new_name, "merge": 0},
            timeout=60,
        )
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}

    def submit(self, doctype, name):
        r = self.s.put(f"{self.base}/api/resource/{doctype}/{name}", json={"docstatus": 1}, timeout=60)
        return r.status_code, r.json() if r.headers.get("content-type", "").startswith("application/json") else {"_raw": r.text}


def run_sync():
    old = ERPClient(OLD_BASE, OLD_KEY)
    prod = ERPClient(PROD_BASE, PROD_KEY)

    print(">>> 1. Sync Purchase Order POO85.021026.001")
    st, d = prod.get("/api/resource/Purchase Order/POO85.021026.001")
    if st == 200:
        print("  [OK] PO POO85.021026.001 sudah ada di target")
    else:
        st_src, d_src = old.get("/api/resource/Purchase Order/POO85.021026.001")
        assert st_src == 200, f"Gagal get PO dari old: {d_src}"
        doc = d_src["data"]
        
        items = []
        for it in doc.get("items", []):
            items.append({
                "item_code": it["item_code"],
                "qty": it["qty"],
                "rate": it["rate"],
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": it.get("conversion_factor", 1),
                "warehouse": "Goods In Transit - RPMD",
                "expense_account": "4210.000 - HPP Pembelian - RPMD",
                "cost_center": "Main - RPMD",
                "schedule_date": it.get("schedule_date") or doc.get("schedule_date") or doc.get("transaction_date"),
            })

        po_payload = {
            "company": "RS PKU MUHAMMADIYAH DELANGGU",
            "supplier": "PT. JUARA ROTI INDONESIA",
            "transaction_date": doc.get("transaction_date"),
            "schedule_date": doc.get("schedule_date") or doc.get("transaction_date"),
            "set_warehouse": "Goods In Transit - RPMD",
            "currency": "IDR",
            "remarks": "Migrasi Site Lama | Ref: POO85.021026.001",
            "items": items,
        }
        st_post, d_post = prod.post("Purchase Order", po_payload)
        assert st_post == 200, f"Gagal POST PO: {d_post}"
        temp_name = d_post["data"]["name"]
        st_ren, d_ren = prod.rename("Purchase Order", temp_name, "POO85.021026.001")
        final_po = "POO85.021026.001" if st_ren == 200 else temp_name
        st_sub, d_sub = prod.submit("Purchase Order", final_po)
        assert st_sub == 200, f"Gagal submit PO: {d_sub}"
        print(f"  [+] PO {final_po} berhasil dibuat & disubmit")

    print("\n>>> 2. Sync Sales Order SLS-051026-006")
    st, d = prod.get("/api/resource/Sales Order/SLS-051026-006")
    if st == 200:
        print("  [OK] SO SLS-051026-006 sudah ada di target")
    else:
        st_src, d_src = old.get("/api/resource/Sales Order/SLS-051026-006")
        assert st_src == 200, f"Gagal get SO dari old: {d_src}"
        doc = d_src["data"]

        items = []
        for it in doc.get("items", []):
            items.append({
                "item_code": it["item_code"],
                "qty": it["qty"],
                "rate": it["rate"],
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": it.get("conversion_factor", 1),
                "warehouse": "Gudang Barang Jadi - JURI",
                "delivery_date": it.get("delivery_date") or doc.get("delivery_date") or doc.get("transaction_date"),
            })

        so_payload = {
            "company": "PT. JUARA ROTI INDONESIA",
            "customer": "CUST-260207",
            "transaction_date": doc.get("transaction_date"),
            "delivery_date": doc.get("delivery_date") or doc.get("transaction_date"),
            "set_warehouse": "Gudang Barang Jadi - JURI",
            "currency": "IDR",
            "inter_company_order_reference": "POO85.021026.001",
            "remarks": "Migrasi Site Lama | Ref: SLS-051026-006",
            "items": items,
        }
        st_post, d_post = prod.post("Sales Order", so_payload)
        assert st_post == 200, f"Gagal POST SO: {d_post}"
        temp_name = d_post["data"]["name"]
        st_ren, d_ren = prod.rename("Sales Order", temp_name, "SLS-051026-006")
        final_so = "SLS-051026-006" if st_ren == 200 else temp_name
        st_sub, d_sub = prod.submit("Sales Order", final_so)
        assert st_sub == 200, f"Gagal submit SO: {d_sub}"
        print(f"  [+] SO {final_so} berhasil dibuat & disubmit")

    print("\n>>> 3. Sync Delivery Note DN-051026-008")
    st, d = prod.get("/api/resource/Delivery Note/DN-051026-008")
    if st == 200:
        print("  [OK] DN DN-051026-008 sudah ada di target")
    else:
        st_src, d_src = old.get("/api/resource/Delivery Note/DN-051026-008")
        assert st_src == 200, f"Gagal get DN dari old: {d_src}"
        doc = d_src["data"]

        # Ambil row name dari SO di target
        _, d_target_so = prod.get("/api/resource/Sales Order/SLS-051026-006")
        target_so_items = {it["item_code"]: it["name"] for it in d_target_so.get("data", {}).get("items", [])}

        items = []
        for it in doc.get("items", []):
            items.append({
                "item_code": it["item_code"],
                "qty": it["qty"],
                "rate": it["rate"],
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": it.get("conversion_factor", 1),
                "warehouse": "Gudang Barang Jadi - JURI",
                "expense_account": "4210.000 - HPP Pembelian - JURI",
                "cost_center": "Main - JURI",
                "against_sales_order": "SLS-051026-006",
                "so_detail": target_so_items.get(it["item_code"]),
            })

        dn_payload = {
            "company": "PT. JUARA ROTI INDONESIA",
            "customer": "CUST-260207",
            "posting_date": doc.get("posting_date"),
            "set_posting_time": 1,
            "posting_time": doc.get("posting_time") or "08:17:00",
            "set_warehouse": "Gudang Barang Jadi - JURI",
            "currency": "IDR",
            "remarks": "Migrasi Site Lama | Ref: DN-051026-008",
            "items": items,
        }
        st_post, d_post = prod.post("Delivery Note", dn_payload)
        assert st_post == 200, f"Gagal POST DN: {d_post}"
        temp_name = d_post["data"]["name"]
        st_ren, d_ren = prod.rename("Delivery Note", temp_name, "DN-051026-008")
        final_dn = "DN-051026-008" if st_ren == 200 else temp_name
        st_sub, d_sub = prod.submit("Delivery Note", final_dn)
        assert st_sub == 200, f"Gagal submit DN: {d_sub}"
        print(f"  [+] DN {final_dn} berhasil dibuat & disubmit")

    print("\n>>> 4. Sync Purchase Receipt PR-071026-013")
    st, d = prod.get("/api/resource/Purchase Receipt/PR-071026-013")
    if st == 200:
        print("  [OK] PR PR-071026-013 sudah ada di target")
    else:
        st_src, d_src = old.get("/api/resource/Purchase Receipt/PR-071026-013")
        assert st_src == 200, f"Gagal get PR dari old: {d_src}"
        doc = d_src["data"]

        # Ambil row name dari PO dan DN di target
        _, d_target_po = prod.get("/api/resource/Purchase Order/POO85.021026.001")
        target_po_items = {it["item_code"]: it["name"] for it in d_target_po.get("data", {}).get("items", [])}

        _, d_target_dn = prod.get("/api/resource/Delivery Note/DN-051026-008")
        target_dn_items = {it["item_code"]: it["name"] for it in d_target_dn.get("data", {}).get("items", [])}

        items = []
        for it in doc.get("items", []):
            items.append({
                "item_code": it["item_code"],
                "qty": it["qty"],
                "rate": it["rate"],
                "uom": it.get("uom"),
                "stock_uom": it.get("stock_uom"),
                "conversion_factor": it.get("conversion_factor", 1),
                "warehouse": "Stores - RPMD",
                "expense_account": "4210.000 - HPP Pembelian - RPMD",
                "cost_center": "Main - RPMD",
                "purchase_order": "POO85.021026.001",
                "purchase_order_item": target_po_items.get(it["item_code"]),
                "delivery_note_item": target_dn_items.get(it["item_code"]),
            })

        pr_payload = {
            "company": "RS PKU MUHAMMADIYAH DELANGGU",
            "supplier": "PT. JUARA ROTI INDONESIA",
            "posting_date": doc.get("posting_date"),
            "set_posting_time": 1,
            "posting_time": doc.get("posting_time") or "10:55:25",
            "set_warehouse": "Stores - RPMD",
            "currency": "IDR",
            "inter_company_reference": "DN-051026-008",
            "remarks": "Migrasi Site Lama | Ref: PR-071026-013 (eResto PCO85.051026.001)",
            "items": items,
        }
        st_post, d_post = prod.post("Purchase Receipt", pr_payload)
        assert st_post == 200, f"Gagal POST PR: {d_post}"
        temp_name = d_post["data"]["name"]
        st_ren, d_ren = prod.rename("Purchase Receipt", temp_name, "PR-071026-013")
        final_pr = "PR-071026-013" if st_ren == 200 else temp_name
        st_sub, d_sub = prod.submit("Purchase Receipt", final_pr)
        assert st_sub == 200, f"Gagal submit PR: {d_sub}"
        print(f"  [+] PR {final_pr} berhasil dibuat & disubmit")

    print("\n================ SINKRONISASI SELESAI ================")


if __name__ == "__main__":
    run_sync()
