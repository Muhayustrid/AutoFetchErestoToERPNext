#!/usr/bin/env python3
"""pos_sync/fill_opening_sep30.py — isi saldo 30 Sep 2026 23:00 ke ERPNext BARU.

Instruksi user 2026-10-09: "aku tuh bikin stock pinjaman pada stock entry
SE-MR-261009001, karna di coldstorage kosong stoknya. jadi aku ingin kamu
memasukan balance seluruh gudang yang stock ke erpnext baru pada jam 23:00
di 30 september 2026."

Arti implementasi (scope: company PT. JUARA ROTI INDONESIA):
  untuk SETIAP (gudang, item) yang di LAMA punya saldo @2026-09-30 23:00,
  pastikan BARU punya nilai yang sama di titik waktu itu. Posisi yang di
  BARU masih kosong (0) -> diisi lewat 1 Stock Reconciliation "Opening
  Stock" per gudang, posting 2026-09-30 23:00:00.
  RECO = set ABSOLUT pada timestamp-nya: dokumen koreksi yang sudah ada
  (23:30/23:35, Oct-1/2) dan loan SE-MR-261009001 (23:59:59) TIDAK
  berubah nilainya; hanya jendela sebelum dokumen-dokumen itu yang jadi
  benar. Posisi yang sudah ada angka beda (audit 2026-10-08 "buku vs
  opname", mis. PEL260087) SENGAJA tidak disentuh — menunggu keputusan.

Fase:
  --plan      (default) hitung posisi kosong, tulis fill_plan_result.json,
              cetak ringkasan detail (dry-run; tidak menulis ke situs).
  --execute   buat gudang/item yang belum ada, pasang RECO per gudang,
              lalu verifikasi ulang @23:00 + poll Repost Item Valuation.
  --report    tulis pos_sync/Laporan_Fill_Saldo_Sep30_2300.xlsx.
  --refresh-lama  tarik ulang SLE LAMA (abaikan cache 12 jam).

Env: /tmp/eresto_mig.env (kunci LAMA) + /tmp/eresto_prod.env (kunci BARU).
Idempoten: tiap run menghitung ulang posisi kosong; yang sudah terisi
dilewati (tidak ada RECO duplikat).
"""
import argparse
import json
import os
import sys
import time
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import Client, load_env  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
DUMP = os.path.join(HERE, "stock_sep30_dump")
LIVE_CACHE = os.path.join(DUMP, "sle_lama_live.json")
BINS_CACHE = os.path.join(DUMP, "lama_bins_fill.json")
PLAN_JSON = os.path.join(DUMP, "fill_plan_result.json")
DOCS_JSON = os.path.join(DUMP, "fill_docs.json")
REPORT = os.path.join(HERE, "Laporan_Fill_Saldo_Sep30_2300.xlsx")
OLD_BASE = "https://rotiropi.j.frappe.cloud"
JURI = "PT. JUARA ROTI INDONESIA"
POST_DATE = "2026-09-30"
POST_TIME = "23:00:00"
EXPENSE_ACC = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"
TOL_REL = 1e-7

# gudang LAMA (ber-stok) -> gudang BARU  (instruksi user: seluruh gudang)
# CATATAN 2026-10-09: 3 gudang testing DIHAPUS atas perintah user
# ("stock di web lama cuma testing aja") — Mini Outlet tetap ada.
WH_MAP = {
    "Gudang Bahan Baku - ROPI": "Gudang Bahan Baku - JURI",
    "Gudang Barang Jadi - ROPI": "Gudang Barang Jadi - JURI",
    "Gudang Jakarta - ROPI": "Gudang Jakarta - JURI",
    "Gudang Produksi - ROPI": "Gudang Produksi - JURI",
    "Work In Progress - ROPI": "Work In Progress - JURI",
    "Gudang GA - ROPI": "Gudang GA - JURI",
    "Gudang RnD - ROPI": "Gudang R&D - JURI",
    "Gudang Outlet - ROPI": "Gudang Outlet - JURI",
    "Gudang Peralatan - ROPI": "Gudang Peralatan - JURI",
    "Gudang Vendor - ROPI": "Gudang Vendor - JURI",
    "Mini Outlet - ROPI": "Mini Outlet - JURI",
}

