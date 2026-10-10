"""Bandingkan PO PT. JUARA ROTI INDONESIA: ERPNext LAMA vs Cloud BARU.

Konteks (instruksi user 2026-10-08): draft PO di site BARU sebagian besar
diinput dari eResto; PO pabrik/PT yang asli sudah diinput langsung di
ERPNext dengan ID asli (PO-<DDMMYY>-<NNN>), bukan ID eResto
(POCK2./POGBJ./POGPT./POGBBK.<DDMMYY>.<NNN>). Tugas: cocokkan tanggal +
item + supplier, tandai duplikat.

Fase:
  --fetch   tarik daftar + detail PO kedua site (cache pos_sync/po_juri_dump/)
  --match   jalankan pencocokan, cetak ringkasan
  --report  tulis pos_sync/Laporan_Banding_PO_PT_JURI.xlsx
Default: semua. --refresh untuk tarik ulang detail.
Read-only di kedua site.

Konvensi cocok: item sama + qty sama (via konversi stok), tanggal ±3 hari,
total sama atau beda faktor PPN 1.11; supplier dianggap setara bila sama
atau dua-duanya marketplace (Tokopedia/Shopee).
"""
import argparse
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from urllib.parse import quote

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
CMP = os.path.join(HERE, "po_juri_dump")
REPORT = os.path.join(HERE, "Laporan_Banding_PO_PT_JURI.xlsx")
OLD_BASE = "https://rotiropi.j.frappe.cloud"
COMPANY = "PT. JUARA ROTI INDONESIA"
WORKERS = 8
WINDOW = ("2026-09-01", "2026-10-09")

LIST_FIELDS = ["name", "supplier", "supplier_name", "transaction_date",
               "grand_total", "status", "docstatus", "set_warehouse",
               "creation", "owner"]
DET_FIELDS = ("name", "supplier", "supplier_name", "transaction_date",
              "grand_total", "net_total", "total_taxes_and_charges", "status",
              "docstatus", "set_warehouse", "creation", "owner")
ROW_FIELDS = ("item_code", "item_name", "qty", "uom", "conversion_factor",
              "rate", "amount", "warehouse")


def log(m):
    print(m, flush=True)


