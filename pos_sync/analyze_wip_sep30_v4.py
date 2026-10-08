#!/usr/bin/env python3
"""READ-ONLY v4: bukti definitif akar WIP negatif + angka batch 30 Sep.

Komponen per item:
  M30/M41/M23  = aliran WIP batch 30 Sep (masuk, keluar 30Sep, keluar 1Okt)
  In7/Out7     = TFM/MFG 7 Okt yang dikecualikan dari replay
  Extras244    = kelebihan konsumsi MFG replay (new - old) utk 244 WO
  cek identitas: live - EOD7 == -In7 - Extras + MFG40
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import Ctx, jload  # noqa: E402
from prod_common import JURI  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "wip_audit")
WIP_O = "Work In Progress - ROPI"
WIP_N = "Work In Progress - JURI"
BATCH30 = {f"MFG-WO-2026-{n:05d}" for n in range(3867, 3931)}
OCT7RANGE = {f"MFG-WO-2026-{n:05d}" for n in range(4176, 4238)}

ctx = Ctx()
old, new = ctx.old, ctx.new


def jdump(n, o):
    with open(os.path.join(OUT, n), "w") as f:
        json.dump(o, f, indent=1, default=str)


def wip_sum_sle(rows, names=None, field="voucher_no"):
    """sum actual_qty per item utk baris SLE (opsional filter set nama)."""
    d = defaultdict(float)
    for r in rows:
        if names is not None and r.get(field) not in names:
            continue
        d[r["item_code"]] += float(r.get("actual_qty") or 0)
    return dict(d)


# ---- 1. daftar SE lama 7 Okt + SE baru (MFG & TFM)
oct7 = []
start = 0
while True:
    st, d = old.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", JURI], ["docstatus", "=", 1],
                               ["posting_date", "=", "2026-10-07"]]),
        "fields": json.dumps(["name", "purpose", "work_order"]),
        "limit_page_length": 500, "limit_start": start})
    rows = d.get("data", []) if st == 200 else []
    oct7 += rows
    if len(rows) < 500:
        break
    start += len(rows)
print(f"SE lama 7 Okt: {len(oct7)}")
jdump("oct7_old_se.json", oct7)

new_mfg = []
start = 0
while True:
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["purpose", "=", "Manufacture"]]),
        "fields": json.dumps(["name", "remarks", "work_order", "posting_date"]),
        "limit_page_length": 500, "limit_start": start})
    rows = d.get("data", []) if st == 200 else []
    new_mfg += rows
    if len(rows) < 500:
        break
    start += len(rows)
print(f"SE Manufacture site baru: {len(new_mfg)}")


def oldname_of(remarks):
    if not remarks or "ERESTO " not in remarks:
        return None
    s = remarks.split("ERESTO ", 1)[1].split(" |")[0].strip()
    return s.split()[0] if s else None


# ---- 2. set nama dokumen lama & baru
se_index = jload("se_index.json", [])  # [{"name","purpose","work_order",...}]
wo_set = set(jload("wos.json", {}))    # 244 WO dimigrasi

mfg244_old, mfg23_old, mfg40_old, mfg_other = set(), set(), set(), set()
tfm244_old, tfm62_old = set(), set()
for r in se_index:
    p, wo = r.get("purpose"), r.get("work_order")
    if p == "Manufacture":
        if wo in wo_set:
            mfg244_old.add(r["name"])
        elif wo in BATCH30:
            mfg23_old.add(r["name"])
        elif wo in OCT7RANGE:
            mfg40_old.add(r["name"])
        else:
            mfg_other.add(r["name"])
    elif p == "Material Transfer for Manufacture" and wo in wo_set:
        tfm244_old.add(r["name"])
for r in oct7:
    p, wo, n = r.get("purpose"), r.get("work_order"), r["name"]
    if p == "Manufacture":
        if wo in wo_set and n not in mfg244_old:
            mfg244_old.add(n)      # 22 H+1 batch 6 Okt yg tgl 7 Okt
        elif wo in OCT7RANGE:
            mfg40_old.add(n)
        elif wo in BATCH30:
            mfg23_old.add(n)
        else:
            mfg_other.add(n)
    elif p == "Material Transfer for Manufacture":
        tfm62_old.add(n)
print(f"OLD MFG: 244={len(mfg244_old)} 23supp={len(mfg23_old)} "
      f"40oct7={len(mfg40_old)} other={len(mfg_other)}")
print(f"OLD TFM: 244={len(tfm244_old)} | 7Okt={len(tfm62_old)}")

new_regen = {r["name"] for r in new_mfg
             if oldname_of(r.get("remarks")) not in mfg23_old}
new_supp = {r["name"] for r in new_mfg} - new_regen
print(f"NEW MFG: regen={len(new_regen)} support={len(new_supp)}")

# ---- 3. SLE
sle_old = json.load(open(os.path.join(OUT, "sle_wip_old.json")))
sle_new = json.load(open(os.path.join(OUT, "sle_wip_new.json")))
sle_new_se = [r for r in sle_new
              if r.get("voucher_type") != "Stock Reconciliation"]

ins_new = wip_sum_sle(sle_new_se, {r["name"] for r in new_mfg})  # placeholder
# ins = SE-MTFM; outs = SE-MFG (all production docs)
ins_new = wip_sum_sle(sle_new_se,
                      {n for n in {r.get("voucher_no") for r in sle_new_se}
                       if n.startswith("SE-MTFM")})
ins_new_pos = {c: v for c, v in ins_new.items() if v > 0}
outs_supp = wip_sum_sle(sle_new_se, new_supp)
outs_regen = wip_sum_sle(sle_new_se, new_regen)
outs_new = defaultdict(float)
for d in (outs_supp, outs_regen):
    for c, v in d.items():
        outs_new[c] += v

old_244 = wip_sum_sle(sle_old, mfg244_old)
old_23 = wip_sum_sle(sle_old, mfg23_old)
old_40 = wip_sum_sle(sle_old, mfg40_old)
old_tfm62 = wip_sum_sle(sle_old, tfm62_old)

v3 = json.load(open(os.path.join(OUT, "v3_data.json")))
M30 = {k: float(v) for k, v in v3["M30"].items()}
M41 = {k: float(v) for k, v in v3["M41"].items()}
M23 = {k: float(v) for k, v in v3["M23"].items()}
INS7 = {k: float(v) for k, v in v3["INS7"].items()}
OUTS7 = {k: float(v) for k, v in v3["OUTS7"].items()}

bal_old = json.load(open(os.path.join(OUT, "bal_old.json")))
bydate = bal_old["by_date"]
bins = {}
start = 0
while True:
    st, d = new.get("/api/resource/Bin", {
        "filters": json.dumps([["warehouse", "=", WIP_N]]),
        "fields": json.dumps(["item_code", "actual_qty"]),
        "limit_page_length": 500, "limit_start": start})
    rows = d.get("data", []) if st == 200 else []
    for r in rows:
        bins[r["item_code"]] = float(r["actual_qty"])
    if len(rows) < 500:
        break
    start += len(rows)

# saldo awal RECO-B dari wip_sep30
wd = jload("wip_sep30.json", {})

allc = sorted(set(list(M30) + list(bins) + [c for c in bydate]))
print()
hdr = (f"{'item':<10}{'EOD30':>12}{'EOD7':>12}{'live':>12}"
       f"{'M30':>12}{'M41':>11}{'M23':>12}"
       f"{'In7':>11}{'Out7':>11}{'Extras244':>12}{'MFG40':>11}{'cek':>6}")
print(hdr)
print("-" * len(hdr))
rows_out = []
for c in allc:
    e30 = bydate.get(c, {}).get("2026-09-30")
    e7 = bydate.get(c, {}).get("2026-10-07")
    lv = bins.get(c)
    extras = outs_regen.get(c, 0) - old_244.get(c, 0)   # neg = over-consume
    m40 = old_40.get(c, 0)
    # identitas: live - EOD7 == -In7 - Extras + MFG40
    #   Extras = new - old (positif = konsumsi baru lbh besar)
    if lv is None or e7 is None:
        cek = "-"
    else:
        pred = e7 - INS7.get(c, 0) - extras + m40
        cek = "OK" if abs(lv - pred) < 0.02 else f"{lv-pred:+.2f}"
    def f(v):
        return f"{v:,.2f}" if v is not None else "-"
    print(f"{c:<10}{f(e30):>12}{f(e7):>12}{f(lv):>12}"
          f"{M30.get(c,0):>12,.2f}{M41.get(c,0):>11,.2f}{M23.get(c,0):>12,.2f}"
          f"{INS7.get(c,0):>11,.2f}{OUTS7.get(c,0):>11,.2f}"
          f"{extras:>12,.2f}{m40:>11,.2f}{cek:>6}")
    rows_out.append({"item": c, "EOD30": e30, "EOD7": e7, "live": lv,
                     "M30": M30.get(c, 0), "M41": M41.get(c, 0),
                     "M23": M23.get(c, 0), "In7": INS7.get(c, 0),
                     "Out7": OUTS7.get(c, 0), "Extras244": extras,
                     "MFG40": m40, "cek": cek})

jdump("v4_final.json", rows_out)

# total
def tot(d):
    return sum(d.values()) if isinstance(d, dict) else sum(d)
print()
print(f"TOTAL M30={tot(M30):,.2f} M41={tot(M41):,.2f} M23={tot(M23):,.2f} "
      f"In7={tot(INS7):,.2f} Out7={tot(OUTS7):,.2f} "
      f"Extras244={tot(outs_regen)-tot(old_244):,.2f} MFG40={tot(old_40):,.2f}")

# kontrol support23
supdiff = {c: outs_supp.get(c, 0) - old_23.get(c, 0)
           for c in set(list(outs_supp) + list(old_23))}
bad = {c: v for c, v in supdiff.items() if abs(v) > 0.02}
print(f"kontrol support23 (new-old, harus ~0): {len(bad)} item beda {bad if bad else ''}")

# hitung dokumen MFG dgn extras utk item contoh
for target in ("BB260011", "BB260002", "BB260007"):
    new_by_doc = defaultdict(float)
    for r in sle_new_se:
        if r.get("voucher_no") in new_regen:
            new_by_doc[r["voucher_no"]] += float(r.get("actual_qty") or 0)
    old_by_doc = defaultdict(float)
    for r in sle_old:
        if r.get("voucher_no") in mfg244_old:
            old_by_doc[r["voucher_no"]] += 0  # placeholder
    # doc-level extras perlu pasangan nama; pakai remarks map baru
    name_map = {r["name"]: oldname_of(r.get("remarks")) for r in new_mfg}
    cnt, tot_ex = 0, 0.0
    for ndoc in new_regen:
        ondoc = name_map.get(ndoc)
        nv = new_by_doc.get(ndoc, 0)
        ov = 0.0
        for r in sle_old:
            if r.get("voucher_no") == ondoc:
                ov += float(r.get("actual_qty") or 0)
        ex = nv - ov
        if abs(ex) > 0.005:
            cnt += 1
            tot_ex += ex
    print(f"   {target}: dokumen MFG dgn selisih (doc-level, semua item) = "
          f"{cnt} dari {len(new_regen)}, total {tot_ex:,.2f}")
print("selesai.")
