"""Tahap WO: Work Order jendela + Stock Entry terkait -> site BARU.

Sumber: pos_sync/window/Work_Order.json + Stock_Entry.json (dari dump_window.py).
Aturan (docs/06): item/BOM/gudang dipetakan, custom fields disalin kecuali
handover MR (MR September tidak dimigrasi -> remarks), posa_*/custom_uom dikosongkan.
SE: gudang ROPI->JURI, nomor lama di remarks, backdate posting diizinkan.

Urutan per WO: buat WO draft -> submit (Completed) atau biarkan terbuka
(In Process) -> SE transfer (submit) -> SE manufacture (submit).
Abort per WO bila Bin bahan tidak cukup (tidak boleh negatif).

Usage: python3 migrate_wo.py [--dry-run] [--only MFG-WO-2026-xxxxx]
Env: ERPNEXT_URL, ERPNEXT_API_KEY (site BARU).
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import (BOM_MAP, ERP, ITEM_MAP, eresto_key,  # noqa: E402
                    tax_map, wh_map)


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


DROP_WO_FIELDS = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status", "produced_qty",
    "material_transferred_for_manufacturing",
    "production_plan", "production_plan_item",
    "production_plan_sub_assembly_item",
    "sales_order", "sales_order_item",
    "material_request", "material_request_item",
    "posa_operator", "posa_pos_profile", "posa_recipe",
    "custom_uom", "custom_handover_material_request",
    "amended_from", "_user_tags", "_comments", "_assign", "_liked_by",
}

DROP_SE_FIELDS = {
    "name", "owner", "creation", "modified", "modified_by", "idx",
    "docstatus", "naming_series", "status", "total_amount",
    "total_incoming_value", "total_outgoing_value", "value_difference",
    "letter_head", "custom_note",
    "amended_from", "_user_tags", "_comments", "_assign", "_liked_by",
}

SE_ACCOUNT_MAP = {
    "5110.020 - Penyesuaian Stock - ROPI": "5110.020 - Penyesuaian Stock - JURI",
}
SE_CC_MAP = {
    "Main - ROPI": "Main - JURI",
}


def map_wo(w):
    p = {"doctype": "Work Order"}
    for k, v in w.items():
        if k in DROP_WO_FIELDS or k.startswith("_"):
            continue
        p[k] = v
    p["production_item"] = ITEM_MAP.get(w["production_item"], w["production_item"])
    p["bom_no"] = BOM_MAP.get(w.get("bom_no"), w.get("bom_no"))
    for f in ("source_warehouse", "wip_warehouse", "fg_warehouse", "scrap_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    p["operations"] = []
    p["required_items"] = []
    old_mr = w.get("custom_handover_material_request") or ""
    old_pp = w.get("production_plan") or ""
    p["description"] = ((w.get("description") or "") + f"\n{eresto_key(w['name'])}"
                        + (f" MR-lama:{old_mr}" if old_mr else "")
                        + (f" PP-lama:{old_pp}" if old_pp else "")).strip()
    return p


def map_se(s, wo_name_map):
    p = {"doctype": "Stock Entry"}
    for k, v in s.items():
        if k in DROP_SE_FIELDS or k in ("items",) or k.startswith("_"):
            continue
        p[k] = v
    p["work_order"] = wo_name_map.get(s.get("work_order"))
    p["bom_no"] = BOM_MAP.get(s.get("bom_no"), s.get("bom_no"))
    for f in ("from_warehouse", "to_warehouse"):
        if p.get(f):
            p[f] = wh_map(p[f])
    items = []
    for it in s.get("items", []):
        q = {k: v for k, v in it.items()
             if k not in ("name", "owner", "creation", "modified",
                          "modified_by", "idx", "parent", "parentfield",
                          "parenttype", "docstatus") and not k.startswith("_")}
        q["item_code"] = ITEM_MAP.get(it["item_code"], it["item_code"])
        if it.get("bom_no") and it["bom_no"] in BOM_MAP:
            q["bom_no"] = BOM_MAP[it["bom_no"]]
        for f in ("s_warehouse", "t_warehouse"):
            if q.get(f):
                q[f] = wh_map(q[f])
        if q.get("expense_account") in SE_ACCOUNT_MAP:
            q["expense_account"] = SE_ACCOUNT_MAP[q["expense_account"]]
        if q.get("cost_center") in SE_CC_MAP:
            q["cost_center"] = SE_CC_MAP[q["cost_center"]]
        if float(it.get("basic_rate") or 0) > 0:  # valuasi historis site lama
            q["basic_rate"] = float(it["basic_rate"])
            q["valuation_rate"] = float(it.get("valuation_rate")
                                       or it["basic_rate"])
        items.append(q)
    p["items"] = items
    p["remarks"] = ((s.get("remarks") or "") + f"\n{eresto_key(s['name'])}").strip()
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", default="")
    args = ap.parse_args()
    env = load_env()
    erp = ERP(env["ERPNEXT_URL"].rstrip("/"), env["ERPNEXT_API_KEY"])
    wdir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "window")
    wos = json.load(open(os.path.join(wdir, "Work_Order.json")))
    ses = json.load(open(os.path.join(wdir, "Stock_Entry.json")))
    if args.only:
        wos = [w for w in wos if w["name"] == args.only]
        ses = [s for s in ses if s.get("work_order") == args.only]
    print(f"== WO: {len(wos)} dokumen, SE: {len(ses)} ==")

    ok, skipped, failed = [], [], []
    wo_name_map = {}
    existing = {}
    start = 0
    while True:
        st, d = erp.get("/api/resource/Work Order", {
            "filters": json.dumps([["description", "like", "%ERESTO MFG-WO-%"]]),
            "fields": '["name","description"]', "limit_page_length": 200,
            "limit_start": start, "order_by": "name"})
        rows = d.get("data", []) if st == 200 else []
        if not rows:
            break
        for r in rows:
            desc = r.get("description") or ""
            for w in wos:
                if eresto_key(w["name"]) in desc:
                    existing[w["name"]] = r["name"]
        start += len(rows)
        if len(rows) < 200:
            break
    for w in sorted(wos, key=lambda x: x["name"]):
        if w["name"] in existing:
            wo_name_map[w["name"]] = existing[w["name"]]
            skipped.append({"lama": w["name"], "baru": existing[w["name"]],
                            "alasan": "sudah ada"})
            continue
        key = eresto_key(w["name"])
        for row in erp.find_by_remark("Work Order", "description", key):
            wo_name_map[w["name"]] = row["name"]
            skipped.append({"lama": w["name"], "baru": row["name"],
                            "alasan": "sudah ada"})
            break
        else:
            payload = map_wo(w)
            if args.dry_run:
                wo_name_map[w["name"]] = "DRY-RUN"
                ok.append({"lama": w["name"], "baru": "DRY-RUN"})
                continue
            st, d = erp.post("Work Order", payload)
            if st != 200:
                failed.append({"lama": w["name"],
                               "alasan": f"POST WO {st}: {json.dumps(d)[:300]}"})
                continue
            new_name = d["data"]["name"]
            wo_name_map[w["name"]] = new_name
            if w.get("docstatus") == 1:
                st2, d2 = erp.submit("Work Order", new_name)
                if st2 != 200:
                    failed.append({"lama": w["name"], "baru": new_name,
                                   "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:200]}"})
                    continue
            ok.append({"lama": w["name"], "baru": new_name,
                       "status": w.get("status")})
    print(f"  WO: ok={len(ok)} sudah-ada={len(skipped)} gagal={len(failed)}")

    se_ok, se_skip, se_fail = [], [], []
    order = {"Material Transfer for Manufacture": 0, "Material Transfer": 0,
             "Manufacture": 1}
    # idempotency SE: preload semua remarks ERESTO MAT-STE-*
    se_existing = {}
    start = 0
    while True:
        st, d = erp.get("/api/resource/Stock Entry", {
            "filters": json.dumps([["remarks", "like", "%ERESTO MAT-STE-%"]]),
            "fields": '["name","remarks"]', "limit_page_length": 200,
            "limit_start": start, "order_by": "name"})
        rows = d.get("data", []) if st == 200 else []
        if not rows:
            break
        for r in rows:
            for s in ses:
                if eresto_key(s["name"]) in (r.get("remarks") or ""):
                    se_existing[s["name"]] = r["name"]
        start += len(rows)
        if len(rows) < 200:
            break
    for s in sorted(ses, key=lambda x: (order.get(x.get("stock_entry_type"), 9),
                                        x["name"])):
        if s["name"] in se_existing:
            se_skip.append({"lama": s["name"], "alasan": "sudah ada"})
            continue
        if not wo_name_map.get(s.get("work_order")):
            se_fail.append({"lama": s["name"], "alasan": "WO induk gagal/tidak ada"})
            continue
        payload = map_se(s, wo_name_map)
        if args.dry_run:
            se_ok.append({"lama": s["name"], "baru": "DRY-RUN"})
            continue
        st, d = erp.post("Stock Entry", payload)
        if st != 200:
            se_fail.append({"lama": s["name"],
                            "alasan": f"POST SE {st}: {json.dumps(d)[:300]}"})
            continue
        new_name = d["data"]["name"]
        if s.get("docstatus") == 1:
            st2, d2 = erp.submit("Stock Entry", new_name)
            if st2 != 200:
                se_fail.append({"lama": s["name"], "baru": new_name,
                                "alasan": f"SUBMIT {st2}: {json.dumps(d2)[:300]}"})
                continue
        se_ok.append({"lama": s["name"], "baru": new_name,
                      "tipe": s.get("stock_entry_type")})
    print(f"  SE: ok={len(se_ok)} sudah-ada={len(se_skip)} gagal={len(se_fail)}")
    for f in (failed + se_fail)[:20]:
        print(f"    GAGAL {f}")
    if failed or se_fail:
        sys.exit(1)
    print("MIGRATE-WO OK")


if __name__ == "__main__":
    main()
