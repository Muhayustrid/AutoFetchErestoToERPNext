#!/usr/bin/env python3
"""pos_sync/rapikan_handover_krim_kopi.py — rapikan history serah terima Krim Kopi.

Konteks (2026-10-10): handover Krim Kopi (PJ260016, company PT. JUARA ROTI
INDONESIA) tanggal 1-8 Okt masih berbentuk SATU Stock Entry + SATU Material
Request borongan (871/872/869/870 Pcs) tanpa ikatan Work Order, sehingga 204 WO
tampil kosong di papan serah terima. Fitur baru (branch production_app
feat/bulk-handover-single-mr) membuat handover grup = SATU Material Request
berbaris-baris (satu baris per WO). Script ini mengganti dokumen lama dengan
bentuk itu: SE dan MR lama di-cancel, lalu per hari dibuat 1 MR bulk + 1 SE
bulk (posting date/time sama seperti SE lama, qty per baris = qty baris MR).

SCOPE KERAS: hanya company "PT. JUARA ROTI INDONESIA" (CS/GBJ/Gudang JURI).
RPMD dan RS PKU MUHAMMADIYAH DELANGGU tidak pernah disentuh — setiap WO/SE/MR
yang dibaca atau ditulis diverifikasi company-nya dulu.

Idempoten: MR bulk ditandai `title = "Serah Terima Bulk PJ260016 <tanggal>"`.
Hari yang MR bulk-nya sudah ada DAN sudah punya SE submitted = SKIP_EXISTS.

DEFAULT = DRY-RUN (cetak rencana per hari: n_wo, Σqty, SE/MR lama, aksi).
Jalankan: python pos_sync/rapikan_handover_krim_kopi.py [--execute] [--cleanup-9okt]

Setelah --execute, hapus dokumen cancelled dengan script yang sudah teruji:
  python pos_sync/bersih_dokumen_cancelled.py --execute
lalu jalankan ulang script ini untuk verifikasi SKIP_EXISTS.
"""
import argparse
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env, pick, pick_rows, fetch_meta

ITEM = "PJ260016"
CS = "Cold Storage Produksi - JURI"
GBJ = "Gudang Barang Jadi - JURI"
JURI = "PT. JUARA ROTI INDONESIA"
UOM = "Pcs"
# hari history (3 & 4 Okt tidak ada data produksi di site)
DAYS = ["2026-10-01", "2026-10-02", "2026-10-05", "2026-10-06", "2026-10-07", "2026-10-08"]
DAY_9OKT = "2026-10-09"
# MR uji 9 Okt (dibuat saat uji fitur, tanpa makna bisnis)
MR_9OKT = ["MREQ-MTR-26-0190"] + [f"MREQ-MTR-26-{n:04d}" for n in range(193, 227)]
AUDIT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "audit_logs")

TITLE = lambda day: f"Serah Terima Bulk {ITEM} {day}"  # noqa: E731


def bulk_title(day):
    return TITLE(day)


def q(value):
    return float(value or 0)


def guard_juri(name, doctype, doc):
    """Tolak dokumen di luar JURI — jangan pernah menyentuh company lain."""
    company = (doc or {}).get("company")
    if company != JURI:
        raise SystemExit(f"BATAL: {doctype} {name} company={company!r} di luar {JURI!r}")


def wo_by_day(c):
    """WO Krim Kopi company JURI -> {planned_start_date: [wo, ...]}."""
    wos = c.list_all(
        "Work Order",
        ["name", "planned_start_date", "produced_qty", "company"],
        filters=[
            ["production_item", "=", ITEM],
            ["fg_warehouse", "=", CS],
            ["company", "=", JURI],
        ],
    )
    for w in wos:
        if w["company"] != JURI:  # pertahanan ganda
            raise SystemExit(f"BATAL: WO {w['name']} bukan company {JURI}")
    out = {}
    for w in wos:
        out.setdefault(str(w["planned_start_date"])[:10], []).append(w)
    return {d: sorted(v, key=lambda x: x["name"]) for d, v in out.items()}