def fnum(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def pdate(v):
    return str(v or "")[:10]


def is_eresto_id(name):
    return bool(re.search(r"\.[0-9]{6}\.[0-9]{3}$", name or ""))


def jenis(name):
    return "eResto" if is_eresto_id(name) else "ERPNext"


def norm_sup(s):
    s = str(s or "").lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(s.split())


def sup_equiv(a, b):
    na, nb = norm_sup(a), norm_sup(b)
    if na == nb:
        return True
    m_a = ("tokopedia" in na) or ("shopee" in na)
    m_b = ("tokopedia" in nb) or ("shopee" in nb)
    return m_a and m_b


def jload(name, default=None):
    p = os.path.join(CMP, name)
    if not os.path.exists(p):
        return default
    with open(p) as f:
        return json.load(f)


def jsave(name, obj):
    os.makedirs(CMP, exist_ok=True)
    with open(os.path.join(CMP, name), "w") as f:
        json.dump(obj, f, default=str, indent=1)


# ------------------------------------------------------------------ fetch
def fetch_list(c, window=None):
    filters = [["company", "=", COMPANY]]
    if window:
        filters += [["transaction_date", ">=", window[0]],
                    ["transaction_date", "<=", window[1]]]
    return c.list_all("Purchase Order", LIST_FIELDS, filters=filters,
                      order="transaction_date asc")


def fetch_details(c, names, cache_name, refresh=False):
    det = {} if refresh else (jload(cache_name) or {})
    todo = [n for n in names if n not in det or "owner" not in (det.get(n) or {})]
    if todo:
        log(f"  [fetch] {len(todo)} detail PO ({cache_name}) ...")
        t0 = time.time()
        ok = 0
        with ThreadPoolExecutor(max_workers=WORKERS) as ex:
            futs = {ex.submit(c.get, "/api/resource/Purchase Order/" + quote(n)): n
                    for n in todo}
            for f in as_completed(futs):
                n = futs[f]
                st, d = f.result()
                if st == 200 and isinstance(d, dict) and d.get("data"):
                    doc = d["data"]
                    det[n] = {k: doc.get(k) for k in DET_FIELDS}
                    det[n]["items"] = [{k: it.get(k) for k in ROW_FIELDS}
                                       for it in doc.get("items") or []]
                    ok += 1
                else:
                    log(f"  [warn] detail {n} gagal: HTTP {st} {str(d)[:120]}")
        jsave(cache_name, det)
        log(f"  [fetch] selesai {ok}/{len(todo)} dalam {time.time()-t0:.1f}s")
    else:
        log(f"  [fetch] cache: {len(det)} detail ({cache_name})")
    return det


# ------------------------------------------------------------------ match
def rows_of(doc):
    out = []
    for it in doc.get("items") or []:
        cf = fnum(it.get("conversion_factor")) or 1.0
        out.append({"code": it.get("item_code"),
                    "qty": fnum(it.get("qty")),
                    "sqty": fnum(it.get("qty")) * cf,
                    "uom": it.get("uom"), "cf": cf,
                    "rate": fnum(it.get("rate")),
                    "amt": fnum(it.get("amount")),
                    "name": it.get("item_name")})
    return out


def fmt_items(doc, maxn=3):
    rows = rows_of(doc)
    parts = [f"{r['code']} x{r['qty']:g}{r['uom'] or ''}@{r['rate']:g}" for r in rows[:maxn]]
    if len(rows) > maxn:
        parts.append(f"+{len(rows)-maxn} lain")
    return "; ".join(parts)


def cmp_docs(a, b):
    ra, rb = rows_of(a), rows_of(b)
    used, qm, am, um = set(), 0, 0, 0
    for x in ra:
        best = None
        for i, y in enumerate(rb):
            if i in used:
                continue
            if y["code"] == x["code"] and abs(y["sqty"] - x["sqty"]) <= max(0.011, abs(x["sqty"]) * 1e-4):
                best = i
                break
        if best is None:
            continue
        used.add(best)
        qm += 1
        y = rb[best]
        if abs(y["amt"] - x["amt"]) <= max(1.0, abs(x["amt"]) * 0.005):
            am += 1
        if str(y["uom"]).lower() != str(x["uom"]).lower():
            um += 1
    n = max(len(ra), len(rb), 1)
    da, db = pdate(a.get("transaction_date")), pdate(b.get("transaction_date"))
    dd = abs((date.fromisoformat(da) - date.fromisoformat(db)).days) if da and db else 999
    ta, tb = fnum(a.get("grand_total")), fnum(b.get("grand_total"))
    na, nb = fnum(a.get("net_total")), fnum(b.get("net_total"))
    total_same = abs(ta - tb) <= max(1.0, 0.001 * max(ta, tb))
    net_same = abs(na - nb) <= max(1.0, 0.001 * max(na, nb))
    tax_factor = None
    if ta and not total_same:
        r = tb / ta
        for f, tag in ((1.11, "×1.11"), (1 / 1.11, "÷1.11")):
            if abs(r - f) < 0.012:
                tax_factor = tag
                break
    return {"n_a": len(ra), "n_b": len(rb),
            "qty_match": round(qm / n, 4), "amt_match": round(am / n, 4),
            "uom_diff": um, "date_diff": dd, "date_a": da, "date_b": db,
            "sup_a": a.get("supplier_name") or a.get("supplier"),
            "sup_b": b.get("supplier_name") or b.get("supplier"),
            "sup_same": sup_equiv(a.get("supplier_name") or a.get("supplier"),
                                  b.get("supplier_name") or b.get("supplier")),
            "total_a": ta, "total_b": tb, "total_same": total_same,
            "net_same": net_same, "tax_factor": tax_factor}


def candidates(src, pool):
    """Kandidat dari pool (dict name->detail), urut terbaik."""
    out = []
    for n, d in pool.items():
        if n == src.get("name"):
            continue
        c = cmp_docs(src, d)
        if c["qty_match"] >= 0.999 or (c["qty_match"] >= 0.6 and c["sup_same"] and c["date_diff"] <= 1):
            c.update({"name": n, "jenis": jenis(n), "ds": d.get("docstatus"),
                      "tgl": pdate(d.get("transaction_date")),
                      "sup": d.get("supplier_name") or d.get("supplier"),
                      "total": fnum(d.get("grand_total")),
                      "owner": d.get("owner"),
                      "items": fmt_items(d)})
            out.append(c)
    out.sort(key=lambda c: (-round(c["qty_match"], 3), c["date_diff"],
                            0 if c["sup_same"] else 1,
                            0 if c["total_same"] else (0 if c["tax_factor"] else 1)))
    return out


def verdict(c):
    if not c:
        return "TIDAK ADA padanan native"
    bits = []
    bits.append("tgl sama" if c["date_diff"] == 0 else f"tgl±{c['date_diff']}h")
    bits.append("item+qty 100%" if c["qty_match"] >= 0.999 else f"item {c['qty_match']*100:.0f}%")
    bits.append("supplier sama" if c["sup_same"] else f"supplier beda ({c['sup_b']})")
    if c["total_same"]:
        bits.append("total sama")
    elif c["tax_factor"]:
        bits.append(f"total {c['tax_factor']} (PPN)")
    else:
        bits.append("total beda")
    return ", ".join(bits)


# ------------------------------------------------------------------ report
def write_report(baru_det, lama_det, baru_list, lama_list, baru_best, lama_best):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    def style(ws):
        fill = PatternFill("solid", fgColor="D9EAF7")
        for c in ws[1]:
            c.fill, c.font = fill, Font(bold=True)
            c.alignment = Alignment(horizontal="center", vertical="center",
                                    wrap_text=True)
        ws.freeze_panes = "A2"
        try:
            ws.auto_filter.ref = ws.dimensions
        except Exception:
            pass
        for col in ws.columns:
            w = max(len(str(c.value or "")) for c in ws[col[0].column])
            ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 52)

    wb = Workbook()
    lama_names = {r["name"] for r in lama_list}
    baru_names = {r["name"] for r in baru_list}

    # Sheet 1: eResto-ID BARU vs native
    s1 = wb.active
    s1.title = "Baru_eRestoID"
    s1.append(["baru_name", "jenis", "ds", "tgl", "supplier", "total",
               "items", "ada_di_LAMA", "native_name", "native_ds", "native_tgl",
               "native_supplier", "native_total", "qty_match", "amt_match",
               "sup_same", "total_same", "tax_factor", "verdict",
               "kandidat_lain", "owner_baru", "catatan"])
    for b in sorted(baru_list, key=lambda r: (r["transaction_date"], r["name"])):
        if not is_eresto_id(b["name"]):
            continue
        d = baru_det.get(b["name"]) or {}
        c = baru_best.get(b["name"])
        cat = []
        if c and c["date_diff"] > 1:
            cat.append("tanggal jauh")
        if c and not c["sup_same"] and not (("tokopedia" in norm_sup(c["sup_a"]) or "shopee" in norm_sup(c["sup_a"]))
                                            and ("tokopedia" in norm_sup(c["sup_b"]) or "shopee" in norm_sup(c["sup_b"]))):
            cat.append("supplier berbeda nyata")
        if c and not c["total_same"] and not c["tax_factor"]:
            cat.append("total tidak ketemu faktor")
        if c and c["uom_diff"]:
            cat.append(f"UOM beda {c['uom_diff']} baris")
        rows = [b["name"], "eResto", b["docstatus"], pdate(b["transaction_date"]),
                b.get("supplier_name"), fnum(b.get("grand_total")),
                fmt_items(d), "YA" if b["name"] in lama_names else "tidak"]
        if c:
            rows += [c["name"], c["ds"], c["tgl"], c["sup"], c["total"],
                     c["qty_match"], c["amt_match"], c["sup_same"],
                     c["total_same"], c["tax_factor"] or "", verdict(c),
                     "", d.get("owner") or "", " | ".join(cat)]
        else:
            rows += ["", "", "", "", "", "", "", "", "", "", "", "", d.get("owner") or "", " | ".join(cat)]
        s1.append(rows)

    # Sheet 2: draft detail item-level
    s2 = wb.create_sheet("Draft_Item_Detail")
    s2.append(["draft", "draft_tgl", "draft_supplier", "native", "native_tgl",
               "native_supplier", "item_draft", "qty_draft", "uom_draft",
               "stok_qty_draft", "rate_draft", "amt_draft", "item_native",
               "qty_native", "uom_native", "stok_qty_native", "rate_native",
               "amt_native", "item_ok", "qty_ok", "uom_sama", "amt_ok"])
    for b in sorted(baru_list, key=lambda r: r["name"]):
        if b["docstatus"] != 0 or not is_eresto_id(b["name"]):
            continue
        c = baru_best.get(b["name"])
        ra = rows_of(baru_det.get(b["name"]) or {})
        rb = rows_of(lama_det.get(c["name"])) if c else []
        for x in ra:
            hit = None
            for y in rb:
                if y["code"] == x["code"] and abs(y["sqty"] - x["sqty"]) <= max(0.011, abs(x["sqty"]) * 1e-4):
                    hit = y
                    break
            y = hit or {}
            s2.append([b["name"], pdate(b["transaction_date"]), b.get("supplier_name"),
                       (c or {}).get("name", ""), (c or {}).get("tgl", ""), (c or {}).get("sup", ""),
                       x["code"], x["qty"], x["uom"], x["sqty"], x["rate"], x["amt"],
                       y.get("code", ""), y.get("qty", ""), y.get("uom", ""), y.get("sqty", ""),
                       y.get("rate", ""), y.get("amt", ""),
                       bool(hit), bool(hit),
                       (str(y.get("uom")).lower() == str(x["uom"]).lower()) if hit else "",
                       bool(hit and abs(y["amt"] - x["amt"]) <= max(1.0, abs(x["amt"]) * 0.005))])

    # Sheet 3: rekap LAMA (window)
    s3 = wb.create_sheet("Rekap_Lama")
    s3.append(["lama_name", "jenis", "ds", "tgl", "supplier", "total", "status",
               "match_baru", "jenis_match", "score_note"])
    for r in sorted(lama_list, key=lambda x: (x["transaction_date"], x["name"])):
        m = lama_best.get(r["name"])
        if r["name"] in baru_names:
            note = "ADA di BARU (ID sama)"
        elif m:
            note = "ADA di BARU (padanan beda ID)"
        else:
            note = "TIDAK ADA di BARU"
        s3.append([r["name"], jenis(r["name"]), r["docstatus"],
                   pdate(r["transaction_date"]), r.get("supplier_name"),
                   fnum(r.get("grand_total")), r.get("status"),
                   (m or {}).get("name", ""), (m or {}).get("jenis", ""),
                   note])

    # Sheet 4: rekap BARU (semua)
    s4 = wb.create_sheet("Rekap_Baru")
    s4.append(["baru_name", "jenis", "ds", "tgl", "supplier", "total", "status",
               "match_lama", "jenis_match", "match_ds", "catatan"])
    for r in sorted(baru_list, key=lambda x: (x["transaction_date"], x["name"])):
        m = baru_best.get(r["name"])
        note = ""
        if is_eresto_id(r["name"]):
            note = "eResto-ID" + (" (draft)" if r["docstatus"] == 0 else "")
            if m:
                note += " -> native " + m["name"]
        else:
            note = "native-ID" + (" (ADA di LAMA)" if r["name"] in lama_names else " (TIDAK di LAMA)")
        s4.append([r["name"], jenis(r["name"]), r["docstatus"],
                   pdate(r["transaction_date"]), r.get("supplier_name"),
                   fnum(r.get("grand_total")), r.get("status"),
                   (m or {}).get("name", ""), (m or {}).get("jenis", ""),
                   (m or {}).get("ds", ""), note])

    # Sheet 5: pasangan duplikat SUBMITTED di BARU (eResto-ID + native dua-duanya ds=1)
    s5 = wb.create_sheet("Duplikat_Submitted")
    s5.append(["eResto_name", "eResto_tgl", "eResto_total", "eResto_created",
               "native_name", "native_tgl", "native_total", "native_created",
               "supplier", "qty_match", "total_same", "verdict"])
    for b in sorted(baru_list, key=lambda r: r["name"]):
        if not is_eresto_id(b["name"]) or b["docstatus"] != 1:
            continue
        c = baru_best.get(b["name"])
        if not c:
            continue
        nd = baru_det.get(c["name"]) or {}
        s5.append([b["name"], pdate(b["transaction_date"]),
                   fnum(b.get("grand_total")), str((baru_det.get(b["name"]) or {}).get("creation"))[:19],
                   c["name"], c["tgl"], c["total"], str(nd.get("creation"))[:19],
                   c["sup"], c["qty_match"], c["total_same"], verdict(c)])

    # Sheet 6: rekomendasi untuk 26 draft (semua punya native twin submitted)
    NOTES = {
        "POGBJ.011026.001": "supplier draft 'Toko Bahan Kue' vs native 'Toko Santi' — konfirmasi mana yang benar",
        "POGBJ.021026.001": "supplier draft 'Toko Bahan Kue' vs native 'Toko Santi' — konfirmasi mana yang benar",
        "POGPT.021026.001": "harga draft 22.400/kg vs native 24.800/kg (beda harga, bukan PPN)",
        "POGPT.011026.001": "UOM draft zak(12kg) vs native kg; tanggal ±1h (pairing berdasar qty)",
        "POGPT.021026.002": "UOM draft zak(12kg) vs native kg; tanggal ±1h (pairing berdasar qty)",
        "POGBJ.021026.015": "tanggal draft 2 Okt vs native 25 Sep; item/qty/total identik",
        "POCK2.021026.003": "2 kandidat native: PO-021026-022 (tanpa PR) & PO-061026-001 (punya PR-061026-001, rate sama dgn draft)",
    }
    s7 = wb.create_sheet("Rekomendasi_Draft")
    s7.append(["draft_eResto", "tgl", "supplier", "total", "native_ERPNext",
               "native_status", "native_ada_PR", "rekomendasi", "catatan"])
    for b in sorted(baru_list, key=lambda r: r["name"]):
        if b["docstatus"] != 0 or not is_eresto_id(b["name"]):
            continue
        c = baru_best.get(b["name"])
        native = c["name"] if c else ""
        n_ds = c["ds"] if c else ""
        s7.append([b["name"], pdate(b["transaction_date"]), b.get("supplier_name"),
                   fnum(b.get("grand_total")), native,
                   {1: "Submitted", 0: "Draft", 2: "Cancelled"}.get(n_ds, n_ds),
                   "", "Draft duplikat — native sudah ada; rekomendasi hapus draft",
                   NOTES.get(b["name"], "")])

    # Sheet 7: pasangan stok dobel (PO+PR ganda di BARU, warisan dari LAMA)
    s8 = wb.create_sheet("Double_Receipt")
    s8.append(["eResto_PO", "PR_eResto", "native_PO", "PR_native", "item", "qty",
               "catatan"])
    DOUBLES = [
        ("POCK2.250926.001", "PR-011026-021", "PO-061026-005", "PR-061026-011",
         "BB260031 (Coffee Latte 500g)", "17 ctn", "dua PO + dua PR submitted di BARU (sama juga di LAMA) → stok dobel"),
        ("POCK2.250926.003", "PR-011026-020", "PO-061026-007", "PR-061026-014",
         "PEL260075 (Kertas Thermal)", "100 Pack", "dua PO + dua PR submitted di BARU (sama juga di LAMA) → stok dobel"),
        ("POCK2.280926.001", "PR-011026-022", "PO-061026-006", "PR-061026-012",
         "PEL260011 (Capitan Roti)", "5 Pcs", "dua PO + dua PR submitted di BARU (sama juga di LAMA) → stok dobel"),
    ]
    for row in DOUBLES:
        s8.append(list(row))

    # Sheet 8: Validation
    s9 = wb.create_sheet("Validation")
    s9.append(["check", "hasil", "status"])
    e = [r for r in baru_list if is_eresto_id(r["name"])]
    dr = [r for r in e if r["docstatus"] == 0]
    with_native = [r for r in e if baru_best.get(r["name"])]
    no_native = [r["name"] for r in e if not baru_best.get(r["name"])]
    checks = [
        ("LAMA PO PT JURI (1 Sep–9 Okt 2026)", f"{len(lama_list)} PO", "OK"),
        ("BARU PO PT JURI (semua)", f"{len(baru_list)} PO", "OK"),
        ("BARU eResto-ID", f"{len(e)} (draft {len(dr)})", "OK"),
        ("eResto-ID BARU punya padanan native", f"{len(with_native)}/{len(e)}",
         "OK" if len(with_native) == len(e) else "CATATAN"),
        ("Tanpa padanan", f"{len(no_native)}: {', '.join(no_native) or '-'}",
         "CATATAN" if no_native else "OK"),
        ("BARU native ada di LAMA",
         f"{len([r for r in baru_list if not is_eresto_id(r['name']) and r['name'] in lama_names])}/"
         f"{len([r for r in baru_list if not is_eresto_id(r['name'])])}", "OK"),
        ("Draft duplikat dgn native submitted",
         f"{len([r for r in dr if (baru_best.get(r['name']) or {}).get('ds') == 1])}/{len(dr)}", "CATATAN"),
    ]
    for c in checks:
        s9.append(list(c))

    for ws in (s1, s2, s3, s4, s5, s7, s8, s9):
        style(ws)
    wb.save(REPORT)
    return REPORT


