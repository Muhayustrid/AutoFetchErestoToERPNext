"""Tahap beli: Purchase Order -> Purchase Receipt ke site BARU.

Sumber: pos_sync/window/Purchase_Order.json + Purchase_Receipt.json.
Aturan (docs/06): supplier kode->nama (cache), gudang ROPI->JURI,
pajak pola per abbr company, baris PR yg merujuk PO September jadi mandiri
(purchase_order dikosongkan, nomor lama di remarks item).

Usage: python3 migrate_po_pr.py [--dry-run]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import ERP, ITEM_MAP, eresto_key, tax_map, wh_map  # noqa: E402


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
    "letter_head", "workflow_state",
    "shipping_address", "shipping_address_display",
    "billing_address", "billing_address_display",
    "dispatch_address", "dispatch_address_display",
    "contact_person", "contact_display", "contact_email", "contact_mobile",
    "custom_note", "custom_section_break_tjtb0",
    "_user_tags", "_comments", "_assign", "_liked_by",
}
DROP_ROW = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "parent", "parentfield", "parenttype", "docstatus",
    "purchase_order", "purchase_order_item", "sales_order", "sales_order_item",
    "material_request", "material_request_item",
    "amended_from",
}


ITEM_GROUP_MAP = {
    "Produk Jadi": "Produk Jadi Pabrik",
}


def expense_map(old, abbr):
    """Akun lama -> baru: ganti akhiran '- <abbr-lama>' jadi '- <abbr>'."""
    if not old or not abbr:
        return old
    if " - " in old:
        return old.rsplit(" - ", 1)[0] + " - " + abbr
    return old


def cc_map(old, abbr):
    if not old or not abbr:
        return old
    if " - " in old:
        return old.rsplit(" - ", 1)[0] + " - " + abbr
    return old


class Mapper:
    def __init__(self, erp):
        self.erp = erp
        self.sup = {}
        self.abbr = {}
        st, d = erp.get("/api/resource/Supplier",
                        {"fields": '["name","supplier_name"]',
                         "limit_page_length": 1000})
        for s in d.get("data", []):
            self.sup[s["supplier_name"]] = s["name"]
            self.sup[s["supplier_name"].lower()] = s["name"]
        st, d = erp.get("/api/resource/Company",
                        {"fields": '["name","abbr"]', "limit_page_length": 500})
        for c in d.get("data", []):
            self.abbr[c["name"]] = c.get("abbr", "")

    def hdr(self, doctype, h, old_items_key="items"):
        p = {"doctype": doctype}
        for k, v in h.items():
            if k in DROP_HDR or k == old_items_key or k.startswith("_"):
                continue
            p[k] = v
        if h.get("supplier"):
            code = h["supplier"]
            st, d = self.erp.get("/api/resource/Supplier/" + code)
            sname = (d.get("data") or {}).get("supplier_name", "") if st == 200 else ""
            # cari via API lama tidak mungkin; pakai cache nama->nama:
            # (dump lama tidak bawa supplier_name; di-resolve di bawah)
            p["_old_supplier"] = code
            p["supplier"] = None
        if p.get("set_warehouse"):
            p["set_warehouse"] = wh_map(p["set_warehouse"])
        abbr = self.abbr.get(h.get("company"), "")
        p["taxes_and_charges"] = tax_map(h.get("taxes_and_charges"), abbr)
        p["taxes"] = []  # dihitung ulang dari template
        # PO tak punya remarks -> kunci idempotency di title (kosong di site lama)
        p["title"] = eresto_key(h["name"])
        return p

    def row(self, it, warehouse_field="warehouse", abbr=""):
        q = {k: v for k, v in it.items()
             if k not in DROP_ROW and not k.startswith("_")}
        q["item_code"] = ITEM_MAP.get(it["item_code"], it["item_code"])
        if it.get("item_group") in ITEM_GROUP_MAP:
            q["item_group"] = ITEM_GROUP_MAP[it["item_group"]]
        if q.get(warehouse_field):
            q[warehouse_field] = wh_map(q[warehouse_field])
        old_mr = it.get("material_request") or ""
        if old_mr:
            q["description"] = ((it.get("description") or "")
                                + f" MR-lama:{old_mr}").strip()
        q["expense_account"] = expense_map(it.get("expense_account"), abbr)
        q["cost_center"] = cc_map(it.get("cost_center"), abbr)
        q.pop("purchase_order", None)
        q.pop("purchase_order_item", None)
        return q


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])
    mp = Mapper(erp)
    wdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window")
    pos = json.load(open(os.path.join(wdir, "Purchase_Order.json")))
    prs = json.load(open(os.path.join(wdir, "Purchase_Receipt.json")))

    # supplier lama kode->nama: butuh dari site lama; diminta via arg? pakai REST lama bila ada key.
    old_key = os.environ.get("ERPNEXT_OLD_API_KEY", "")
    old_sup = {}
    if old_key:
        from common import OLD_BASE
        old = ERP(OLD_BASE, old_key)
        st, d = old.get("/api/resource/Supplier",
                        {"fields": '["name","supplier_name"]',
                         "limit_page_length": 1000})
        if st == 200:
            for s in d.get("data", []):
                old_sup[s["name"]] = s["supplier_name"]
    print(f"  supplier lama terpetakan: {len(old_sup)}")

    po_map, failed = {}, []
    for h in sorted(pos, key=lambda x: x["name"]):
        key = eresto_key(h["name"])
        if erp.find_by_remark("Purchase Order", "title", key):
            po_map[h["name"]] = "EXISTS"
            continue
        p = mp.hdr("Purchase Order", h)
        _sn = old_sup.get(p.pop("_old_supplier"), "")
        new_sup = mp.sup.get(_sn) or mp.sup.get(_sn.lower(), "")
        if not new_sup:
            failed.append({"lama": h["name"], "alasan": "supplier tidak ketemu"})
            continue
        p["supplier"] = new_sup
        abbr = mp.abbr.get(h.get("company"), "")
        p["items"] = [mp.row(it, abbr=abbr) for it in h.get("items", [])]
        if args.dry_run:
            po_map[h["name"]] = "DRY-RUN"
            continue
        st, d = erp.post("Purchase Order", p)
        if st != 200:
            failed.append({"lama": h["name"],
                           "alasan": f"POST {st}: {json.dumps(d)[:300]}"})
            continue
        name = d["data"]["name"]
        po_map[h["name"]] = name
        if h.get("docstatus") == 1:
            st2, d2 = erp.submit("Purchase Order", name)
            if st2 != 200:
                failed.append({"lama": h["name"], "baru": name,
                               "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:200]}"})
                continue
        if h.get("docstatus") == 2:
            st2, d2 = erp.submit("Purchase Order", name)
            if st2 == 200:
                erp.cancel("Purchase Order", name)
    print(f"  PO: {len([v for v in po_map.values() if v not in ('EXISTS',)])} "
          f"baru, gagal={len(failed)}")

    pr_failed = []
    for h in sorted(prs, key=lambda x: x["name"]):
        key = eresto_key(h["name"])
        if erp.find_by_remark("Purchase Receipt", "title", key):
            continue
        p = mp.hdr("Purchase Receipt", h)
        _sn = old_sup.get(p.pop("_old_supplier"), "")
        new_sup = mp.sup.get(_sn) or mp.sup.get(_sn.lower(), "")
        if not new_sup:
            pr_failed.append({"lama": h["name"], "alasan": "supplier tidak ketemu"})
            continue
        p["supplier"] = new_sup
        abbr = mp.abbr.get(h.get("company"), "")
        rows = []
        for it in h.get("items", []):
            q = mp.row(it, abbr=abbr)
            old_po = (it.get("purchase_order") or "")
            if old_po and po_map.get(old_po) not in (None, "EXISTS", "DRY-RUN"):
                q["purchase_order"] = po_map[old_po]
            else:
                q["purchase_order"] = None
                if old_po:
                    q["description"] = ((it.get("description") or "")
                                        + f" PO-lama:{old_po} "
                                          f"{it.get('purchase_order_item') or ''}").strip()
            rows.append(q)
        p["items"] = rows
        if args.dry_run:
            continue
        st, d = erp.post("Purchase Receipt", p)
        if st != 200:
            pr_failed.append({"lama": h["name"],
                              "alasan": f"POST {st}: {json.dumps(d)[:300]}"})
            continue
        name = d["data"]["name"]
        if h.get("docstatus") == 1:
            st2, d2 = erp.submit("Purchase Receipt", name)
            if st2 != 200:
                pr_failed.append({"lama": h["name"], "baru": name,
                                  "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:200]}"})
    print(f"  PR: gagal={len(pr_failed)}")
    for f in (failed + pr_failed)[:20]:
        print(f"    GAGAL {f}")
    if failed or pr_failed:
        sys.exit(1)
    print("MIGRATE-PO-PR OK")


if __name__ == "__main__":
    main()