# gudang BARU yang dibuat kalau belum ada (nama, akun persediaan).
WH_CREATE = {
    # nama, parent, akun persediaan (None = ikut default)
    "Mini Outlet - JURI": ("Mini Outlet", "All Warehouses - JURI", None),
}

# remap kode bentrok antar-site (lihat migrate_outlet_so_dn_to_juri.py)
REMAP = {"BB260057": "BB26001", "BB260058": "BB26008", "BB260059": "BB26009"}

# posisi yang SENGAJA dilewati (menunggu keputusan audit 2026-10-08):
#   BB260021   : UOM Pcs (LAMA) vs Pack (BARU) — bukan satuan yang sama
#   BHP260004  : non-stock di BARU
# PEL260087 TIDAK di-skip: posisinya kosong @23:00 di BARU, jadi diisi
# dengan angka buku LAMA (238.100/27.850); koreksi 23:30 (201.000/34.000)
# tetap dan tidak diubah — keputusan audit tetap milik user.
SKIP_ITEMS = {"BB260021", "BHP260004"}

GROUP_MAP = {"Produk Jadi": "Produk Jadi Pabrik"}
UOM_NORM = {"Kg": "kg"}


def log(m):
    print(m, flush=True)


def tosec(t):
    s = str(t or "0").split(".")
    p = s[0].split(":")
    while len(p) < 3:
        p.append("0")
    try:
        return int(float(p[0])) * 3600 + int(float(p[1])) * 60 + float(p[2])
    except Exception:
        return -1


CUT23 = (POST_DATE, tosec(POST_TIME))


def fetch(dt, fields, filters, order, c, page=500):
    out, start = [], 0
    while True:
        st, d = c.get("/api/resource/" + dt, {
            "fields": json.dumps(fields), "filters": json.dumps(filters),
            "order_by": order, "limit_page_length": page,
            "limit_start": start})
        rows = d.get("data", []) if st == 200 else []
        if st != 200:
            raise SystemExit("GET %s %s gagal HTTP %s %s"
                             % (dt, c.base, st, str(d)[:200]))
        out += rows
        start += len(rows)
        if len(rows) < page:
            break
    return out


SLE_F = ["name", "warehouse", "item_code", "posting_date", "posting_time",
         "actual_qty", "qty_after_transaction", "voucher_no"]


def fetch_sle(c, company, upto=None, cache=None):
    filt = [["company", "=", company], ["is_cancelled", "=", 0]]
    if upto:
        filt.append(["posting_date", "<=", upto])
    if cache and os.path.exists(cache):
        age = time.time() - os.path.getmtime(cache)
        if age < 12 * 3600 and "--refresh-lama" not in sys.argv:
            log("  [cache] %s (%.1f jam)" % (os.path.basename(cache),
                                             age / 3600))
            return json.load(open(cache))
    rows = fetch("Stock Ledger Entry", SLE_F, filt,
                 "posting_date asc, posting_time asc, name asc", c)
    if cache:
        json.dump(rows, open(cache, "w"), default=str)
    return rows


def fetch_items(c):
    return {i["name"]: i for i in fetch(
        "Item", ["name", "item_name", "stock_uom", "is_stock_item",
                 "disabled", "item_group", "has_batch_no", "has_serial_no"],
        [], "name asc", c)}


def build_idx(rows):
    idx = defaultdict(list)
    for r in rows:
        idx[(r["warehouse"], r["item_code"])].append(
            (str(r["posting_date"])[:10], tosec(r["posting_time"]), r["name"],
             float(r["qty_after_transaction"] or 0), r["voucher_no"]))
    for k in idx:
        idx[k].sort()
    return idx


def last_at(idx, key, cut):
    best = None
    for e in idx.get(key, []):
        if (e[0], e[1]) <= cut:
            best = e
    return best


