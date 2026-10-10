"""Bersih-bersih duplikat PO PT. JUARA ROTI INDONESIA di site BARU (2026-10-08).

Dasar: audit `Laporan_Banding_PO_PT_JURI.xlsx` + persetujuan user
("eksekusi bersihnya silahkan"). Semua tulis hanya ke site BARU.

Tindakan:
1. Hapus 26 draft eResto-ID (duplikat PO native submitted). Draft di-discover
   otomatis: company JURI + nama pola eResto + docstatus 0.
2. Cancel 4 PO eResto submitted 7 Okt (POCK2.071026.001..004) — kembaran
   native PO-071026-011..014 dipertahankan.
3. Cancel sisi native 3 pasangan stok dobel (PO + PR) — rantai eResto yang
   sudah tertaut PI (261008007/008) dipertahankan:
   PO-061026-005 + PR-061026-011 | PO-061026-006 + PR-061026-012 |
   PO-061026-007 + PR-061026-014.
4. Cancel 2 PO native tanpa rantai, duplikat PO native ber-PR:
   PO-021026-020 (kembar PO-061026-003) | PO-021026-022 (kembar PO-061026-001).

Pra-cek per dokumen (yang melanggar di-SKIP, bukan dipaksa):
- draft yang dihapus: 0 referensi purchase_order/purchase_receipt di PR/PI;
- PO/PR yang di-cancel: referensinya hanya dari pasangan yang ikut di-cancel;
- tidak ada Payment Entry submitted yang merefer target.

Rerun aman: doc sudah docstatus 2 / 404 di-skip.
Output: pos_sync/Laporan_Bersih_PO_JURI.xlsx
Env: /tmp/eresto_prod.env (ERPNEXT_URL, ERPNEXT_API_KEY) -- site BARU saja.
"""
import argparse
import json
import os
import re
import sys
import urllib.parse
from concurrent.futures import ThreadPoolExecutor

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPORT = os.path.join(HERE, "Laporan_Bersih_PO_JURI.xlsx")
ENV = "/tmp/eresto_prod.env"
COMPANY = "PT. JUARA ROTI INDONESIA"
WORKERS = 8

# --- target yang di-cancel (nama tetap; sengaja hardcode utk operasi destruktif)
CANCEL_PR = ["PR-061026-011", "PR-061026-012", "PR-061026-014"]
CANCEL_PO_NATIVE = ["PO-061026-005", "PO-061026-006", "PO-061026-007",
                    "PO-021026-020", "PO-021026-022"]
CANCEL_PO_ERESTO = ["POCK2.071026.001", "POCK2.071026.002",
                    "POCK2.071026.003", "POCK2.071026.004"]
CANCEL_ALL = set(CANCEL_PR + CANCEL_PO_NATIVE + CANCEL_PO_ERESTO)

KEEP_ERESTO = ["POCK2.250926.001", "POCK2.250926.003", "POCK2.280926.001",
               "POCK2.300926.002", "POGBJ.290526.001"]


def log(m):
    print(m, flush=True)


def is_eresto_id(n):
    return bool(re.search(r"\.[0-9]{6}\.[0-9]{3}$", n or ""))


def full(c, dt, n):
    st, d = c.get("/api/resource/" + urllib.parse.quote(dt) + "/"
                  + urllib.parse.quote(n))
    return d.get("data") if st == 200 else None


def fetch_all(c, dt, fields, filters=None):
    return c.list_all(dt, fields, filters=filters)


def scan_refs(c):
    """Peta referensi: siapa saja (PR/PI submitted) yang menyebut doc X."""
    refs = {}          # doc -> [(dokumen, jenis, docstatus)]
    prs = fetch_all(c, "Purchase Receipt", ["name", "docstatus"],
                    [["company", "=", COMPANY]])
    pis = fetch_all(c, "Purchase Invoice", ["name", "docstatus"],
                    [["company", "=", COMPANY]])
    todo = [("Purchase Receipt", r["name"]) for r in prs] + \
           [("Purchase Invoice", r["name"]) for r in pis]
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        data = list(ex.map(lambda t: (t[0], t[1], full(c, t[0], t[1])), todo))
    for dt, n, d in data:
        if not d:
            continue
        ds = d.get("docstatus")
        for it in d.get("items") or []:
            for f in ("purchase_order", "purchase_receipt"):
                v = it.get(f)
                if v:
                    refs.setdefault(v, []).append((n, dt, ds))
    return refs, len(prs), len(pis)


def scan_payments(c):
    pes = fetch_all(c, "Payment Entry", ["name", "docstatus"],
                    [["company", "=", COMPANY]])
    hit = {}
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        data = list(ex.map(lambda r: (r["name"], full(c, "Payment Entry",
                                                       r["name"])), pes))
    for n, d in data:
        if not d or d.get("docstatus") != 1:
            continue
        for r in d.get("references") or []:
            if r.get("reference_name") in CANCEL_ALL:
                hit.setdefault(r["reference_name"], []).append(n)
    return hit, len(pes)


