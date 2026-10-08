#!/usr/bin/env python3
"""READ-ONLY v5: verifikasi final.

1. 23 MFG support (batch 30 Sep finish 1 Okt) sudah konsumsi WIP di site baru?
2. Out-supp per item == M23 per item?
3. Handover MT 1 Okt utk 23 MR gagal: apakah ikut ter-replay?
4. Jam MFG 23 (1 Okt) & 41 (30 Sep) di site lama.
5. Dampak kalau M23 dikurangi lagi dari WIP site baru.
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
WIP_N = "Work In Progress - JURI"
BATCH30 = {f"MFG-WO-2026-{n:05d}" for n in range(3867, 3931)}
FAIL_WOS = ({f"MFG-WO-2026-{n:05d}" for n in range(3867, 3880)}
            | {f"MFG-WO-2026-{n:05d}" for n in range(3883, 3893)})
FAIL_MRS = ({f"MAT-MR-2026-{n:05d}" for n in range(788, 803)}
            | {f"MAT-MR-2026-{n:05d}" for n in range(805, 809)}
            | {f"MAT-MR-2026-{n:05d}" for n in range(811, 815)})

ctx = Ctx()
old, new = ctx.old, ctx.new
v3 = json.load(open(os.path.join(OUT, "v3_data.json")))
M23 = {k: float(v) for k, v in v3["M23"].items()}
sle_new = json.load(open(os.path.join(OUT, "sle_wip_new.json")))

# ------------------------------------------------ 1. MFG site baru: regen/supp
mfg = []
start = 0
while True:
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["purpose", "=", "Manufacture"]]),
        "fields": json.dumps(["name", "remarks", "posting_date",
                              "posting_time", "docstatus"]),
        "limit_page_length": 500, "limit_start": start})
    rows = d.get("data", []) if st == 200 else []
    mfg += rows
    if len(rows) < 500:
        break
    start += len(rows)


def oldname_of(r):
    rm = r.get("remarks") or ""
    if "ERESTO " not in rm:
        return None
    s = rm.split("ERESTO ", 1)[1].split(" |")[0].strip()
    return s.split()[0] if s else None


m23_new_names = {}   # new name -> old name (23 support)
for r in mfg:
    on = oldname_of(r)
    if on and on.startswith("MAT-STE-2026-08"):
        # cek apakah dok lama ini MFG batch30 1 Okt
        pass
# ambil daftar nama baru dari se_index MFG batch30 (23 dok)
se_index = jload("se_index.json")
m23_old = sorted({r["name"] for r in se_index
                  if r["purpose"] == "Manufacture"
                  and r.get("work_order") in BATCH30
                  and r["posting_date"] == "2026-10-01"})
m23_old_set = set(m23_old)
print(f"MFG lama batch30 tgl 1 Okt (23supp): {len(m23_old)}")
for r in mfg:
    on = oldname_of(r)
    if on in m23_old_set:
        m23_new_names[r["name"]] = on
print(f"ada di site baru: {len(m23_new_names)}")
jdump = None
sup_new = set(m23_new_names)

# ------------------------------------------ 2. per-item B / in / out identity
opening, ins, outs_sup, outs_regen = (defaultdict(float), defaultdict(float),
                                      defaultdict(float), defaultdict(float))
for r in sle_new:
    q = float(r.get("actual_qty") or 0)
    vn = r.get("voucher_no") or ""
    if r.get("voucher_type") == "Stock Reconciliation":
        opening[r["item_code"]] += q
    elif vn.startswith("SE-MTFM"):
        ins[r["item_code"]] += q
    elif vn in sup_new:
        outs_sup[r["item_code"]] += q
    elif vn.startswith("SE-MFG"):
        outs_regen[r["item_code"]] += q

# B otoritatif: isi RECO-JURI-261007002 (cache SLE tak memuat baris RECO)
B = defaultdict(float)
st, d = new.get("/api/resource/Stock Reconciliation/RECO-JURI-261007002")
if st == 200:
    for x in d["data"].get("items", []):
        B[x["item_code"]] += float(x.get("qty") or 0)
print(f"RECO-B: {len(B)} item, total {sum(B.values()):,.2f}")

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

print()
hdr = (f"{'item':<10}{'B(RECO)':>12}{'inTFM':>11}{'outRegen':>11}"
       f"{'outSupp':>11}{'B+in-out':>12}{'bin':>12}{'supp==M23':>10}")
print(hdr)
badid, badm = 0, 0
rows_out = []
items = sorted(set(list(B) + list(bins)))
for c in items:
    o = B.get(c, 0)
    i = ins.get(c, 0)
    r1 = outs_regen.get(c, 0)
    r2 = outs_sup.get(c, 0)
    calc = o + i + r1 + r2
    b = bins.get(c, 0)
    ok1 = "OK" if abs(calc - b) < 0.02 else f"{calc-b:+.2f}"
    m = M23.get(c, 0)
    ok2 = "OK" if abs(-r2 - m) < 0.02 else f"{-r2:+,.2f} vs {m:,.2f}"
    if ok1 != "OK":
        badid += 1
    if ok2 != "OK":
        badm += 1
    print(f"{c:<10}{o:>12,.2f}{i:>11,.2f}{r1:>11,.2f}{r2:>11,.2f}"
          f"{calc:>12,.2f}{b:>12,.2f}{ok1:>10}")
    rows_out.append({"item": c, "B": o, "inTFM": i, "outRegen": r1,
                     "outSupp": r2, "bin": b, "M23": m,
                     "bin_minus_M23": b - m})
print(f"identitas (B+inTFM+outRegen+outSupp == bin) beda: {badid} | "
      f"supp vs M23 beda: {badm}")
json.dump(rows_out, open(os.path.join(OUT, "v5_identity.json"), "w"),
          indent=1, default=str)

# --------------------------------------------- 3. handover MT 23 MR gagal
mt_old, start = [], 0
while True:
    st, d = old.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["company", "=", JURI], ["docstatus", "=", 1],
                               ["purpose", "=", "Material Transfer"],
                               ["posting_date", "=", "2026-10-01"]]),
        "fields": json.dumps(["name"]),
        "limit_page_length": 100, "limit_start": start})
    rows = d.get("data", []) if st == 200 else []
    mt_old += rows
    if len(rows) < 100:
        break
    start += len(rows)
ho_old = []
for r in mt_old:
    st, d = old.get("/api/resource/Stock Entry/" + r["name"])
    if st != 200:
        continue
    roots = {it.get("material_request") for it in
             d["data"].get("items", []) if it.get("material_request")}
    if roots & FAIL_MRS:
        ho_old.append({"se": r["name"], "mrs": sorted(roots & FAIL_MRS),
                       "items": [(it["item_code"], it.get("qty"))
                                 for it in d["data"].get("items", [])]})
print()
print(f"Handover MT lama 1 Okt utk 23 MR gagal: {len(ho_old)}")
found = 0
for h in ho_old:
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["remarks", "like", f"%ERESTO {h['se']} |%"]]),
        "fields": json.dumps(["name", "docstatus"]), "limit_page_length": 3})
    hit = d.get("data") if st == 200 else []
    if hit:
        found += 1
print(f"  ikut ter-replay di site baru: {found} dari {len(ho_old)}")
json.dump(ho_old, open(os.path.join(OUT, "ho23_old.json"), "w"), indent=1,
          default=str)

# -------------------------------------------------- 4. jam MFG 41/23
def times_from(names):
    out = []
    for n in names:
        st, d = old.get("/api/resource/Stock Entry/" + n)
        if st == 200:
            out.append((str(d["data"].get("posting_time")), n))
    out.sort()
    return out


mfg30_names = v3["mfg_split"].get("2026-09-30", [])
t30 = times_from(mfg30_names)
t01 = times_from(m23_old)
print()
if t30:
    print(f"MFG 30Sep ({len(t30)}): jam {t30[0][0]} .. {t30[-1][0]}")
print(f"MFG 1Okt ({len(t01)}): jam {t01[0][0]} .. {t01[-1][0]}")

# cek FG rows support (dari dok lama 1 contoh)
st, d = old.get("/api/resource/Stock Entry/" + m23_old[0])
if st == 200:
    fg = [it for it in d["data"]["items"] if it.get("is_finished_item")]
    fg_txt = [(x["item_code"], x.get("qty"), x.get("t_warehouse")) for x in fg]
    print(f"contoh {m23_old[0]}: FG rows {fg_txt}")

# ------------------------------------- 5. dampak kalau M23 dikurangi lagi
print()
print("kalau M23 dikurangkan LAGI dari bin sekarang:")
neg = [(r["item"], r["bin"], r["M23"], r["bin_minus_M23"]) for r in rows_out
       if r["M23"] > 0.01]
neg.sort(key=lambda x: x[3])
for c, b, m, bm in neg:
    flag = "  <-- MINUS" if bm < -0.01 else ""
    print(f"  {c:<10} bin={b:>12,.2f} - M23={m:>12,.2f} = {bm:>12,.2f}{flag}")
print(f"  total item M23: {len(neg)} | jd minus: "
      f"{sum(1 for x in neg if x[3] < -0.01)}")
print("selesai.")