def rows_after(idx, key):
    return [e for e in idx.get(key, []) if (e[0], e[1]) > CUT23]


# ---------------------------------------------------------------- plan
def build_plan(mig, prod, refresh_bins=False):
    old = Client(OLD_BASE, mig["ERPNEXT_OLD_CLOUD_API_KEY"], "LAMA")
    new = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"], "BARU")
    log("  [lama] SLE <= %s ..." % POST_DATE)
    lama_rows = fetch_sle(old, JURI, POST_DATE, LIVE_CACHE)
    log("  [baru] SLE semua tanggal ...")
    baru_rows = fetch_sle(new, JURI, None)
    log("  [baru] %d baris" % len(baru_rows))
    idxL = build_idx(lama_rows)
    idxB_all = build_idx(baru_rows)
    idxB30 = build_idx([r for r in baru_rows
                        if str(r["posting_date"])[:10] <= POST_DATE])
    items_l = fetch_items(old)
    items_b = fetch_items(new)

    # batch map utk item ber-batch yang muncul di idxL.
    # Ambil batch dari Serial and Batch Bundle pada baris SLE terakhir
    # <= cutoff (bukan sembarang batch) supaya batch-nya benar.
    batches_l = {}
    batch_codes = sorted({c for c, x in items_l.items() if x.get("has_batch_no")}
                         & {k[1] for k in idxL})
    for code in batch_codes:
        st, d = old.get("/api/resource/Stock Ledger Entry", {
            "filters": json.dumps([["item_code", "=", code],
                                   ["posting_date", "<=", POST_DATE],
                                   ["is_cancelled", "=", 0],
                                   ["serial_and_batch_bundle", "is", "set"]]),
            "fields": json.dumps(["serial_and_batch_bundle"]),
            "order_by": "posting_date desc, posting_time desc",
            "limit_page_length": 1})
        bundle = (d.get("data") or [{}])[0].get("serial_and_batch_bundle") \
            if st == 200 else None
        if bundle:
            st2, d2 = old.get("/api/resource/Serial and Batch Bundle/" + bundle)
            if st2 == 200:
                ents = [e for e in d2["data"].get("entries", [])
                        if float(e.get("qty") or 0) != 0]
                if ents:
                    batches_l[code] = ents[-1]["batch_no"]
        if code not in batches_l:
            st, d = old.get("/api/resource/Batch", {
                "filters": json.dumps([["item", "=", code]]),
                "fields": json.dumps(["name"]), "limit_page_length": 1})
            if st == 200 and d.get("data"):
                batches_l[code] = d["data"][0]["name"]

    # bins LAMA utk valuation rate
    if refresh_bins or not os.path.exists(BINS_CACHE):
        bins = []
        wl = list(WH_MAP.keys())
        for i in range(0, len(wl), 10):
            bins += fetch("Bin", ["item_code", "warehouse", "actual_qty",
                                  "valuation_rate"],
                          [["warehouse", "in", wl[i:i + 10]]], "name asc",
                          old)
        json.dump(bins, open(BINS_CACHE, "w"), default=str)
    else:
        bins = json.load(open(BINS_CACHE))
        log("  [cache] lama_bins_fill.json")
    rate_l = {(b["warehouse"], b["item_code"]):
              float(b["valuation_rate"] or 0) for b in bins}
    # fallback: rate per item dari gudang mana pun yang > 0
    rate_any = {}
    for b in bins:
        v = float(b["valuation_rate"] or 0)
        if v > 0:
            rate_any.setdefault(b["item_code"], []).append(v)

    inserts, ok, skipped = [], [], []
    total = 0
    for wl, wb in WH_MAP.items():
        for itl in sorted({k[1] for k in idxL if k[0] == wl}):
            eL = last_at(idxL, (wl, itl), CUT23)
            if not eL or abs(eL[3]) < 1e-6:
                continue
            total += 1
            L = eL[3]
            itb = REMAP.get(itl, itl)
            src = items_l.get(itl) or {}
            dst = items_b.get(itb) or {}
            base = {"wh_lama": wl, "wh_baru": wb, "item_lama": itl,
                    "item_baru": itb, "item_name": src.get("item_name"),
                    "item_group": src.get("item_group"),
                    "uom_l": src.get("stock_uom"), "L": L}
            if L < 0:
                base["reason"] = "saldo LAMA negatif (%.4f)" % L
                skipped.append(base)
                continue
            if itl in SKIP_ITEMS or itb in SKIP_ITEMS:
                base["reason"] = "menunggu keputusan audit 2026-10-08"
                skipped.append(base)
                continue
            ua = (src.get("stock_uom") or "").lower()
            ub = (dst.get("stock_uom") or "").lower()
            if dst and ua != ub:
                base["reason"] = ("konflik UOM: LAMA=%s BARU=%s"
                                  % (src.get("stock_uom"),
                                     dst.get("stock_uom")))
                skipped.append(base)
                continue
            if dst and not dst.get("is_stock_item"):
                base["reason"] = "item non-stock di BARU"
                skipped.append(base)
                continue
            eB = last_at(idxB30, (wb, itb), CUT23)
            B0 = eB[3] if eB else 0.0
            base["B0"] = B0
            later = rows_after(idxB_all, (wb, itb))
            base["later_docs"] = sorted({e[4] for e in later})[:5]
            base["has_later"] = bool(later)
            tol = max(1e-4, abs(L) * TOL_REL)
            if abs(B0 - L) <= tol:
                ok.append(base)
                continue
            if abs(B0) > tol:
                base["reason"] = ("angka beda @23:00 (BARU=%.4f vs LAMA=%.4f)"
                                  " — menunggu keputusan audit" % (B0, L))
                skipped.append(base)
                continue
            # INSERT (hanya posisi benar-benar kosong)
            assert abs(B0) <= tol, "BUG: insert utk B0=%s" % B0
            base["need_item"] = not bool(dst)
            raw_uom = (dst.get("stock_uom") or src.get("stock_uom")
                       or "Pcs")
            base["uom"] = UOM_NORM.get(raw_uom, raw_uom)
            rate = float(rate_l.get((wl, itl)) or 0)
            if rate <= 0:
                cand = rate_any.get(itl) or []
                rate = cand[0] if cand else 0.0
                if rate > 0:
                    base["rate_fallback"] = True
            base["rate"] = rate
            if dst.get("has_batch_no"):
                base["batch"] = batches_l.get(itl)
                if not base["batch"]:
                    base["reason"] = "item ber-batch tapi batch LAMA tidak ada"
                    skipped.append(base)
                    continue
            inserts.append(base)
    return {"old": old, "new": new, "inserts": inserts, "ok": ok,
            "skipped": skipped, "total": total}


