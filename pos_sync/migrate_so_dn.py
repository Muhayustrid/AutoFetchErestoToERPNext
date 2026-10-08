"""Tahap jual: Sales Order -> Delivery Note ke site BARU.

Sumber: pos_sync/window/Sales_Order.json + Delivery_Note.json.
Aturan (docs/06): customer via customer_name (cache), gudang ROPI->JURI,
pajak NULL (tak ada di jendela), baris DN yg merujuk SO September jadi mandiri
(against_* dikosongkan, nomor lama di remarks baris).

Usage: python3 migrate_so_dn.py [--dry-run]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP, ITEM_MAP, eresto_key, wh_map  # noqa: E402


def load_env(path="/tmp/eresto_mig.env"):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


DROP_HDR = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status", "amended_from",
    "pos_profile", "posa_pos_opening_shift",
    "letter_head", "inter_company_order_reference",
    "company_address", "company_address_display",
    "shipping_address", "shipping_address_display",
    "shipping_address_name",
    "billing_address", "billing_address_display",
    "dispatch_address", "dispatch_address_display",
    "dispatch_address_name",
    "customer_address", "address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
    "_user_tags", "_comments", "_assign", "_liked_by",
}
DROP_ROW = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "parent", "parentfield", "parenttype", "docstatus",
    "against_sales_order", "so_detail", "sales_order", "sales_order_item",
    "purchase_order", "purchase_order_item",
    "bom_no",
    "amended_from",
}

# customer kode lama -> customer_name site baru (kode CUST-xxx beda arti)
CUSTOMER_ALIAS = {
    "CUST260029": "RSUD KOTA PRABUMULIH",
    "CUST260044": "RSI FATIMAH BANYUWANGI",
}

PRICE_LIST_FALLBACK = {
    "Harga Outlet Franchise": "Harga Outlet",
}


def suffix_map(old, abbr):
    if not old or not abbr:
        return old
    if " - " in old:
        return old.rsplit(" - ", 1)[0] + " - " + abbr
    return old


ITEM_GROUP_MAP = {
    "Produk Jadi": "Produk Jadi Pabrik",
}


def comp_abbr(erp_cache, company):
    return erp_cache.get(company, "")


def resolve_customer(cus, old):
    if old in cus:
        return cus[old]
    alias = CUSTOMER_ALIAS.get(old, "")
    if alias and alias in cus:
        return cus[alias]
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])
    st, d = erp.get("/api/resource/Customer",
                    {"fields": '["name","customer_name"]',
                     "limit_page_length": 1000})
    cus = {c["customer_name"]: c["name"] for c in d.get("data", [])}
    cus.update({c["name"]: c["name"] for c in d.get("data", [])})
    st, d = erp.get("/api/resource/Company",
                    {"fields": '["name","abbr"]', "limit_page_length": 500})
    abbr = {c["name"]: c.get("abbr", "") for c in d.get("data", [])}
    wdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window")

    failed, so_map = [], {}
    for h in sorted(json.load(open(os.path.join(wdir, "Sales_Order.json"))),
                    key=lambda x: x["name"]):
        key = eresto_key(h["name"])
        if erp.find_by_remark("Sales Order", "title", key):
            so_map[h["name"]] = "EXISTS"
            continue
        # SO tak punya remarks -> kunci idempotency di title
        p = {"doctype": "Sales Order", "title": key}
        for k, v in h.items():
            if k in DROP_HDR or k == "items" or k.startswith("_"):
                continue
            p[k] = v
        new_cus = resolve_customer(cus, h.get("customer"))
        if not new_cus:
            failed.append({"lama": h["name"], "alasan": "customer tidak ketemu"})
            continue
        p["customer"] = new_cus
        if p.get("selling_price_list") in PRICE_LIST_FALLBACK:
            p["selling_price_list"] = PRICE_LIST_FALLBACK[p["selling_price_list"]]
        if p.get("set_warehouse"):
            p["set_warehouse"] = wh_map(p["set_warehouse"])
        rows = []
        a = abbr.get(h.get("company"), "")
        for it in h.get("items", []):
            q = {k: v for k, v in it.items()
                 if k not in DROP_ROW and not k.startswith("_")}
            q["item_code"] = ITEM_MAP.get(it["item_code"], it["item_code"])
            if it.get("item_group") in ITEM_GROUP_MAP:
                q["item_group"] = ITEM_GROUP_MAP[it["item_group"]]
            if q.get("warehouse"):
                q["warehouse"] = wh_map(q["warehouse"])
            q["cost_center"] = suffix_map(it.get("cost_center"), a)
            q["expense_account"] = suffix_map(it.get("expense_account"), a)
            rows.append(q)
        p["items"] = rows
        if args.dry_run:
            so_map[h["name"]] = "DRY-RUN"
            continue
        st, d = erp.post("Sales Order", p)
        if st != 200:
            failed.append({"lama": h["name"],
                           "alasan": f"POST {st}: {json.dumps(d)[:300]}"})
            continue
        name = d["data"]["name"]
        so_map[h["name"]] = name
        if h.get("docstatus") == 1:
            st2, d2 = erp.submit("Sales Order", name)
            if st2 != 200:
                failed.append({"lama": h["name"], "baru": name,
                               "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:200]}"})
        if h.get("docstatus") == 2 and st == 200:
            st2, d2 = erp.submit("Sales Order", name)
            if st2 == 200:
                erp.cancel("Sales Order", name)
    print(f"  SO: gagal={len(failed)}")

    dn_failed = []
    for h in sorted(json.load(open(os.path.join(wdir, "Delivery_Note.json"))),
                    key=lambda x: x["name"]):
        key = eresto_key(h["name"])
        if erp.find_by_remark("Delivery Note", "title", key):
            continue
        # DN tak punya remarks -> kunci idempotency di title
        p = {"doctype": "Delivery Note", "title": key}
        for k, v in h.items():
            if k in DROP_HDR or k == "items" or k.startswith("_"):
                continue
            p[k] = v
        new_cus = resolve_customer(cus, h.get("customer"))
        if not new_cus:
            dn_failed.append({"lama": h["name"], "alasan": "customer tidak ketemu"})
            continue
        p["customer"] = new_cus
        if p.get("selling_price_list") in PRICE_LIST_FALLBACK:
            p["selling_price_list"] = PRICE_LIST_FALLBACK[p["selling_price_list"]]
        if p.get("set_warehouse"):
            p["set_warehouse"] = wh_map(p["set_warehouse"])
        rows = []
        a = abbr.get(h.get("company"), "")
        for it in h.get("items", []):
            q = {k: v for k, v in it.items()
                 if k not in DROP_ROW and not k.startswith("_")}
            q["item_code"] = ITEM_MAP.get(it["item_code"], it["item_code"])
            if it.get("item_group") in ITEM_GROUP_MAP:
                q["item_group"] = ITEM_GROUP_MAP[it["item_group"]]
            if q.get("warehouse"):
                q["warehouse"] = wh_map(q["warehouse"])
            q["cost_center"] = suffix_map(it.get("cost_center"), a)
            q["expense_account"] = suffix_map(it.get("expense_account"), a)
            old_so = it.get("against_sales_order") or ""
            new_so = so_map.get(old_so)
            if old_so and new_so not in (None, "EXISTS", "DRY-RUN"):
                q["against_sales_order"] = new_so
            else:
                q["against_sales_order"] = None
                q["so_detail"] = None
                if old_so:
                    q["description"] = ((it.get("description") or "")
                                        + f" SO-lama:{old_so}").strip()
            rows.append(q)
        p["items"] = rows
        if args.dry_run:
            continue
        st, d = erp.post("Delivery Note", p)
        if st != 200:
            dn_failed.append({"lama": h["name"],
                              "alasan": f"POST {st}: {json.dumps(d)[:300]}"})
            continue
        name = d["data"]["name"]
        if h.get("docstatus") == 1:
            st2, d2 = erp.submit("Delivery Note", name)
            if st2 != 200:
                dn_failed.append({"lama": h["name"], "baru": name,
                                  "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:200]}"})
    print(f"  DN: gagal={len(dn_failed)}")
    for f in (failed + dn_failed)[:20]:
        print(f"    GAGAL {f}")
    if failed or dn_failed:
        sys.exit(1)
    print("MIGRATE-SO-DN OK")


if __name__ == "__main__":
    main()