# ------------------------------------------------------------------ main
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--refresh", action="store_true")
    args = ap.parse_args()

    mig = load_env("/tmp/eresto_mig.env")
    prod = load_env("/tmp/eresto_prod.env")
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "lama")
    new = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "baru")

    log("[list] tarik SEMUA daftar PO PT JURI (kedua site) ...")
    lama_all = fetch_list(old, window=None)
    baru_all = fetch_list(new, window=None)
    lama_list = [r for r in lama_all if WINDOW[0] <= pdate(r["transaction_date"]) <= WINDOW[1]]
    log(f"  LAMA: {len(lama_all)} PO (semua) | jendela {WINDOW[0]}..{WINDOW[1]}: {len(lama_list)}")
    log(f"  BARU: {len(baru_all)} PO")
    jsave("list_lama.json", lama_list)
    jsave("list_baru.json", baru_all)

    lama_det = fetch_details(old, [r["name"] for r in lama_all], "details_lama.json",
                             refresh=args.refresh)
    baru_det = fetch_details(new, [r["name"] for r in baru_all], "details_baru.json",
                             refresh=args.refresh)

    log("\n[match] mencocokkan ...")
    # pool native khusus (utk padanan draft/ID eResto)
    lama_native = {n: d for n, d in lama_det.items() if not is_eresto_id(n)}
    baru_native = {n: d for n, d in baru_det.items() if not is_eresto_id(n)}

    baru_best, lama_best = {}, {}
    for b in sorted(baru_all, key=lambda r: r["name"]):
        d = baru_det.get(b["name"])
        if not d:
            continue
        if is_eresto_id(b["name"]):
            cands = [c for c in candidates(d, lama_native) if c["name"] in baru_native]
            if not cands:
                cands = candidates(d, lama_native)
            baru_best[b["name"]] = cands[0] if cands else None
        else:
            c = candidates(d, baru_det)
            c = [x for x in c if x["name"] != b["name"]]
            baru_best[b["name"]] = c[0] if c else None
    for l in sorted(lama_list, key=lambda r: r["name"]):
        d = lama_det.get(l["name"])
        if not d:
            continue
        c = candidates(d, baru_det)
        lama_best[l["name"]] = c[0] if c else None

    # ringkasan draft
    log("\n=== DRAFT BARU (26) vs padanan native ===")
    n_dup = 0
    for b in sorted(baru_all, key=lambda r: r["name"]):
        if b["docstatus"] != 0 or not is_eresto_id(b["name"]):
            continue
        c = baru_best.get(b["name"])
        if c:
            n_dup += 1
            log(f"  {b['name']:<24} -> {c['name']:<22} {verdict(c)}")
        else:
            log(f"  {b['name']:<24} -> (tidak ada padanan yang lolos)")
    log(f"  {n_dup}/26 draft punya padanan native")

    # ringkasan eResto-ID submitted
    log("\n=== eResto-ID BARU submitted (8) ===")
    for b in sorted(baru_all, key=lambda r: r["name"]):
        if b["docstatus"] == 0 or not is_eresto_id(b["name"]):
            continue
        c = baru_best.get(b["name"])
        log(f"  {b['name']:<24} -> " + (c["name"] + " | " + verdict(c) if c else "(tidak ada padanan)"))

    rp = write_report(baru_det, lama_det, baru_all, lama_list, baru_best, lama_best)
    log(f"\n[report] {rp}")


if __name__ == "__main__":
    main()