def print_plan(plan):
    ins, ok, sk = plan["inserts"], plan["ok"], plan["skipped"]
    log("")
    log("=" * 72)
    log("=== RINGKASAN PLAN (isi saldo LAMA @%s %s -> BARU)" % (POST_DATE,
                                                                POST_TIME))
    log("  posisi LAMA ber-stok @23:00 : %d" % plan["total"])
    log("  sudah sama di BARU          : %d" % len(ok))
    log("  AKAN DIISI (insert)         : %d" % len(ins))
    log("  SKIP (pending/keputusan)    : %d" % len(sk))
    by = defaultdict(lambda: [0, 0.0, 0])
    for f in ins:
        by[f["wh_baru"]][0] += 1
        by[f["wh_baru"]][1] += abs(f["L"])
        if f["need_item"]:
            by[f["wh_baru"]][2] += 1
    log("")
    log("  %-42s %4s %16s %10s" % ("gudang BARU", "n", "sum|qty|", "item br"))
    for w in sorted(by, key=lambda x: str(x)):
        c = by[w]
        log("  %-42s %4d %16.2f %10d" % (w, c[0], c[1], c[2]))
    need = sorted({f["item_baru"] for f in ins if f["need_item"]})
    log("")
    log("  item perlu dibuat: %d" % len(need))
    for x in need:
        log("     %s" % x)
    log("")
    log("=== SKIP (menunggu keputusan/tidak diisi) ===")
    for s in sk:
        log("  %-38s %-16s L=%-14.4f | %s"
            % (s["wh_baru"], s["item_baru"], s["L"], s["reason"]))
    log("")
    log("=== INSERT detail ===")
    for f in sorted(ins, key=lambda x: (str(x["wh_baru"]), str(x["item_baru"]))):
        log("  %-40s %-18s qty=%-15.4f uom=%-6s rate=%-14.6f new_item=%-5s later=%s"
            % (f["wh_baru"], f["item_baru"], f["L"], f["uom"], f["rate"],
               f["need_item"], ",".join(f["later_docs"]) if f["later_docs"] else "-"))
    log("")
    log("OK")