def old_se_for_day(c, day):
    """SE Material Transfer CS->GBJ (docstatus 1) untuk item ini pada hari itu."""
    ses = c.list_all(
        "Stock Entry",
        ["name", "posting_date", "docstatus", "company"],
        filters=[
            ["purpose", "=", "Material Transfer"],
            ["posting_date", "=", day],
            ["docstatus", "=", 1],
            ["company", "=", JURI],
        ],
    )
    found = []
    for s in ses:
        st, d = c.get(f"/api/resource/Stock Entry/{s['name']}", {"limit_page_length": 0})
        if st != 200:
            continue
        se = d["data"]
        guard_juri(se["name"], "Stock Entry", se)
        rows = [
            row
            for row in se.get("items", [])
            if row.get("item_code") == ITEM and row.get("s_warehouse") == CS and row.get("t_warehouse") == GBJ
        ]
        if not rows:
            continue
        if se.get("title", "").startswith("Serah Terima Bulk"):
            continue  # SE bulk buatan script ini, bukan target replace
        found.append(
            {
                "name": se["name"],
                "qty": sum(q(row.get("qty")) for row in rows),
                "posting_time": se.get("posting_time"),
                "posting_date": str(se.get("posting_date")),
            }
        )
    return found


def old_mr_for_day(c, day):
    """MR Material Transfer CS->GBJ (docstatus 1) untuk item ini pada hari itu."""
    mrs = c.list_all(
        "Material Request",
        ["name", "transaction_date", "docstatus", "status", "company", "title"],
        filters=[
            ["material_request_type", "=", "Material Transfer"],
            ["transaction_date", "=", day],
            ["docstatus", "=", 1],
            ["company", "=", JURI],
            ["set_from_warehouse", "=", CS],
            ["set_warehouse", "=", GBJ],
        ],
    )
    return [m for m in mrs if any(i.get("item_code") == ITEM for i in _mr_items(c, m["name"]))]


def _mr_items(c, name):
    st, d = c.get(f"/api/resource/Material Request/{name}", {"limit_page_length": 0})
    if st != 200:
        return []
    return d["data"].get("items", [])


def bulk_mr_for_day(c, day):
    """MR bulk milik script ini untuk hari itu (kalau sudah dibuat)."""
    st, d = c.get(
        "/api/resource/Material Request",
        {
            "filters": json.dumps([["title", "=", bulk_title(day)]]),
            "fields": json.dumps(["name", "docstatus", "status", "transaction_date", "company"]),
            "limit_page_length": 5,
        },
    )
    rows = d.get("data", []) if st == 200 else []
    rows = [r for r in rows if r.get("company") == JURI]
    return rows[0] if rows else None


def sent_se_for_mr(c, mr_name):
    """SE submitted yang merujuk MR ini (lewat Stock Entry Detail.material_request)."""
    st, d = c.get(
        "/api/resource/Stock Entry",
        {
            "filters": json.dumps([["Stock Entry Detail", "material_request", "=", mr_name], ["docstatus", "=", 1]]),
            "fields": json.dumps(["name", "posting_date"]),
            "limit_page_length": 5,
        },
    )
    return d.get("data", []) if st == 200 else []


def build_plan(c):
    """Rencana per hari: n_wo, Σqty, SE/MR lama, dan aksi yang akan dijalankan."""
    days = wo_by_day(c)
    plan = []
    for day in DAYS:
        wos = days.get(day, [])
        total = sum(q(w.get("produced_qty")) for w in wos)
        ses = old_se_for_day(c, day)
        mrs = old_mr_for_day(c, day)
        bulk = bulk_mr_for_day(c, day)
        se_matches = [s for s in ses if abs(s["qty"] - total) < 0.5]
        extra = [s for s in ses if abs(s["qty"] - total) >= 0.5]
        has_sent_se = bool(bulk and sent_se_for_mr(c, bulk["name"]))

        # urutan logika: hari yang MR bulk-nya sudah ada + sudah terkirim selalu
        # SKIP_EXISTS, walaupun SE/MR lamanya sudah cancelled (atau dihapus).
        if has_sent_se:
            action = "SKIP_EXISTS"
        elif not wos or not (ses or bulk):
            action = "ABORT_MISMATCH"
        elif bulk:
            action = "BUAT_SE_SAJA"
        elif se_matches:
            action = "ACTION"
        else:
            action = "ABORT_MISMATCH"

        plan.append(
            {
                "day": day,
                "n_wo": len(wos),
                "total": total,
                "old_se": ses,
                "se_matches": se_matches,
                "extra_se": extra,
                "old_mr": mrs,
                "bulk": bulk,
                "action": action,
                "wos": wos,
            }
        )
    return plan


