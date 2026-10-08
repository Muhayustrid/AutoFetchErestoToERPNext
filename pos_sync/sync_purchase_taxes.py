import os
"""Sinkronisasi Purchase Taxes and Charges untuk Purchase Order dan Purchase Receipt PT. JUARA ROTI INDONESIA (1-7 Okt 2026).

Menyelaraskan child table taxes, total_taxes_and_charges, dan grand_total agar 100% klop dengan ERPNext Lama.
"""

import json
import requests

OLD_BASE = "https://rotiropi.j.frappe.cloud"
OLD_KEY = os.environ.get("ERPNEXT_OLD_CLOUD_API_KEY", "")

PROD_BASE = "https://ropierpnext.frappe.cloud"
PROD_KEY = os.environ.get("ERPNEXT_API_KEY", "")

TAX_FIELDS = [
    "taxes", "taxes_and_charges", "total_taxes_and_charges",
    "grand_total", "base_grand_total", "net_total", "base_net_total"
]


def tax_template_map(old_tpl):
    if not old_tpl:
        return "Purchase Tax - JURI"
    if "Include" in old_tpl:
        return "Purchase Tax (Termasuk Pajak) - JURI"
    return "Purchase Tax - JURI"


def set_allow_on_submit(s_prod, doctype, value=1):
    for fld in TAX_FIELDS:
        s_prod.post(f"{PROD_BASE}/api/resource/Property Setter", json={
            "doctype": "Property Setter",
            "doctype_or_field": "DocField",
            "doc_type": doctype,
            "field_name": fld,
            "property": "allow_on_submit",
            "property_type": "Check",
            "value": str(value)
        })