# ---------------------------------------------------------------- execute
GROUP_ACC = {}


def template_accounts(c):
    global GROUP_ACC
    if GROUP_ACC:
        return GROUP_ACC
    for code, grp in (("PEL260006", "Perlengkapan"),
                      ("BHP260027", "Barang Habis Pakai"),
                      ("ATK260044", "ATK"),
                      ("PJ260010", "Produk Jadi Pabrik")):
        st, d = c.get("/api/resource/Item/" + code)
        if st != 200:
            continue
        for x in d["data"].get("item_defaults", []):
            if x.get("company") == JURI and x.get("default_inventory_account"):
                GROUP_ACC[grp] = x["default_inventory_account"]
                break
    return GROUP_ACC


def ensure_warehouse(c, wb):
    st, d = c.get("/api/resource/Warehouse/" + wb.replace(" ", "%20"))
    if st == 200:
        return False
    name, parent, acc = WH_CREATE[wb]
    payload = {"doctype": "Warehouse", "warehouse_name": name,
               "company": JURI, "is_group": 0,
               "parent_warehouse": parent}
    if acc:
        payload["account"] = acc
    st, d = c.post("Warehouse", payload)
    if st != 200:
        raise SystemExit("GAGAL buat warehouse %s: HTTP %s %s"
                         % (wb, st, str(d)[:300]))
    log("  [wh] dibuat: %s" % d["data"]["name"])
    return True


def ensure_item(c, f, created):
    items_b = created.setdefault("items_b", {})
    if f["item_baru"] in items_b:
        return
    grp = GROUP_MAP.get(f.get("item_group") or "", f.get("item_group")
                        or "Perlengkapan")
    acc = template_accounts(c).get(grp) or "1145.000 - Finished Good - JURI"
    raw = f.get("uom_l") or "Pcs"
    uom = UOM_NORM.get(raw, raw)
    payload = {
        "doctype": "Item", "item_code": f["item_baru"],
        "item_name": f.get("item_name"), "item_group": grp,
        "stock_uom": uom, "is_stock_item": 1,
        "item_defaults": [{"company": JURI,
                           "default_inventory_account": acc}]}
    st, d = c.post("Item", payload)
    if st != 200:
        raise SystemExit("GAGAL buat item %s: HTTP %s %s"
                         % (f["item_baru"], st, str(d)[:300]))
    final = d["data"]["name"]
    if final != f["item_baru"]:
        st2, d2 = c.rename("Item", final, f["item_baru"])
        if st2 != 200:
            raise SystemExit("GAGAL rename item %s -> %s: HTTP %s %s"
                             % (final, f["item_baru"], st2, str(d2)[:200]))
    items_b[f["item_baru"]] = True
    created["created_items"].append(f["item_baru"])
    log("  [item] dibuat: %-18s %-36s %s (%s)"
        % (f["item_baru"], f.get("item_name") or "", uom, acc))


