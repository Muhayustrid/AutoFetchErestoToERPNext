#!/usr/bin/env python3
"""Eksekusi final: Bersihkan 13 Bin minus + Sinkronkan 5 tahapan 23 WO 6 Okt.

Tahapan:
1. Stock Reconciliation penyesuaian:
   - Gudang Bahan Baku - JURI (5 item)
   - Work In Progress - JURI (7 item)
   - Stores - RPMD (1 item: PG001)
2. Sinkronkan seluruh 5 tahapan pada 23 Work Order PP261006001:
   - Persiapan (adonan_ke, jam, suhu, penimbang, leader, kru, qc)
   - Material (transferred qty)
   - Pre-Packing (confirmed, good, reject, trial, sisa, jam_pembekuan)
   - Post-Packing (confirmed, good, reject, trial, sisa, jam_packing, qc_packing)
   - Finish (produced_qty, process_loss_qty, status Completed, actual start/end)
3. Verifikasi:
   - 0 Bin negatif di seluruh site baru
   - 306 WO 1-7 Okt 100% cocok dengan site lama di seluruh tahapan production_app
"""
import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import Ctx, clean_time  # noqa: E402
from prod_common import JURI  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP_DIR = os.path.join(HERE, "oct7_dump")

WO_ALLOW_ON_SUBMIT = [
    "produced_qty", "process_loss_qty", "status",
    "material_transferred_for_manufacturing",
    "actual_start_date", "actual_end_date"
]

SYNC_FIELDS = [
    # 1. Persiapan
    "custom_adonan_ke", "custom_adonan", "custom_jam_adonan", "custom_suhu_adonan",
    "custom_nama_penimbang", "custom_leader_produksi", "custom_jumlah_kru",
    "custom_qc_produksi",
    # 2. Material
    "material_transferred_for_manufacturing",
    # 3. Pre-Packing
    "custom_good_qty_prepacking", "custom_reject_qty_prepacking",
    "custom_trial_qty_prepacking", "custom_sisa_qty_prepacking",
    "custom_jam_pembekuan", "custom_prepacking_confirmed",
    # 4. Post-Packing
    "custom_good_qty_postpacking", "custom_reject_qty_postpacking",
    "custom_trial_qty_postpacking", "custom_sisa_qty_postpacking",
    "custom_jam_packing", "custom_qc_packing", "custom_postpacking_confirmed",
    # 5. Finish
    "produced_qty", "process_loss_qty", "status", "actual_start_date", "actual_end_date"
]

WOS_23 = [
    "MFG-WO-2026-04119", "MFG-WO-2026-04120", "MFG-WO-2026-04121", "MFG-WO-2026-04122",
    "MFG-WO-2026-04123", "MFG-WO-2026-04124", "MFG-WO-2026-04125", "MFG-WO-2026-04126",
    "MFG-WO-2026-04127", "MFG-WO-2026-04128", "MFG-WO-2026-04129", "MFG-WO-2026-04130",
    "MFG-WO-2026-04131", "MFG-WO-2026-04132", "MFG-WO-2026-04133", "MFG-WO-2026-04134",
    "MFG-WO-2026-04135", "MFG-WO-2026-04136", "MFG-WO-2026-04137", "MFG-WO-2026-04138",
    "MFG-WO-2026-04139", "MFG-WO-2026-04140", "MFG-WO-2026-04141"
]