def discover_drafts(c):
    pos = fetch_all(c, "Purchase Order", ["name", "docstatus", "supplier",
                                          "grand_total", "transaction_date",
                                          "owner"],
                    [["company", "=", COMPANY]])
    drafts = [r for r in pos if r["docstatus"] == 0 and is_eresto_id(r["name"])]
    return pos, drafts


def preflight(drafts, refs, pe_hits):
    """Kembalikan (delete_ok, cancel_ok, catatan) — dokumen tidak aman di-skip."""
    notes, delete_ok, cancel_ok = [], [], []
    for d in drafts:
        n = d["name"]
        r = refs.get(n) or []
        if r:
            notes.append((n, "SKIP_UNSAFE", f"masih dirujuk: {r[:3]}"))
        else:
            delete_ok.append(n)
    for n in CANCEL_PR + CANCEL_PO_NATIVE + CANCEL_PO_ERESTO:
        r = refs.get(n) or []
        bad = [x for x in r if x[0] not in CANCEL_ALL]
        if bad:
            notes.append((n, "SKIP_UNSAFE", f"dirujuk pihak lain: {bad[:3]}"))
        elif n in pe_hits:
            notes.append((n, "SKIP_UNSAFE", f"ada Payment Entry: {pe_hits[n]}"))
        else:
            cancel_ok.append(n)
    return delete_ok, cancel_ok, notes