def ensure_item_default(c, itb, cache):
    """pastikan ada item default inventory account utk JURI."""
    if itb in cache:
        return
    cache[itb] = True
    st, d = c.get("/api/resource/Item/" + itb)
    if st != 200:
        raise SystemExit("item %s tidak ada" % itb)
    dd = d["data"]
    defs = dd.get("item_defaults") or []
    has = [x for x in defs if x.get("company") == JURI]
    if has and has[0].get("default_inventory_account"):
        return
    grp = dd.get("item_group")
    acc = template_accounts(c).get(grp) or "1145.000 - Finished Good - JURI"
    if has:
        c.post("/api/method/frappe.client.set_value", {
            "doctype": "Item Default", "name": has[0]["name"],
            "fieldname": "default_inventory_account", "value": acc})
        log("  [item] default acc diisi: %s -> %s" % (itb, acc))
    else:
        defs.append({"company": JURI, "default_inventory_account": acc})
        c.put("Item", itb, {"item_defaults": defs})
        log("  [item] default acc ditambah: %s -> %s" % (itb, acc))


def execute(plan):
    new = plan["new"]
    ins = plan["inserts"]
    log("")
    log("=== pastikan setting serial/batch (parity LAMA) ===")
    st, d = new.get("/api/method/frappe.client.get_value", {
        "doctype": "Stock Settings",
        "fieldname": "enable_serial_and_batch_no_for_item"})
    val = (d.get("message") or {}).get("enable_serial_and_batch_no_for_item")
    if val != 1:
        st2, d2 = new.put("Stock Settings", "Stock Settings",
                          {"enable_serial_and_batch_no_for_item": 1})
        log("  [setting] enable_serial_and_batch_no_for_item 0 -> 1 (HTTP %s)"
            % st2)
    else:
        log("  [setting] enable_serial_and_batch_no_for_item sudah 1")

    log("")
    log("=== pastikan gudang & item ===")
    for wb in sorted({f["wh_baru"] for f in ins}):
        if wb in WH_CREATE:
            ensure_warehouse(new, wb)
        else:
            st, d = new.get("/api/resource/Warehouse/"
                            + wb.replace(" ", "%20"))
            if st != 200:
                raise SystemExit("warehouse %s tidak ada di BARU!" % wb)
    created = {"items_b": {}, "created_items": []}
    for f in ins:
        if f["need_item"]:
            ensure_item(new, f, created)
    cache = {}
    for f in ins:
        ensure_item_default(new, f["item_baru"], cache)
    for f in ins:
        b = f.get("batch")
        if not b:
            continue
        st, d = new.get("/api/resource/Batch/" + b)
        if st == 200:
            continue
        st, d = new.post("Batch", {"doctype": "Batch", "batch_id": b,
                                   "item": f["item_baru"]})
        if st != 200:
            raise SystemExit("GAGAL buat batch %s: HTTP %s %s"
                             % (b, st, str(d)[:200]))
        log("  [batch] dibuat: %s (%s)" % (b, f["item_baru"]))

    log("")
    log("=== pasang RECO per gudang @%s %s ===" % (POST_DATE, POST_TIME))
    by = defaultdict(list)
    for f in ins:
        by[f["wh_baru"]].append(f)
    # status terkini @23:00 (utk idempoten: yang sudah terisi dilewati)
    rows_now = fetch_sle(new, JURI, None)
    idx_now = build_idx(rows_now)
    fixed = {}

    def cur(f):
        k = (f["wh_baru"], f["item_baru"])
        if k in fixed:
            return fixed[k]
        e = last_at(idx_now, k, CUT23)
        return e[3] if e else 0.0

    docs, n_fail, n_fill = {}, 0, 0
    for wb in sorted(by, key=lambda x: str(x)):
        need = [f for f in by[wb]
                if abs(cur(f) - f["L"]) > max(1e-4, abs(f["L"]) * TOL_REL)]
        if not need:
            log("  [SKIP] %-42s sudah terisi" % wb)
            docs[wb] = "(sudah terisi)"
            continue
        reco_items = []
        for f in need:
            row = {"item_code": f["item_baru"], "warehouse": wb,
                   "qty": f["L"], "uom": f["uom"],
                   "valuation_rate": f["rate"]}
            if f.get("batch"):
                row["batch_no"] = f["batch"]
                row["use_serial_batch_fields"] = 1
            reco_items.append(row)
        payload = {
            "doctype": "Stock Reconciliation", "company": JURI,
            "purpose": "Opening Stock", "set_posting_time": 1,
            "posting_date": POST_DATE, "posting_time": POST_TIME,
            "set_warehouse": wb, "expense_account": EXPENSE_ACC,
            "cost_center": COST_CENTER,
            "items": reco_items,
            "docstatus": 1}
        st, d = new.post("Stock Reconciliation", payload)
        if st == 200:
            docs[wb] = d["data"]["name"]
            n_fill += len(need)
            for f in need:
                fixed[(wb, f["item_baru"])] = f["L"]
            log("  [OK] %-42s %s items=%d" % (wb, d["data"]["name"],
                                              len(need)))
        else:
            n_fail += 1
            log("  [FAIL] %-42s %s" % (wb, str(d)[:300]))
        json.dump({"docs": docs, "created_items": created["created_items"],
                   "n_ok": len([v for v in docs.values()
                                if v != "(sudah terisi)"]),
                   "n_fill": n_fill, "n_fail": n_fail},
                  open(DOCS_JSON, "w"), indent=1, default=str)
    json.dump({"docs": docs, "created_items": created["created_items"],
               "n_ok": len([v for v in docs.values()
                            if v != "(sudah terisi)"]),
               "n_fill": n_fill, "n_fail": n_fail},
              open(DOCS_JSON, "w"), indent=1, default=str)
    return docs, n_fail