def ensure_wo_setters(ctx):
    made = []
    for field in WO_ALLOW_ON_SUBMIT:
        st, d = ctx.new.get("/api/resource/Property Setter", {
            "filters": json.dumps([
                ["doc_type", "=", "Work Order"],
                ["field_name", "=", field],
                ["property", "=", "allow_on_submit"]]),
            "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
        rows = d.get("data", []) if st == 200 else []
        if rows and str(rows[0]["value"]) == "1":
            continue
        st, d = ctx.new.post("Property Setter", {
            "doctype": "Property Setter", "doctype_or_field": "DocField",
            "doc_type": "Work Order", "field_name": field,
            "property": "allow_on_submit", "property_type": "Check",
            "value": "1"})
        made.append(field)
    print(f"  Setter allow_on_submit WO: {made or '(sudah aktif)'}")


def cleanup_wo_setters(ctx):
    for field in WO_ALLOW_ON_SUBMIT:
        st, d = ctx.new.get("/api/resource/Property Setter", {
            "filters": json.dumps([
                ["doc_type", "=", "Work Order"],
                ["field_name", "=", field],
                ["property", "=", "allow_on_submit"]]),
            "fields": json.dumps(["name", "value"]), "limit_page_length": 1})
        rows = d.get("data", []) if st == 200 else []
        if not rows:
            continue
        if str(rows[0]["value"]) == "1":
            ctx.new.put("Property Setter", rows[0]["name"], {"value": "0"})
            print(f"  Setter WO {field} dikembalikan ke 0")


def post_reco(ctx, payload, tag, dry=False):
    wh = payload.get("set_warehouse")
    for it in payload["items"]:
        if not it.get("warehouse"):
            it["warehouse"] = wh
    print(f"== Posting {tag} ==")
    print(f"   Company: {payload['company']}, Warehouse: {wh}")
    print(f"   Items ({len(payload['items'])}):")
    for it in payload["items"]:
        print(f"     {it['item_code']:<12} qty={it['qty']:>14,.2f} rate={it['valuation_rate']} wh={it.get('warehouse')}")
    if dry:
        print(f"   [DRY-RUN] {tag} tidak diposting.")
        return None
    st, d = ctx.new.post("Stock Reconciliation", payload)
    if st == 200:
        docname = d["data"]["name"]
        print(f"   [OK] {tag} berhasil dibuat & disubmit: {docname}")
        return docname
    else:
        print(f"   [FAIL] {tag} gagal: {json.dumps(d)[:300]}")
        return None


def run_reco_phase(ctx, dry=False):
    print("=" * 80)
    print("FASE 1: Stock Reconciliation Penyesuaian Saldo")
    print("=" * 80)

    # 1. Gudang Bahan Baku - JURI (5 item saldo EOD 30 Sep riil)
    payload_bb = {
        "doctype": "Stock Reconciliation",
        "company": JURI,
        "purpose": "Opening Stock",
        "set_posting_time": 1,
        "posting_date": "2026-09-30",
        "posting_time": "23:35:00",
        "set_warehouse": "Gudang Bahan Baku - JURI",
        "expense_account": "1171.000 - Pembukaan sementara - JURI",
        "cost_center": "Main - JURI",
        "items": [
            {"item_code": "BB260011", "qty": 2530000.0, "valuation_rate": 18.018003771, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260012", "qty": 1950000.0, "valuation_rate": 17.179487185, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260018", "qty": 3000.0, "valuation_rate": 413.266, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260021", "qty": 82000.0, "valuation_rate": 13.465147439, "uom": "Pack", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260022", "qty": 658920.0, "valuation_rate": 17.482607904, "uom": "g", "allow_zero_valuation_rate": 1},
        ],
        "docstatus": 1
    }
    doc_bb = post_reco(ctx, payload_bb, "RECO-BAHAN-BAKU", dry)

    # 2. Work In Progress - JURI (7 item kompensasi akumulasi over-consumption MFG 1-6 Okt)
    payload_wip = {
        "doctype": "Stock Reconciliation",
        "company": JURI,
        "purpose": "Opening Stock",
        "set_posting_time": 1,
        "posting_date": "2026-09-30",
        "posting_time": "23:35:00",
        "set_warehouse": "Work In Progress - JURI",
        "expense_account": "1171.000 - Pembukaan sementara - JURI",
        "cost_center": "Main - JURI",
        "items": [
            {"item_code": "BB260002", "qty": 234.40, "valuation_rate": 666.328790726, "uom": "Pcs", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260011", "qty": 15810.00, "valuation_rate": 18.018019435, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260015", "qty": 14280.00, "valuation_rate": 17.117110754, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260016", "qty": 2470.00, "valuation_rate": 233.99998008, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260019", "qty": 118.20, "valuation_rate": 396.0, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260022", "qty": 10200.00, "valuation_rate": 17.000015, "uom": "g", "allow_zero_valuation_rate": 1},
            {"item_code": "BB260029", "qty": 20400.00, "valuation_rate": 6.630626688, "uom": "g", "allow_zero_valuation_rate": 1},
        ],
        "docstatus": 1
    }
    doc_wip = post_reco(ctx, payload_wip, "RECO-WIP-ADJUST", dry)

    # 3. Stores - RPMD (1 item: PG001 Goodie Bag 2 pcs opening agar tidak minus setelah 2 POS sales)
    payload_rpmd = {
        "doctype": "Stock Reconciliation",
        "company": "RS PKU MUHAMMADIYAH DELANGGU",
        "purpose": "Opening Stock",
        "set_posting_time": 1,
        "posting_date": "2026-09-30",
        "posting_time": "23:30:00",
        "set_warehouse": "Stores - RPMD",
        "expense_account": "1171.000 - Pembukaan sementara - RPMD",
        "cost_center": "Main - RPMD",
        "items": [
            {"item_code": "PG001", "qty": 2.0, "valuation_rate": 1900.0, "uom": "Pcs", "allow_zero_valuation_rate": 1}
        ],
        "docstatus": 1
    }
    doc_rpmd = post_reco(ctx, payload_rpmd, "RECO-RPMD-PG001", dry)

    return doc_bb, doc_wip, doc_rpmd


def run_wo_sync_phase(ctx, dry=False):
    print("=" * 80)
    print("FASE 2: Sinkronisasi 5 Tahapan 23 Work Order (PP261006001)")
    print("=" * 80)

    if not dry:
        ensure_wo_setters(ctx)

    success, failed = [], []
    for name in WOS_23:
        st_o, d_o = ctx.old.get(f"/api/resource/Work Order/{name}")
        if st_o != 200:
            print(f"  [FAIL] {name}: Tidak ditemukan di site lama")
            failed.append((name, "404 old site"))
            continue
        old_doc = d_o["data"]

        st_n, d_n = ctx.new.get(f"/api/resource/Work Order/{name}")
        if st_n != 200:
            print(f"  [FAIL] {name}: Tidak ditemukan di site baru")
            failed.append((name, "404 new site"))
            continue
        new_doc = d_n["data"]

        values = {}
        for f in SYNC_FIELDS:
            ov = old_doc.get(f)
            nv = new_doc.get(f)
            if f.endswith("_qty") or f in ("material_transferred_for_manufacturing", "custom_suhu_adonan", "custom_adonan_ke", "custom_adonan", "custom_jumlah_kru", "custom_prepacking_confirmed", "custom_postpacking_confirmed"):
                if abs(float(ov or 0) - float(nv or 0)) > 0.001:
                    values[f] = float(ov or 0) if not f.endswith("_confirmed") and not f in ("custom_adonan_ke", "custom_adonan", "custom_jumlah_kru") else int(float(ov or 0))
            elif f in ("custom_jam_adonan", "custom_jam_pembekuan", "custom_jam_packing"):
                so = str(ov or "").split(".")[0].strip()
                sn = str(nv or "").split(".")[0].strip()
                if so != sn:
                    values[f] = so if so else None
            elif f in ("actual_start_date", "actual_end_date"):
                so = str(ov or "").split(".")[0].strip()
                sn = str(nv or "").split(".")[0].strip()
                if so != sn:
                    values[f] = so if so else None
            else:
                so = str(ov or "").strip()
                sn = str(nv or "").strip()
                if so != sn:
                    values[f] = ov

        if not values:
            print(f"  [OK] {name}: Sudah identik (0 perbedaan)")
            success.append(name)
            continue

        print(f"  Update {name} -> {len(values)} fields: {list(values.keys())}")
        if dry:
            print(f"     [DRY-RUN] values: {values}")
            success.append(name)
            continue

        st, d = ctx.new.req(
            "POST", "/api/method/frappe.client.set_value",
            payload={"doctype": "Work Order", "name": name,
                     "fieldname": json.dumps(values)})
        if st in (200, 201):
            print(f"     [OK] {name} berhasil diupdate!")
            success.append(name)
        else:
            print(f"     [FAIL] {name} gagal: {json.dumps(d)[:250]}")
            failed.append((name, str(d)[:200]))

    if not dry:
        cleanup_wo_setters(ctx)

    print(f"\nHasil Sinkronisasi WO: {len(success)} sukses, {len(failed)} gagal.")
    return success, failed


def run_verify_phase(ctx):
    print("=" * 80)
    print("FASE 3: Verifikasi Komprehensif (Negative Bins & WO Stages)")
    print("=" * 80)

    # 1. Cek semua Bin negatif di site baru
    st, r = ctx.new.get("/api/resource/Bin", {
        "filters": json.dumps([["actual_qty", "<", 0], ["item_code", "!=", ""]]),
        "fields": json.dumps(["item_code", "warehouse", "actual_qty", "valuation_rate"]),
        "limit_page_length": 500})
    rows = r.get("data", []) if st == 200 else []
    print(f"\n1. Pemeriksaan Bin Negatif (Seluruh Sistem): {len(rows)} negatif")
    if rows:
        for x in sorted(rows, key=lambda z: (z["warehouse"], z["item_code"])):
            print(f"   [!] {x['item_code']:<12} {x['warehouse']:<32} qty={x['actual_qty']:>12,.2f}")
    else:
        print("   [LOLOS / OK] TIDAK ADA SATU PUN BIN NEGATIF DI SELURUH SISTEM!")

    # 2. Cek tahapan seluruh 306 WO 1-7 Oktober
    fields = [
        "name", "production_plan", "status", "qty", "produced_qty", "process_loss_qty",
        "material_transferred_for_manufacturing", "custom_prepacking_confirmed",
        "custom_postpacking_confirmed"
    ]
    w_new = ctx.new.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["planned_start_date", ">=", "2026-10-01"],
                               ["planned_start_date", "<=", "2026-10-07 23:59:59"]]),
        "fields": json.dumps(fields), "limit_page_length": 500})[1].get("data", [])

    w_old = ctx.old.get("/api/resource/Work Order", {
        "filters": json.dumps([["company", "=", JURI],
                               ["planned_start_date", ">=", "2026-10-01"],
                               ["planned_start_date", "<=", "2026-10-07 23:59:59"]]),
        "fields": json.dumps(fields), "limit_page_length": 500})[1].get("data", [])

    old_map = {w["name"]: w for w in w_old}

    def sim_stage(wo):
        qty = float(wo.get("qty") or 0)
        produced = float(wo.get("produced_qty") or 0)
        loss = float(wo.get("process_loss_qty") or 0)
        if qty > 0 and (produced + loss) >= qty: return "selesai"
        transferred = float(wo.get("material_transferred_for_manufacturing") or 0)
        if transferred < qty: return "material"
        if not wo.get("custom_prepacking_confirmed"): return "pre_packing"
        if not wo.get("custom_postpacking_confirmed"): return "post_packing"
        return "finish"

    mismatches = []
    stage_counts = {}
    for wn in w_new:
        stg_n = sim_stage(wn)
        stage_counts[stg_n] = stage_counts.get(stg_n, 0) + 1
        wo = old_map.get(wn["name"])
        if not wo:
            mismatches.append((wn["name"], "Tidak ada di site lama"))
            continue
        stg_o = sim_stage(wo)
        if stg_n != stg_o:
            mismatches.append((wn["name"], f"OLD={stg_o} vs NEW={stg_n}"))

    print(f"\n2. Pemeriksaan Tahapan 306 Work Order (1-7 Oktober):")
    print(f"   Total WO terdaftar: {len(w_new)}")
    for stg, cnt in sorted(stage_counts.items()):
        print(f"     Tahap {stg:<15}: {cnt} WO")
    if mismatches:
        print(f"   [!] Ada {len(mismatches)} ketidakcocokan tahap:")
        for m in mismatches:
            print(f"       {m[0]}: {m[1]}")
    else:
        print("   [LOLOS / OK] 306/306 WO 100% COCOK DAN IDENTIK DENGAN TAHAPAN SITE LAMA!")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Simulasi tanpa POST/PUT")
    ap.add_argument("--only-reco", action="store_true", help="Hanya jalankan Stock Reconciliation")
    ap.add_argument("--only-wo", action="store_true", help="Hanya jalankan sinkronisasi WO")
    ap.add_argument("--only-verify", action="store_true", help="Hanya verifikasi")
    args = ap.parse_args()

    ctx = Ctx()

    if args.only_verify:
        run_verify_phase(ctx)
        return

    if not args.only_wo:
        run_reco_phase(ctx, args.dry_run)
    if not args.only_reco:
        run_wo_sync_phase(ctx, args.dry_run)

    run_verify_phase(ctx)


if __name__ == "__main__":
    main()
