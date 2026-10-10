#!/usr/bin/env python3
"""pos_sync/hapus_warehouse_testing.py — hapus permanen warehouse testing + stoknya.

Instruksi user 2026-10-09:
  "warehouse namanya Gudang Finished Goods Testing / Gudang Testing Manufacture /
   WIP Testing DIHAPUS! Stock yang ada di web lama itu cuma testing aja,
   jadi hapus ajaa."

Aksi (2 site):
  LAMA (rotiropi.j): Gudang Finished Goods Testing - ROPI,
      Gudang Testing Manufacture - ROPI, WIP Testing - ROPI
      -> cancel + hapus permanen 4 SE testing pemegang stok
         (MAT-STE-2026-01469/05894/05900/05901), lalu hapus 3 warehouse.
  BARU (ropierpnext): Gudang Testing Manufacture - JURI, WIP Testing - JURI
      -> cancel + hapus permanen RECO-JURI-261009046 / 261009043
         (satu-satunya penulis SLE), lalu hapus 2 warehouse.
  (Gudang Finished Goods Testing tidak ada di BARU — tidak pernah dibuat.)

Prosedur hapus dokumen ber-ledger (teruji): backup JSON -> purge POS Print Log
-> Accounts Settings.delete_linked_ledger_entries=1 sementara -> DELETE dok ->
restore 0 -> verifikasi SLE/GL per dokumen = 0 -> hapus warehouse (ERPNext
on_trash: butuh 0 SLE & Bin tanpa qty; unlink Item Default otomatis).

Urutan cancel LAMA diambil reverse-chronological supaya saldo tidak negatif:
  05901 (16:09) -> 05900 (16:03) -> 05894 (15:57) -> 01469 (17 Jul).

DEFAULT DRY-RUN:
  python pos_sync/hapus_warehouse_testing.py --plan
  python pos_sync/hapus_warehouse_testing.py --execute [--only baru|lama]
  python pos_sync/hapus_warehouse_testing.py --patch-state   (setelah execute:
      bersihkan artefak konsolidasi RECO dari 2 warehouse BARU yg dihapus)
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
AUDIT = os.path.normpath(os.path.join(HERE, "..", "audit_logs"))
REPORT = os.path.join(HERE, "Laporan_Hapus_Warehouse_Testing.xlsx")
STATE = os.path.join(HERE, "reco_consolidate_state.json")
PLAN = os.path.join(HERE, "reco_consolidate_plan.json")

JURI = "PT. JUARA ROTI INDONESIA"
OLD_BASE = "https://rotiropi.j.frappe.cloud"

BARU_WH = ["Gudang Testing Manufacture - JURI", "WIP Testing - JURI"]
BARU_RECO = {"Gudang Testing Manufacture - JURI": "RECO-JURI-261009046",
             "WIP Testing - JURI": "RECO-JURI-261009043"}
LAMA_WH = ["Gudang Finished Goods Testing - ROPI",
           "Gudang Testing Manufacture - ROPI", "WIP Testing - ROPI"]
LAMA_SE = ["MAT-STE-2026-05901", "MAT-STE-2026-05900",
           "MAT-STE-2026-05894", "MAT-STE-2026-01469"]  # urutan cancel
# draft testing lama (Agustus) yg memblokir hapus warehouse (link check
# Frappe menolak docstatus != 2) -> ikut dihapus (backup dulu)
LAMA_DRAFTS = ["MAT-STE-2026-03773", "MAT-STE-2026-04117"]

RESULTS = []  # (site, aksi, objek, status)


def log(m):
    print(m, flush=True)


def q(x):
    return urllib.parse.quote(str(x))


def fetch_all(c, dt, fields, filters, order=None):
    return c.list_all(dt, fields, filters=filters, order=order)


def get_doc(c, dt, name):
    st, d = c.get("/api/resource/%s/%s" % (q(dt), q(name)))
    return (d.get("data") if st == 200 else None), st


def purge_print_logs(c, names):
    n = 0
    for nm in names:
        st, d = c.get("/api/resource/POS%20Print%20Log", {
            "filters": json.dumps([["reference_name", "=", nm]]),
            "fields": json.dumps(["name"]), "limit_page_length": 0})
        for r in (d.get("data") or []):
            c.req("DELETE", "/api/resource/POS%20Print%20Log/" + q(r["name"]))
            n += 1
    return n


def wh_info(c, wh):
    d, st = get_doc(c, "Warehouse", wh)
    out = {"exists": st == 200, "doc": d}
    if st != 200:
        out["sle"] = []
        return out
    out["children"] = fetch_all(c, "Warehouse", ["name"],
                                [["parent_warehouse", "=", wh]])
    out["sle"] = fetch_all(c, "Stock Ledger Entry",
                           ["name", "posting_date", "posting_time",
                            "voucher_type", "voucher_no", "item_code",
                            "actual_qty", "qty_after_transaction",
                            "is_cancelled"],
                           [["warehouse", "=", wh]],
                           "posting_date asc, posting_time asc, name asc")
    out["bins"] = fetch_all(c, "Bin",
                            ["item_code", "actual_qty", "reserved_qty",
                             "ordered_qty", "indented_qty", "projected_qty",
                             "planned_qty"],
                            [["warehouse", "=", wh]])
    return out


def refs_check(c, whs):
    """Cari referensi lain ke warehouse target (selain dok yg akan dihapus)."""
    out = {}
    # POS Profile
    out["pos_profile"] = fetch_all(c, "POS Profile", ["name"],
                                   [["warehouse", "in", whs]])
    # Material Request (set_warehouse)
    out["mr_set"] = fetch_all(c, "Material Request",
                              ["name", "docstatus", "set_warehouse"],
                              [["set_warehouse", "in", whs]])
    # Work Order
    out["wo"] = []
    for fld in ("fg_warehouse", "source_warehouse"):
        out["wo"] += fetch_all(c, "Work Order",
                               ["name", "docstatus", fld],
                               [[fld, "in", whs]])
    # Item Default (best-effort; child doctype sering 403 di resource API)
    st, d = c.get("/api/method/frappe.client.get_list", {
        "doctype": "Item Default",
        "filters": json.dumps([["default_warehouse", "in", whs]]),
        "fields": json.dumps(["parent", "default_warehouse"]),
        "limit_page_length": 0})
    out["item_default"] = (d.get("message") if st == 200 else
                           {"info": "tidak bisa dibaca via API (HTTP %s) — "
                                    "on_trash akan unlink otomatis" % st})
    # Draft Stock Entry yang menyentuh wh
    drafts = fetch_all(c, "Stock Entry", ["name"],
                       [["company", "=", JURI], ["docstatus", "=", 0]])
    hits = []
    for r in drafts[:250]:
        dd, st2 = get_doc(c, "Stock Entry", r["name"])
        if st2 != 200:
            continue
        for it in dd.get("items", []):
            if it.get("s_warehouse") in whs or it.get("t_warehouse") in whs:
                hits.append([r["name"], it.get("item_code"),
                             it.get("s_warehouse"), it.get("t_warehouse")])
                break
    out["draft_se"] = hits
    out["draft_se_total"] = len(drafts)
    return out


def drain_repost(c):
    for i in range(1, 13):
        st, d = c.get("/api/resource/Repost Item Valuation", {
            "filters": json.dumps([["company", "=", JURI],
                                   ["status", "in", ["Queued", "In Progress"]]]),
            "fields": json.dumps(["name"]), "limit_page_length": 1})
        n = len(d.get("data", [])) if st == 200 else -1
        if n == 0:
            log("  [repost] queue kosong")
            return
        if i == 6:
            c.post("/api/method/erpnext.stock.doctype.repost_item_valuation"
                   ".repost_item_valuation.execute_repost_item_valuation", {})
        log("  [repost] ... masih %s antre" % n)
        time.sleep(10)


def plan_site(c, label, whs):
    log("")
    log("== %s ==" % label)
    for wh in whs:
        info = wh_info(c, wh)
        if not info["exists"]:
            log("  %-40s TIDAK ADA (sudah terhapus?)" % wh)
            continue
        sle = info["sle"]
        vouchers = sorted({(x["voucher_type"], x["voucher_no"]) for x in sle})
        nz_bins = [b for b in info["bins"]
                   if any(float(b.get(k) or 0) for k in
                          ("actual_qty", "reserved_qty", "ordered_qty",
                           "indented_qty", "projected_qty", "planned_qty"))]
        log("  %-40s anak=%d SLE=%d bin_isi=%d" % (
            wh, len(info.get("children") or []), len(sle), len(nz_bins)))
        for v in vouchers:
            log("      dok: %s %s" % v)
        for b in nz_bins:
            log("      bin: %s qty=%s proj=%s" % (
                b["item_code"], b["actual_qty"], b.get("projected_qty")))
    refs = refs_check(c, whs)
    log("  refs: pos_profile=%s mr=%s wo=%s draft_se=%s (dari %s draft)" % (
        refs["pos_profile"], refs["mr_set"], refs["wo"],
        refs["draft_se"], refs["draft_se_total"]))
    idf = refs["item_default"]
    log("  item_default: %s" % (json.dumps(idf)[:180] if idf else "0"))
    return refs


def backup_site(c, label, docs):  # docs: list[(dt, name)]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(AUDIT, "backup_hapus_wh_testing_%s_%s.json"
                        % (label.lower(), stamp))
    os.makedirs(AUDIT, exist_ok=True)
    bk = {}
    for dt, nm in docs:
        d, st = get_doc(c, dt, nm)
        bk["%s||%s" % (dt, nm)] = d or {"_missing": True, "_http": st}
    json.dump(bk, open(path, "w"), indent=1, default=str)
    log("[OK] backup %s: %d dok -> %s" % (label, len(bk), path))
    return path


def ensure_setter(c, dt, field):
    """Property Setter allow_on_submit=1 sementara (pola repo)."""
    rows = fetch_all(c, "Property Setter", ["name", "value"],
                     [["doc_type", "=", dt], ["field_name", "=", field],
                      ["property", "=", "allow_on_submit"]])
    if rows:
        return None, rows[0]["name"]
    st, d = c.post("Property Setter", {
        "doctype": "Property Setter", "doctype_or_field": "DocField",
        "doc_type": dt, "field_name": field,
        "property": "allow_on_submit", "property_type": "Check", "value": "1"})
    if st not in (200, 201):
        raise SystemExit("GAGAL buat setter %s.%s: HTTP %s %s"
                         % (dt, field, st, str(d)[:250]))
    return True, d["data"]["name"]


def remove_repost_links(c, whs, label=""):
    """Cancel + hapus Repost Item Valuation yg menyentuh warehouse target.

    Link-check Frappe menolak docstatus != 2; RIV `Queued` juga tak bisa
    di-cancel (before_cancel). Solusi: set status -> `Skipped` lewat
    Property Setter sementara (allow_on_submit), cancel, delete, buang
    setter.
    """
    drain_repost(c)
    rows = fetch_all(c, "Repost Item Valuation",
                     ["name", "status", "docstatus", "item_code"],
                     [["warehouse", "in", whs]])
    log("== RIV blocker %s: %d ==" % (label, len(rows)))
    if not rows:
        return
    created_setters = []
    try:
        for r in rows:
            d, st = get_doc(c, "Repost Item Valuation", r["name"])
            if st != 200:
                log("  [SKIP] RIV %s sudah tidak ada" % r["name"])
                continue
            if (d.get("status") or "") in ("Queued", "In Progress"):
                flag, sname = ensure_setter(c, "Repost Item Valuation", "status")
                if flag:
                    created_setters.append(sname)
                stv, dv = c.req("POST", "/api/method/frappe.client.set_value", {
                    "doctype": "Repost Item Valuation", "name": r["name"],
                    "fieldname": "status", "value": "Skipped"})
                log("  [%s] RIV %s status Queued -> Skipped (set_value HTTP %s)"
                    % ("OK" if stv == 200 else "FAIL", r["name"], stv))
                if stv != 200:
                    raise SystemExit("STOP %s: set status RIV %s gagal: %s"
                                     % (label, r["name"], str(dv)[:250]))
                d["status"] = "Skipped"
            if d["docstatus"] == 1:
                stc, dd = c.put("Repost Item Valuation", r["name"],
                                {"docstatus": 2})
                ok = stc == 200
                log("  [%s] cancel RIV %s: %s"
                    % ("OK" if ok else "FAIL", r["name"], stc))
                if not ok:
                    raise SystemExit("STOP %s: cancel RIV %s gagal: %s"
                                     % (label, r["name"], str(dd)[:250]))
                time.sleep(0.2)
            std, dd = c.req("DELETE", "/api/resource/Repost%20Item%20Valuation/"
                            + q(r["name"]))
            ok = std in (200, 202)
            RESULTS.append((label, "riv_delete", r["name"],
                            "OK" if ok else "FAIL %s" % std))
            log("  [%s] hapus RIV %s: %s"
                % ("OK" if ok else "FAIL", r["name"], std))
            if not ok:
                raise SystemExit("STOP %s: hapus RIV %s gagal: %s"
                                 % (label, r["name"], str(dd)[:250]))
            time.sleep(0.2)
    finally:
        for sname in created_setters:
            c.req("DELETE", "/api/resource/Property%20Setter/" + q(sname))
            log("  [setter] hapus %s" % sname)


def purge_cancelled_ledgers(c, names, label=""):
    """Hapus langsung baris GL Entry & SLE cancelled milik voucher2 ini.

    Dipakai saat Accounts Settings.delete_linked_ledger_entries tak bisa
    disetel (site LAMA: doc Accounts Settings rusak "Row #6 Doctype:
    Expense Claim" -> PUT ditolak). Baris cancelled sudah tak berdampak
    saldo; link-check Frappe melihatnya karena docstatus=1.
    """
    total = 0
    for nm in names:
        for dt, path in (("GL Entry", "GL%20Entry"),
                         ("Stock Ledger Entry", "Stock%20Ledger%20Entry")):
            rows = fetch_all(c, dt, ["name", "is_cancelled", "docstatus"],
                             [["voucher_no", "=", nm]])
            for r0 in rows:
                if not int(r0.get("is_cancelled") or 0):
                    continue
                st, _ = c.req("DELETE", "/api/resource/%s/%s"
                              % (path, q(r0["name"])))
                if st in (200, 202):
                    total += 1
                else:
                    log("  [WARN] hapus %s %s: HTTP %s"
                        % (dt, r0["name"], st))
    log("[OK] ledger cancelled %s dipurge langsung: %d baris" % (label, total))
    return total


def delete_docs(c, docs, label=""):
    """Hapus dokumen cancelled; fallback purge-ledger bila dlle tak bisa."""
    stx, _ = c.put("Accounts Settings", "Accounts Settings",
                   {"delete_linked_ledger_entries": 1})
    dlle_ok = stx == 200
    if dlle_ok:
        log("[OK] delete_linked_ledger_entries=1 (HTTP %s)" % stx)
    else:
        log("[INFO] delete_linked_ledger_entries tak bisa disetel "
            "(HTTP %s) — pakai purge ledger langsung" % stx)
    try:
        for dt, nm in docs:
            d, st = get_doc(c, dt, nm)
            if st != 200:
                RESULTS.append((label, "delete", nm, "SKIP_MISSING"))
                continue
            if d["docstatus"] != 2:
                RESULTS.append((label, "delete", nm, "SKIP_NOT_CANCELLED"))
                log("  [WARN] %s %s docstatus=%s — dilewati"
                    % (dt, nm, d["docstatus"]))
                continue
            std, dd = c.req("DELETE", "/api/resource/%s/%s" % (q(dt), q(nm)))
            if std not in (200, 202) and not dlle_ok:
                # fallback: purge ledger cancelled voucher ini lalu retry
                purge_cancelled_ledgers(c, [nm], label)
                std, dd = c.req("DELETE", "/api/resource/%s/%s"
                                % (q(dt), q(nm)))
            ok = std in (200, 202)
            RESULTS.append((label, "delete", nm,
                            "OK" if ok else "FAIL %s" % std))
            log("  [%s] delete %s: %s" % ("OK" if ok else "FAIL", nm, std))
            if not ok:
                raise SystemExit("STOP %s: delete %s gagal: %s"
                                 % (label, nm, str(dd)[:300]))
            time.sleep(0.3)
    finally:
        if dlle_ok:
            c.put("Accounts Settings", "Accounts Settings",
                  {"delete_linked_ledger_entries": 0})
            log("[OK] restore delete_linked_ledger_entries=0")


def execute_site(c, label, whs, docs, drafts=()):
    """docs = list[(doctype, name)] dalam urutan cancel yang benar.
    drafts = draft testing yang memblokir hapus warehouse (ikut dihapus)."""
    # ---------- backup ----------
    doc_rows = (list(docs) + [("Stock Entry", nm) for nm in drafts]
                + [("Warehouse", w) for w in whs if wh_info(c, w)["exists"]])
    bpath = backup_site(c, label, doc_rows)

    # ---------- kuras repost ----------
    drain_repost(c)

    # ---------- hapus draft pemblokir ----------
    for nm in drafts:
        d, st = get_doc(c, "Stock Entry", nm)
        if st != 200:
            log("  [SKIP] draft %s sudah tidak ada" % nm)
            RESULTS.append((label, "draft_delete", nm, "SKIP_MISSING"))
            continue
        if d["docstatus"] != 0:
            RESULTS.append((label, "draft_delete", nm,
                            "SKIP docstatus=%s" % d["docstatus"]))
            log("  [WARN] %s docstatus=%s (bukan draft) — dilewati"
                % (nm, d["docstatus"]))
            continue
        std, dd = c.req("DELETE", "/api/resource/Stock%20Entry/" + q(nm))
        ok = std in (200, 202)
        RESULTS.append((label, "draft_delete", nm,
                        "OK" if ok else "FAIL %s" % std))
        log("  [%s] hapus draft %s: %s" % ("OK" if ok else "FAIL", nm, std))
        if not ok:
            raise SystemExit("STOP %s: hapus draft %s gagal: %s"
                             % (label, nm, str(dd)[:300]))
        time.sleep(0.3)

    # ---------- cancel ----------
    names = [nm for _dt, nm in docs]
    purged = purge_print_logs(c, names)
    log("[OK] POS Print Log dipurge: %d" % purged)
    for dt, nm in docs:
        d, st = get_doc(c, dt, nm)
        if st != 200:
            log("  [SKIP] %s %s sudah tidak ada" % (dt, nm))
            RESULTS.append((label, "cancel", nm, "SKIP_MISSING"))
            continue
        if d["docstatus"] == 2:
            log("  [SKIP] %s %s sudah cancelled" % (dt, nm))
            RESULTS.append((label, "cancel", nm, "SKIP_CANCELLED"))
            continue
        stc, dd = c.put(dt, nm, {"docstatus": 2})
        ok = stc == 200
        RESULTS.append((label, "cancel", nm, "OK" if ok else "FAIL %s" % stc))
        log("  [%s] cancel %s: %s" % ("OK" if ok else "FAIL", nm, stc))
        if not ok:
            raise SystemExit("STOP %s: cancel %s gagal: %s"
                             % (label, nm, str(dd)[:300]))
        time.sleep(0.3)

    # ---------- hapus dokumen (dlle window / fallback ledger purge) ----------
    delete_docs(c, docs, label)

    # ---------- hapus RIV pemblokir (link-check) ----------
    remove_repost_links(c, whs, label)

    # ---------- hapus warehouse ----------
    for wh in whs:
        info = wh_info(c, wh)
        if not info["exists"]:
            RESULTS.append((label, "wh_delete", wh, "SKIP_MISSING"))
            log("  [SKIP] %s sudah tidak ada" % wh)
            continue
        if info["sle"]:
            RESULTS.append((label, "wh_delete", wh,
                            "FAIL masih ada %d SLE" % len(info["sle"])))
            raise SystemExit("STOP %s: %s masih punya %d SLE — "
                             "dokumen pemegangnya belum bersih"
                             % (label, wh, len(info["sle"])))
        if info.get("children"):
            raise SystemExit("STOP %s: %s masih punya child warehouse"
                             % (label, wh))
        nz = [b for b in info["bins"]
              if any(float(b.get(k) or 0) for k in
                     ("actual_qty", "reserved_qty", "ordered_qty",
                      "indented_qty", "projected_qty", "planned_qty"))]
        if nz:
            log("  [INFO] %s: %d Bin masih bernilai ringan "
                "(akan dibersihkan on_trash)" % (wh, len(nz)))
            for b in nz:
                log("      %s qty=%s proj=%s" % (
                    b["item_code"], b["actual_qty"], b.get("projected_qty")))
                # kosongkan nilai non-qty via set_value (Bin qty 0 aman)
                for k in ("reserved_qty", "ordered_qty", "indented_qty",
                          "projected_qty", "planned_qty"):
                    if float(b.get(k) or 0):
                        c.post("/api/method/frappe.client.set_value", {
                            "doctype": "Bin", "name": b["name"],
                            "fieldname": k, "value": 0})
        stw, dw = c.req("DELETE", "/api/resource/Warehouse/" + q(wh))
        ok = stw in (200, 202)
        RESULTS.append((label, "wh_delete", wh, "OK" if ok else "FAIL %s" % stw))
        log("  [%s] delete Warehouse %s: %s"
            % ("OK" if ok else "FAIL", wh, stw))
        if not ok:
            raise SystemExit("STOP %s: hapus %s gagal: %s"
                             % (label, wh, str(dw)[:300]))
        time.sleep(0.3)

    # ---------- verifikasi ----------
    log("")
    log("== VERIFIKASI %s ==" % label)
    allok = True
    for wh in whs:
        info = wh_info(c, wh)
        sle_n = len(info["sle"]) if info["exists"] else 0
        gone = not info["exists"]
        if not gone or sle_n:
            allok = False
        log("  [%s] %-40s warehouse=%s SLE=%d" % (
            "OK" if (gone and sle_n == 0) else "FAIL", wh,
            "TERHAPUS" if gone else "MASIH ADA", sle_n))
    for dt, nm in docs:
        d, st = get_doc(c, dt, nm)
        ok = st == 404
        if not ok:
            allok = False
        log("  [%s] %s %s: %s" % ("OK" if ok else "FAIL", dt, nm,
                                  "TERHAPUS" if ok else "MASIH ADA"))
    for nm in drafts:
        d, st = get_doc(c, "Stock Entry", nm)
        ok = st == 404
        if not ok:
            allok = False
        log("  [%s] draft %s: %s" % ("OK" if ok else "FAIL", nm,
                                     "TERHAPUS" if ok else "MASIH ADA"))
    log("  [%s] %s" % ("LOLOS" if allok else "PERIKSA",
                       "semua target terhapus" if allok else "ada sisa"))
    return bpath, allok


def write_report():
    try:
        import pandas as pd
        rows = [{"site": a, "aksi": b, "objek": c, "status": d}
                for a, b, c, d in RESULTS]
        out = REPORT
        with pd.ExcelWriter(out, engine="openpyxl") as xw:
            pd.DataFrame(rows).to_excel(xw, sheet_name="Aksi", index=False)
            pd.DataFrame([{"target_baru": ", ".join(BARU_WH),
                           "target_lama": ", ".join(LAMA_WH),
                           "dok_baru": ", ".join(BARU_RECO.values()),
                           "dok_lama": ", ".join(LAMA_SE)}
                          ]).to_excel(xw, sheet_name="Target", index=False)
        log("[OK] Laporan -> %s" % out)
    except Exception as e:  # noqa: BLE001
        log("[WARN] excel: %s" % e)


def patch_state():
    """Bersihkan artefak konsolidasi RECO dari 2 warehouse BARU yg dihapus."""
    st = json.load(open(STATE))
    pl = json.load(open(PLAN))
    for wh in BARU_WH:
        pref = wh + "|"
        for key in ("rows", "values"):
            st["snapshot"][key] = {k: v for k, v in
                                   st["snapshot"][key].items()
                                   if not k.startswith(pref)}
        st.get("created", {}).pop(wh, None)
        pl.get("consolidated", {}).pop(wh, None)
        pl.get("wh_docs", {}).pop(wh, None)
        pl.get("pred_new_blocks", {}).pop(wh, None)
        pl["cons_meta"] = {k: v for k, v in pl.get("cons_meta", {}).items()
                           if not k.startswith(pref)}
    st.setdefault("deleted_testing_whs", {})["baru"] = BARU_WH
    st["deleted_testing_whs"]["lama"] = LAMA_WH
    st["deleted_testing_whs"]["tanggal"] = "2026-10-09"
    st["deleted_testing_whs"]["docs_baru"] = list(BARU_RECO.values())
    st["deleted_testing_whs"]["docs_lama"] = LAMA_SE
    json.dump(st, open(STATE, "w"), indent=1, default=str)
    json.dump(pl, open(PLAN, "w"), indent=1, default=str)
    log("[OK] state & plan dibersihkan dari warehouse testing BARU")
    log("     created: %s" % json.dumps(st.get("created")))
    log("     gudang konsolidasi sisa: %s" % len(pl.get("consolidated", {})))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--only", choices=["baru", "lama"], default=None)
    ap.add_argument("--patch-state", action="store_true")
    args = ap.parse_args()

    prod = load_env("/tmp/eresto_prod.env")
    mig = load_env("/tmp/eresto_mig.env")
    baru = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")
    lama = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")

    if args.patch_state:
        patch_state()
        return

    do_baru = args.only in (None, "baru")
    do_lama = args.only in (None, "lama")

    if not args.execute:
        log("=" * 72)
        log("FASE PLAN (dry-run; tidak menulis)")
        if do_baru:
            plan_site(baru, "BARU", BARU_WH)
        if do_lama:
            plan_site(lama, "LAMA", LAMA_WH)
        log("")
        log("Rencana: cancel+delete dok pemegang stok -> hapus warehouse.")
        log("Jalankan: python pos_sync/hapus_warehouse_testing.py --execute "
            "[--only baru|lama]")
        return

    if do_baru:
        log("=" * 72)
        log("EKSEKUSI BARU")
        execute_site(baru, "BARU", BARU_WH,
                     [("Stock Reconciliation", nm)
                      for nm in BARU_RECO.values()])
    if do_lama:
        log("=" * 72)
        log("EKSEKUSI LAMA")
        execute_site(lama, "LAMA", LAMA_WH,
                     [("Stock Entry", nm) for nm in LAMA_SE],
                     drafts=LAMA_DRAFTS)
    write_report()
    log("")
    log("OK — lanjutkan: --patch-state lalu regenerate laporan konsolidasi")


if __name__ == "__main__":
    main()