def write_report(rows, checks, kept, path=REPORT):
    wb = Workbook()
    ws = wb.active
    ws.title = "Aksi"
    ws.append(["doctype", "name", "aksi", "hasil", "keterangan"])
    for r in rows:
        ws.append(r)
    ws2 = wb.create_sheet("Verifikasi")
    ws2.append(["check", "hasil", "status"])
    for c in checks:
        ws2.append(list(c))
    ws3 = wb.create_sheet("Rantai_Dipertahankan")
    ws3.append(["dokumen", "keterangan"])
    for r in kept:
        ws3.append(list(r))
    for w in (ws, ws2, ws3):
        for cell in w[1]:
            cell.fill = PatternFill("solid", fgColor="D9EAF7")
            cell.font = Font(bold=True)
        w.freeze_panes = "A2"
        for col in range(1, w.max_column + 1):
            w.column_dimensions[get_column_letter(col)].width = 34
    wb.save(path)
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute", action="store_true",
                    help="jalankan (default: dry-run)")
    args = ap.parse_args()

    env = load_env(ENV)
    c = Client(env["ERPNEXT_URL"], env["ERPNEXT_API_KEY"], "baru", pause=0.1)

    log("[scan] PO + referensi PR/PI ...")
    pos, drafts = discover_drafts(c)
    refs, n_pr, n_pi = scan_refs(c)
    pe_hits, n_pe = scan_payments(c)
    log(f"  PO JURI: {len(pos)} | draft eResto-ID: {len(drafts)} | "
        f"PR: {n_pr} | PI: {n_pi} | PE: {n_pe}")

    delete_ok, cancel_ok, notes = preflight(drafts, refs, pe_hits)
    for n, st, ket in notes:
        log(f"  [{st}] {n}: {ket}")
    log(f"[plan] hapus {len(delete_ok)} draft | cancel {len(cancel_ok)} dokumen")

    # urutan cancel: PR dulu, lalu PO native, lalu PO eResto
    order = [n for n in CANCEL_PR if n in cancel_ok] + \
            [n for n in CANCEL_PO_NATIVE if n in cancel_ok] + \
            [n for n in CANCEL_PO_ERESTO if n in cancel_ok]
    dt_of = {}
    for n in CANCEL_PR:
        dt_of[n] = "Purchase Receipt"
    for n in CANCEL_PO_NATIVE + CANCEL_PO_ERESTO:
        dt_of[n] = "Purchase Order"

    ITEMS = ("BB260031", "PEL260075", "PEL260011")
    WH = "Gudang Jakarta - JURI"

    def bin_qty():
        out = {}
        for it in ITEMS:
            st, d = c.get("/api/resource/Bin",
                          {"filters": json.dumps([["item_code", "=", it],
                                                  ["warehouse", "=", WH]]),
                           "fields": json.dumps(["actual_qty"])})
            r = (d.get("data") or [{}])[0]
            out[it] = float(r.get("actual_qty") or 0)
        return out

    bin_before = bin_qty()

    rows = []
    if not args.execute:
        for n in delete_ok:
            rows.append(["Purchase Order", n, "DELETE", "DRY",
                         "draft duplikat"])
        for n in order:
            rows.append([dt_of[n], n, "CANCEL", "DRY", "kembar duplikat"])
        log("[dry-run] tidak ada perubahan. Jalankan --execute untuk eksekusi.")
    else:
        for n in delete_ok:
            d = full(c, "Purchase Order", n)
            if d is None:
                rows.append(["Purchase Order", n, "DELETE", "SKIP_SUDAH",
                             "sudah tidak ada (404)"])
                continue
            st, d = c.delete("Purchase Order", n)
            ok = st in (200, 202, 204)
            rows.append(["Purchase Order", n, "DELETE",
                         "OK" if ok else f"GAGAL HTTP {st}",
                         str(d)[:200] if not ok else "draft dihapus"])
            log(f"  delete {n}: {'OK' if ok else 'GAGAL ' + str(st)}")
        for n in order:
            cur = full(c, dt_of[n], n)
            if cur and cur.get("docstatus") == 2:
                rows.append([dt_of[n], n, "CANCEL", "SKIP_SUDAH",
                             "sudah cancelled"])
                continue
            st, d = c.cancel(dt_of[n], n)
            ok = st == 200
            rows.append([dt_of[n], n, "CANCEL",
                         "OK" if ok else f"GAGAL HTTP {st}",
                         str(d)[:200] if not ok else "cancelled"])
            log(f"  cancel {n}: {'OK' if ok else 'GAGAL ' + str(st)}")

    bin_after = bin_qty()

    # ---- verifikasi akhir (live)
    pos2, drafts2 = discover_drafts(c)
    eran = [r for r in pos2 if is_eresto_id(r["name"])]
    er_sub = [r["name"] for r in eran if r["docstatus"] == 1]
    er_can = [r["name"] for r in eran if r["docstatus"] == 2]
    kept_missing = [n for n in KEEP_ERESTO if n not in er_sub]
    nat_ok = [n for n in ("PO-071026-011", "PO-071026-012", "PO-071026-013",
                          "PO-071026-014", "PO-061026-003", "PO-061026-001")
              if any(r["name"] == n and r["docstatus"] == 1 for r in pos2)]
    prs2 = fetch_all(c, "Purchase Receipt", ["name", "docstatus"],
                     [["company", "=", COMPANY]])
    pr_sub = [r for r in prs2 if r["docstatus"] == 1]
    # delta Bin yang diharapkan dari cancel PR sisi native: -stock
    exp_delta = {"BB260031": -204000.0, "PEL260075": -1000.0, "PEL260011": -5.0}
    bin_ok = []
    for it in ITEMS:
        d_act = bin_after[it] - bin_before[it]
        d_exp = exp_delta[it] if args.execute else 0.0
        bin_ok.append(f"{it}: {d_act:+g}")
        if abs(d_act - d_exp) > 0.01:
            bin_ok.append(f"(EXPECT {d_exp:+g}!)")
    checks = [
        ("Draft eResto-ID tersisa", f"{len(drafts2)}", "OK" if not drafts2 else "CATATAN"),
        ("eResto-ID submitted (harus 5)", f"{sorted(er_sub)}",
         "OK" if sorted(er_sub) == sorted(KEEP_ERESTO) and not kept_missing else "CATATAN"),
        ("eResto-ID cancelled", f"{len(er_can)}", "OK" if len(er_can) == 4 else "CATATAN"),
        ("Native keeper submitted", f"{len(nat_ok)}/6", "OK" if len(nat_ok) == 6 else "CATATAN"),
        ("PR submitted (harus 71)", f"{len(pr_sub)}",
         "OK" if len(pr_sub) == (n_pr - 3 if args.execute else n_pr) else "CATATAN"),
        (f"Bin Gudang Jakarta {'(setelah cancel)' if args.execute else '(dry)'}",
         "; ".join(bin_ok), "OK"),
    ]
    kept = [
        ("POCK2.250926.001 + PR-011026-021 + PI-JURI-261008007", "rantai PI Ayla (INVCK2.081026.003) dipertahankan"),
        ("POCK2.280926.001 + PR-011026-022 + PI-JURI-261008008", "rantai PI Tokopedia (INVCK2.011026.002) dipertahankan"),
        ("POCK2.250926.003 + PR-011026-020", "rantai eResto dipertahankan (seragam dgn 2 sibling CK2)"),
        ("POCK2.300926.002 + PR-081026-005 + PI-JURI-261008012", "kembaran native hanya ada di LAMA"),
        ("POGBJ.290526.001 + PR-061026-015 + PI-JURI-261008001", "PO Mei Alkindo, tanpa kembaran"),
        ("PO-071026-011..014 / PO-061026-001 / PO-061026-003", "native keeper (ber-PR)"),
    ]
    rp = write_report(rows, checks, kept)
    for _, h, s in checks:
        log(f"  [check] {s}: {h}")
    log(f"[report] {rp}")


if __name__ == "__main__":
    main()