def print_plan(plan):
    print(f"\n{'hari':11} {'n_wo':>4} {'Σqty':>7} {'SE_lama':>22} {'qty_SE':>7} {'MR_lama':20} aksi")
    for p in plan:
        se = p["se_matches"][0] if p["se_matches"] else None
        print(
            f"{p['day']} {p['n_wo']:>4} {p['total']:>7.0f} "
            f"{(se['name'] if se else '-'):>22} {(se['qty'] if se else 0):>7.0f} "
            f"{(p['old_mr'][0]['name'] if p['old_mr'] else '-'):20} {p['action']}"
        )
        for x in p["extra_se"]:
            print(f"{'':11} SE lain di hari itu (TIDAK disentuh): {x['name']} qty={x['qty']:.0f}")
        for m in p["old_mr"][1:]:
            print(f"{'':11} MR lain: {m['name']} status={m['status']}")
        for w in (p["bulk"],):
            if w:
                print(f"{'':11} MR bulk sudah ada: {w['name']} status={w['status']}")


def snapshot_bins(c):
    return {b["warehouse"]: q(b["actual_qty"]) for b in c.list_all("Bin", ["warehouse", "actual_qty"], filters=[["item_code", "=", ITEM]])}


def global_negative_bins(c):
    rows = c.list_all("Bin", ["warehouse", "actual_qty", "item_code"], filters=[["actual_qty", "<", 0]])
    return [(r["item_code"], r["warehouse"], r["actual_qty"]) for r in rows]


def set_allow_negative_stock(c, value):
    st, _ = c.put("Stock Settings", "Stock Settings", {"allow_negative_stock": 1 if value else 0})
    if st not in (200, 202):
        raise SystemExit(f"GAGAL set allow_negative_stock={value}: HTTP {st}")


def get_allow_negative_stock(c):
    st, d = c.get("/api/resource/Stock Settings/Stock Settings", {"limit_page_length": 0})
    return 1 if st == 200 and d["data"].get("allow_negative_stock") else 0


def cancel_doc(c, doctype, name, doc):
    guard_juri(name, doctype, doc)
    st, d = c.put(doctype, name, {"docstatus": 2})
    if st not in (200, 202):
        raise SystemExit(f"GAGAL cancel {doctype} {name}: HTTP {st} {str(d)[:200]}")
    return True


def create_bulk_mr(c, day, wos, meta):
    """Satu MR Material Transfer: satu baris per WO (qty = produced_qty WO)."""
    mr = {
        "doctype": "Material Request",
        "title": bulk_title(day),
        "material_request_type": "Material Transfer",
        "company": JURI,
        "transaction_date": day,
        "schedule_date": day,
        "set_from_warehouse": CS,
        "set_warehouse": GBJ,
        "items": [
            {
                "doctype": "Material Request Item",
                "item_code": ITEM,
                "qty": q(w.get("produced_qty")),
                "uom": UOM,
                "stock_uom": UOM,
                "conversion_factor": 1,
                "from_warehouse": CS,
                "warehouse": GBJ,
                "schedule_date": day,
                "custom_work_order": w["name"],
            }
            for w in wos
        ],
    }
    st, d = c.post("Material Request", mr)
    if st not in (200, 202):
        raise SystemExit(f"GAGAL buat MR {day}: HTTP {st} {str(d)[:300]}")
    name = d["data"]["name"]
    st, d = c.put("Material Request", name, {"docstatus": 1})
    if st not in (200, 202):
        raise SystemExit(f"GAGAL submit MR {name}: HTTP {st} {str(d)[:300]}")
    return name