def verify(plan):
    new = plan["new"]
    log("")
    log("=== verifikasi ulang @%s %s ===" % (POST_DATE, POST_TIME))
    rows = fetch_sle(new, JURI, None)
    idx = build_idx(rows)
    bad = []
    for f in plan["inserts"] + plan["ok"]:
        e = last_at(idx, (f["wh_baru"], f["item_baru"]), CUT23)
        got = e[3] if e else None
        tol = max(1e-4, abs(f["L"]) * TOL_REL)
        if got is None or abs(got - f["L"]) > tol:
            bad.append((f, got))
    if bad:
        log("  [FAIL] %d posisi tidak sesuai:" % len(bad))
        for f, got in bad[:30]:
            log("     %-40s %-18s mau=%.4f dapat=%s"
                % (f["wh_baru"], f["item_baru"], f["L"], got))
    else:
        log("  OK: %d posisi insert + %d posisi lama semua = LAMA @23:00"
            % (len(plan["inserts"]), len(plan["ok"])))
    log("")
    log("=== poll Repost Item Valuation ===")
    for i in range(1, 41):
        st, d = new.get("/api/resource/Repost Item Valuation", {
            "filters": json.dumps([["status", "in",
                                    ["Queued", "In Progress"]]]),
            "fields": json.dumps(["name"]), "limit_page_length": 1})
        n = len(d.get("data", [])) if st == 200 else -1
        if n == 0:
            log("  selesai.")
            break
        log("  ... masih ada antrean (%ds)" % (i * 15))
        time.sleep(15)
    return bad