def sync_taxes():
    s_old = requests.Session()
    s_old.headers.update({"Authorization": f"token {OLD_KEY}"})

    s_prod = requests.Session()
    s_prod.headers.update({"Authorization": f"token {PROD_KEY}"})

    # 1. Pastikan allow_on_submit aktif
    set_allow_on_submit(s_prod, "Purchase Order", 1)
    set_allow_on_submit(s_prod, "Purchase Receipt", 1)

    # 2. Ambil seluruh PO target yang ada di Prod
    r = s_prod.get(f"{PROD_BASE}/api/resource/Purchase Order", params={
        "filters": json.dumps([["company", "=", "PT. JUARA ROTI INDONESIA"]]),
        "fields": json.dumps(["name"]),
        "limit_page_length": 500
    })
    target_pos = [p["name"] for p in r.json().get("data", [])]

    # 3. Ambil seluruh PR target yang ada di Prod
    r = s_prod.get(f"{PROD_BASE}/api/resource/Purchase Receipt", params={
        "filters": json.dumps([["company", "=", "PT. JUARA ROTI INDONESIA"]]),
        "fields": json.dumps(["name"]),
        "limit_page_length": 500
    })
    target_prs = [p["name"] for p in r.json().get("data", [])]

    print(f"Memeriksa pajak untuk {len(target_pos)} PO dan {len(target_prs)} PR...")

    po_updated = []
    for po_name in target_pos:
        r_old = s_old.get(f"{OLD_BASE}/api/resource/Purchase Order/{po_name}")
        if r_old.status_code != 200:
            continue
        old_doc = r_old.json().get("data", {})
        old_taxes = old_doc.get("taxes", [])
        if not old_taxes and not old_doc.get("total_taxes_and_charges"):
            continue

        new_taxes = []
        for t in old_taxes:
            new_taxes.append({
                "category": t.get("category", "Total"),
                "add_deduct_tax": t.get("add_deduct_tax", "Add"),
                "charge_type": t.get("charge_type", "On Net Total"),
                "account_head": "1152.001 - PPN Masukan - JURI",
                "description": "PPN Masukan @ 11.0 - JURI",
                "rate": t.get("rate", 11.0),
                "cost_center": "Main - JURI",
                "tax_amount": t.get("tax_amount"),
                "tax_amount_after_discount_amount": t.get("tax_amount_after_discount_amount") or t.get("tax_amount"),
                "total": t.get("total"),
                "base_tax_amount": t.get("base_tax_amount") or t.get("tax_amount"),
                "base_total": t.get("base_total") or t.get("total"),
            })

        payload = {
            "taxes_and_charges": tax_template_map(old_doc.get("taxes_and_charges")),
            "total_taxes_and_charges": old_doc.get("total_taxes_and_charges"),
            "grand_total": old_doc.get("grand_total"),
            "base_grand_total": old_doc.get("base_grand_total") or old_doc.get("grand_total"),
            "net_total": old_doc.get("net_total"),
            "base_net_total": old_doc.get("base_net_total") or old_doc.get("net_total"),
            "taxes": new_taxes,
        }
        r_put = s_prod.put(f"{PROD_BASE}/api/resource/Purchase Order/{po_name}", json=payload)
        if r_put.status_code == 200:
            po_updated.append((po_name, old_doc.get("total_taxes_and_charges"), old_doc.get("grand_total")))
            print(f"  [OK] PO {po_name:16s} Pajak: Rp {old_doc.get('total_taxes_and_charges'):,.2f} | Total: Rp {old_doc.get('grand_total'):,.2f}")
        else:
            print(f"  [FAIL] PO {po_name}: {r_put.text[:200]}")

    pr_updated = []
    for pr_name in target_prs:
        r_old = s_old.get(f"{OLD_BASE}/api/resource/Purchase Receipt/{pr_name}")
        if r_old.status_code != 200:
            continue
        old_doc = r_old.json().get("data", {})
        old_taxes = old_doc.get("taxes", [])
        if not old_taxes and not old_doc.get("total_taxes_and_charges"):
            continue

        new_taxes = []
        for t in old_taxes:
            new_taxes.append({
                "category": t.get("category", "Total"),
                "add_deduct_tax": t.get("add_deduct_tax", "Add"),
                "charge_type": t.get("charge_type", "On Net Total"),
                "account_head": "1152.001 - PPN Masukan - JURI",
                "description": "PPN Masukan @ 11.0 - JURI",
                "rate": t.get("rate", 11.0),
                "cost_center": "Main - JURI",
                "tax_amount": t.get("tax_amount"),
                "tax_amount_after_discount_amount": t.get("tax_amount_after_discount_amount") or t.get("tax_amount"),
                "total": t.get("total"),
                "base_tax_amount": t.get("base_tax_amount") or t.get("tax_amount"),
                "base_total": t.get("base_total") or t.get("total"),
            })

        payload = {
            "taxes_and_charges": tax_template_map(old_doc.get("taxes_and_charges")),
            "total_taxes_and_charges": old_doc.get("total_taxes_and_charges"),
            "grand_total": old_doc.get("grand_total"),
            "base_grand_total": old_doc.get("base_grand_total") or old_doc.get("grand_total"),
            "net_total": old_doc.get("net_total"),
            "base_net_total": old_doc.get("base_net_total") or old_doc.get("net_total"),
            "taxes": new_taxes,
        }
        r_put = s_prod.put(f"{PROD_BASE}/api/resource/Purchase Receipt/{pr_name}", json=payload)
        if r_put.status_code == 200:
            pr_updated.append((pr_name, old_doc.get("total_taxes_and_charges"), old_doc.get("grand_total")))
            print(f"  [OK] PR {pr_name:16s} Pajak: Rp {old_doc.get('total_taxes_and_charges'):,.2f} | Total: Rp {old_doc.get('grand_total'):,.2f}")
        else:
            print(f"  [FAIL] PR {pr_name}: {r_put.text[:200]}")

    # Pulihkan allow_on_submit
    set_allow_on_submit(s_prod, "Purchase Order", 0)
    set_allow_on_submit(s_prod, "Purchase Receipt", 0)

    print(f"\nSelesai: {len(po_updated)} PO dan {len(pr_updated)} PR diperbarui dengan pajak lengkap.")


if __name__ == "__main__":
    sync_taxes()