def make_se_from_mr(c, mr_name, day, posting_time, meta):
    """make_stock_entry MR -> SE dengan posting tanggal/waktu SE lama, qty per baris MR."""
    st, d = c.req(
        "POST",
        "/api/method/erpnext.stock.doctype.material_request.material_request.make_stock_entry",
        {"source_name": mr_name},
    )
    se = (d or {}).get("message") if st == 200 else None
    if not se:
        raise SystemExit(f"GAGAL make_stock_entry {mr_name}: HTTP {st} {str(d)[:300]}")

    mr_items = {i["name"]: i for i in _mr_items(c, mr_name)}
    se["set_posting_time"] = 1
    se["posting_date"] = day
    if posting_time:
        se["posting_time"] = str(posting_time).split(".")[0]  # Time field: HH:MM:SS
    for row in se.get("items", []):
        mri = mr_items.get(row.get("material_request_item"))
        if mri:  # qty mengikuti baris MR (bukan stock_qty yg bisa dibulatkan erpnext)
            row["qty"] = q(mri.get("qty"))
            row["transfer_qty"] = q(mri.get("qty")) * q(row.get("conversion_factor") or 1)
    se["company"] = JURI
    payload = pick(se, meta["Stock Entry"])
    rows = pick_rows(se.get("items", []), meta["Stock Entry Detail"], drop=("name",))
    if not rows:
        raise SystemExit(f"make_stock_entry {mr_name} tanpa baris item")
    payload["items"] = rows
    st, d = c.post("Stock Entry", payload)
    if st not in (200, 202):
        raise SystemExit(f"GAGAL buat SE {day}: HTTP {st} {str(d)[:300]}")
    name = d["data"]["name"]
    st, d = c.put("Stock Entry", name, {"docstatus": 1})
    if st not in (200, 202):
        raise SystemExit(f"GAGAL submit SE {name}: HTTP {st} {str(d)[:300]}")
    return name