def run_report():
    import openpyxl
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter
    plan = json.load(open(PLAN_JSON))
    docs = json.load(open(DOCS_JSON)) if os.path.exists(DOCS_JSON) else {}
    wb = openpyxl.Workbook()
    head_fill = PatternFill("solid", fgColor="D9EAF7")
    bold = Font(bold=True)

    def sheet(name, cols, rows, widths):
        ws = wb.create_sheet(name[:31])
        ws.append(cols)
        for c in range(1, len(cols) + 1):
            cell = ws.cell(row=1, column=c)
            cell.fill = head_fill
            cell.font = bold
            cell.alignment = Alignment(horizontal="center")
        for r in rows:
            ws.append(r)
        ws.freeze_panes = "A2"
        for i, w in enumerate(widths, 1):
            ws.column_dimensions[get_column_letter(i)].width = w

    ws = wb.active
    ws.title = "Ringkasan"
    ws.append(["Laporan", "Isi saldo 30 Sep 2026 23:00 (LAMA -> BARU, JURI)"])
    ws.append(["Instruksi", "user 2026-10-09 — balance seluruh gudang "
                            "yang stock @23:00 (stock pinjaman "
                            "SE-MR-261009001 tidak diubah)"])
    ws.append(["Metode", "RECO Opening Stock @2026-09-30 23:00:00 per gudang "
                          "(set absolut; dokumen 23:30+ tetap)"])
    ws.append(["", ""])
    ws.append(["Total posisi LAMA ber-stok @23:00", plan["total"]])
    ws.append(["Sudah sama (skip)", len(plan["ok"])])
    ws.append(["Diisi (insert)", len(plan["inserts"])])
    ws.append(["Tidak diisi (pending audit)", len(plan["skipped"])])
    ws.append(["RECO dibuat", docs.get("n_ok", 0)])
    ws.append(["Item baru dibuat", len(docs.get("created_items", []))])
    ws.append(["", ""])
    ws.append(["RECO per gudang:", ""])
    for w, n in sorted(docs.get("docs", {}).items()):
        ws.append([w, n])
    ws.freeze_panes = "A2"
    ws.column_dimensions["A"].width = 46
    ws.column_dimensions["B"].width = 64

    cols = ["Wh BARU", "Item", "Nama", "Qty @23:00", "UOM", "Rate",
            "Item Baru?", "Dokumen >23:00", "RECO"]
    widths = [34, 18, 40, 14, 8, 16, 12, 26, 26]
    dm = docs.get("docs", {})
    sheet("Insert", cols,
          [[f["wh_baru"], f["item_baru"], f.get("item_name") or "", f["L"],
            f["uom"], f["rate"], "YA" if f["need_item"] else "",
            ",".join(f["later_docs"]) or "", dm.get(f["wh_baru"], "")]
           for f in plan["inserts"]], widths)
    sheet("Sudah_Sama", cols,
          [[f["wh_baru"], f["item_baru"], f.get("item_name") or "", f["L"],
            "", "", "", "", ""] for f in plan["ok"]], widths)
    sheet("Pending_Audit", ["Wh BARU", "Item", "Nama", "LAMA @23:00",
                            "BARU @23:00", "Alasan"],
          [[f["wh_baru"], f["item_baru"], f.get("item_name") or "", f["L"],
            f.get("B0", ""), f["reason"]] for f in plan["skipped"]],
          [34, 18, 40, 16, 16, 70])
    wb.save(REPORT)
    log("Laporan ditulis: %s" % REPORT)
    log("OK")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--refresh-lama", action="store_true")
    ap.add_argument("--refresh-bins", action="store_true")
    a = ap.parse_args()
    mig = load_env("/tmp/eresto_mig.env")
    prod = load_env("/tmp/eresto_prod.env")
    use_plan_file = a.execute or a.report
    if use_plan_file:
        if not os.path.exists(PLAN_JSON):
            raise SystemExit("plan belum ada — jalankan --plan dulu")
        plan = json.load(open(PLAN_JSON))
        plan["new"] = Client(prod["ERPNEXT_URL"], prod["ERPNEXT_API_KEY"],
                             "BARU")
    else:
        log("=" * 72)
        log("FASE PLAN (dry-run; tidak menulis ke situs)")
        plan = build_plan(mig, prod, refresh_bins=a.refresh_bins)
        json.dump({k: v for k, v in plan.items()
                   if k not in ("old", "new")}, open(PLAN_JSON, "w"),
                  indent=1, default=str)
        print_plan(plan)
        log("Plan ditulis: %s" % PLAN_JSON)
        return
    if a.execute:
        _, n_fail = execute(plan)
        verify(plan)
        if n_fail:
            raise SystemExit("ADA %d RECO GAGAL — cek log" % n_fail)
    if a.report:
        run_report()


if __name__ == "__main__":
    main()