def execute_plan(c, plan, meta):
    """Cancel SE/MR lama (terbaru dulu), lalu per hari: MR bulk -> SE bulk."""
    neg_flag_before = get_allow_negative_stock(c)
    bins_before = snapshot_bins(c)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(AUDIT, exist_ok=True)

    todo = [p for p in plan if p["action"] in ("ACTION", "BUAT_SE_SAJA", "SKIP_EXISTS")]
    backup_name = os.path.join(AUDIT, f"backup_handover_krim_kopi_{stamp}.json")
    backup = {"bins_before": bins_before, "days": {}}
    for p in todo:
        dok = {}
        for se in p["se_matches"]:
            st, d = c.get(f"/api/resource/Stock Entry/{se['name']}", {"limit_page_length": 0})
            dok[se["name"]] = d["data"] if st == 200 else {"_gagal_baca": se}
        for m in p["old_mr"]:
            st, d = c.get(f"/api/resource/Material Request/{m['name']}", {"limit_page_length": 0})
            dok[m["name"]] = d["data"] if st == 200 else {"_gagal_baca": m}
        backup["days"][p["day"]] = {
            "old_se": p["se_matches"],
            "old_mr": [m["name"] for m in p["old_mr"]],
            "extra_se_tidak_disentuh": [x["name"] for x in p["extra_se"]],
            "dokumen": dok,
        }
    json.dump(backup, open(backup_name, "w"), indent=1, default=str)
    print(f"[backup] {backup_name}")

    # cancel dokumen lama: SE terbaru dulu, lalu MR-nya
    print(f"[flag] allow_negative_stock={neg_flag_before} -> 1 (restore di finally)")
    set_allow_negative_stock(c, 1)
    try:
        for p in sorted(todo, key=lambda x: x["day"], reverse=True):
            for se in p["se_matches"]:
                st, d = c.get(f"/api/resource/Stock Entry/{se['name']}", {"limit_page_length": 0})
                guard_juri(se["name"], "Stock Entry", d["data"])
                cancel_doc(c, "Stock Entry", se["name"], d["data"])
                print(f"  cancel SE {se['name']} (qty={se['qty']:.0f})")
        for p in sorted(todo, key=lambda x: x["day"], reverse=True):
            for m in p["old_mr"]:
                st, d = c.get(f"/api/resource/Material Request/{m['name']}", {"limit_page_length": 0})
                if st != 200:
                    continue
                guard_juri(m["name"], "Material Request", d["data"])
                cancel_doc(c, "Material Request", m["name"], d["data"])
                print(f"  cancel MR {m['name']} (qty={sum(q(i.get('qty')) for i in d['data'].get('items', [])):.0f})")

        for p in sorted(todo, key=lambda x: x["day"]):
            bulk = p["bulk"]
            if bulk:
                mr_name = bulk["name"]
                print(f"[{p['day']}] pakai MR bulk {mr_name}")
            else:
                mr_name = create_bulk_mr(c, p["day"], p["wos"], meta)
                print(f"[{p['day']}] MR bulk {mr_name} ({len(p['wos'])} baris, Σ{p['total']:.0f})")
            se_name = make_se_from_mr(c, mr_name, p["day"], p["se_matches"][0]["posting_time"], meta)
            print(f"[{p['day']}] SE {se_name} (posting {p['day']} {p['se_matches'][0]['posting_time']})")
    finally:
        set_allow_negative_stock(c, neg_flag_before)
        print(f"[flag] allow_negative_stock dipulihkan ke {neg_flag_before}")

    bins_after = snapshot_bins(c)
    bad = {w: (bins_before.get(w), bins_after.get(w)) for w in set(bins_before) | set(bins_after)
           if abs(q(bins_before.get(w)) - q(bins_after.get(w))) > 0.5}
    print("[bin] identik dengan snapshot:", "LOLOS" if not bad else f"GAGAL {bad}")
    return neg_flag_before


def verify(c):
    ok = True

    def check(label, good, detail=""):
        nonlocal ok
        ok = ok and bool(good)
        print(f"{'LOLOS' if good else 'GAGAL'}  {label}{(' — ' + detail) if detail else ''}")

    bins = snapshot_bins(c)
    neg_global = global_negative_bins(c)
    check("0 Bin negatif (global)", not neg_global, str(neg_global[:3]))
    sle_neg = c.list_all(
        "Stock Ledger Entry",
        ["name"],
        filters=[["item_code", "=", ITEM], ["warehouse", "in", [CS, GBJ]], ["qty_after_transaction", "<", 0]],
    )
    check("0 SLE PJ260016 negatif di CS/GBJ", not sle_neg, str(sle_neg[:3]))
    wos = wo_by_day(c)
    hist_days = [d for d in DAYS]
    status = {}
    for d in hist_days:
        for w in wos.get(d, []):
            st, dd = c.get(
                "/api/resource/Work Order/" + w["name"], {"limit_page_length": 0, "fields": json.dumps(["custom_handover_status", "custom_handover_material_request"])}
            )
            if st == 200:
                status[w["name"]] = (dd["data"].get("custom_handover_status"), dd["data"].get("custom_handover_material_request"))
    terkirim = [n for n, (s, _m) in status.items() if s == "Terkirim"]
    check(f"WO 1-8 Okt berstatus Terkirim = 204", len(terkirim) == 204, f"dapat {len(terkirim)}")
    # setiap baris SE baru merujuk MR bulk hari yang sama
    wrong_link = 0
    rows_wo = 0
    for d in hist_days:
        bulk = bulk_mr_for_day(c, d)
        if not bulk:
            continue
        want = bulk["name"]
        for se in sent_se_for_mr(c, want):
            st, dd = c.get(f"/api/resource/Stock Entry/{se['name']}", {"limit_page_length": 0})
            for row in dd["data"].get("items", []):
                rows_wo += 1
                if row.get("material_request") != want:
                    wrong_link += 1
    check("setiap baris SE baru merujuk MR bulk-nya", wrong_link == 0, f"{rows_wo} baris, {wrong_link} salah")
    check("allow_negative_stock == 0", get_allow_negative_stock(c) == 0)
    plan = build_plan(c)
    check("dry-run ulang: semua SKIP_EXISTS", all(p["action"] == "SKIP_EXISTS" for p in plan),
          ", ".join(f"{p['day']}={p['action']}" for p in plan))
    return ok


def cleanup_9okt(c, meta):
    """Cancel + hapus MR uji 9 Okt (MREQ-MTR-26-0190, 0193..0226)."""
    print("\n=== CLEANUP 9 OKT ===")
    for n in MR_9OKT:
        st, d = c.get(f"/api/resource/Material Request/{n}", {"limit_page_length": 0})
        if st != 200:
            print(f"  {n}: tidak ada (HTTP {st}) — dilewati")
            continue
        doc = d["data"]
        guard_juri(n, "Material Request", doc)
        if doc.get("docstatus") == 2:
            print(f"  {n}: sudah Cancelled")
        else:
            cancel_doc(c, "Material Request", n, doc)
            print(f"  cancel {n} (status={doc.get('status')})")
    print("hapus permanen dokumen cancelled:")
    print("  python pos_sync/bersih_dokumen_cancelled.py --execute")

    # satu MR bulk 34 baris pengganti 35 MR uji (idempoten lewat title)
    bulk = bulk_mr_for_day(c, DAY_9OKT)
    if bulk:
        print(f"MR bulk 9 Okt sudah ada: {bulk['name']} — dilewati")
        return
    wos = wo_by_day(c).get(DAY_9OKT, [])
    if len(wos) != 34:
        raise SystemExit(f"BATAL: WO 9 Okt = {len(wos)}, diharapkan 34")
    name = create_bulk_mr(c, DAY_9OKT, wos, meta)
    print(f"MR bulk 9 Okt {name} ({len(wos)} baris, Σ{sum(q(w.get('produced_qty')) for w in wos):.0f})")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--cleanup-9okt", action="store_true", help="cancel MR uji 9 Okt (perlu --execute)")
    args = ap.parse_args()

    env = load_env("/tmp/eresto_prod.env")
    c = Client(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], "BARU", pause=0.05)
    st, d = c.get("/api/method/frappe.ping")
    if st != 200:
        raise SystemExit(f"tidak bisa hubungi {env['ERPNEXT_URL']}: {st}")

    if args.cleanup_9okt:
        if not args.execute:
            print("DRY-RUN: --cleanup-9okt belum dijalankan (tambah --execute).")
        else:
            cleanup_9okt(c, None)
        return

    plan = build_plan(c)
    print("RENCANA SERAH TERIMA KRIM KOPI (company %s gudang %s -> %s)" % (JURI, CS, GBJ))
    print_plan(plan)
    bad = [p for p in plan if p["action"] == "ABORT_MISMATCH"]
    todo = [p for p in plan if p["action"] in ("ACTION", "BUAT_SE_SAJA")]
    print(f"\nhari ABORT_MISMATCH: {len(bad)} | hari akan dikerjakan: {len(todo)} | SKIP_EXISTS: {sum(1 for p in plan if p['action'] == 'SKIP_EXISTS')}")
    if not args.execute:
        print("DRY-RUN: tidak ada perubahan. Tambah --execute untuk menjalankan.")
        return
    if not todo:
        print("Tidak ada yang perlu dikerjakan.")
        return

    meta = fetch_meta(c, ["Stock Entry", "Stock Entry Detail"])
    execute_plan(c, plan, meta)
    print("\n=== VERIFIKASI ===")
    print("HASIL:", "LOLOS" if verify(c) else "GAGAL")
    print("\nLangkah berikutnya (hapus dokumen cancelled):")
    print("  python pos_sync/bersih_dokumen_cancelled.py --execute")


if __name__ == "__main__":
    main()
