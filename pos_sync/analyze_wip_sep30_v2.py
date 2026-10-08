#!/usr/bin/env python3
"""READ-ONLY v2: fakta Sep 30 vs WIP utk validasi pemahaman user.

Pertanyaan user:
 - WO tanggal 30 ga masuk -> ga masuk request;
 - sebagian WIP mungkin ga perlu stock recon;
 - cek production plan tgl 30; WIP terakhir tgl berapa;
 - hitung WIP utk production tgl 30; WO mana yg dari 30 Sep;
 - itu utk ngurangin WIP tgl 1 Oktober.
"""
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from migrate_wo_full_okt import Ctx  # noqa: E402
from prod_common import JURI  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "wip_audit")
os.makedirs(OUT, exist_ok=True)
WIP_O = "Work In Progress - ROPI"

ctx = Ctx()
old, new = ctx.old, ctx.new


def jdump(n, o):
    with open(os.path.join(OUT, n), "w") as f:
        json.dump(o, f, indent=1, default=str)


def get_list(client, dt, filters, fields, limit=500, order=None):
    out, start = [], 0
    while True:
        p = {"filters": json.dumps(filters), "fields": json.dumps(fields),
             "limit_page_length": limit, "limit_start": start}
        if order:
            p["order_by"] = order
        st, d = client.get("/api/resource/" + dt, p)
        rows = d.get("data", []) if st == 200 else []
        out += rows
        if len(rows) < limit:
            break
        start += len(rows)
    return out


# ---------------------------------------------------------------- 1. PLAN 30
print("=" * 78)
print("1. PRODUCTION PLAN 28 Sep - 1 Okt (site lama)")
cache_p = os.path.join(OUT, "plans_28sep_1oct.json")
if os.path.exists(cache_p):
    plan_docs = json.load(open(cache_p))
    plans = [{"name": k, "posting_date": v["posting_date"],
              "status": v["status"], "docstatus": v["docstatus"]}
             for k, v in plan_docs.items()]
else:
    plans = get_list(old, "Production Plan",
                     [["company", "=", JURI],
                      ["posting_date", ">=", "2026-09-28"],
                      ["posting_date", "<=", "2026-10-01"]],
                     ["name", "posting_date", "status", "docstatus"],
                     order="posting_date asc, name asc")
    plan_docs = {}
    for p in plans:
        st, d = old.get("/api/resource/Production Plan/" + p["name"])
        if st == 200:
            plan_docs[p["name"]] = d["data"]
    jdump("plans_28sep_1oct.json", plan_docs)
for p in plans:
    d = plan_docs.get(p["name"], {})
    items = [(r.get("item_code"), r.get("planned_qty"))
             for r in d.get("po_items", [])]
    print(f"   {p['name']} | {p['posting_date']} | status={p['status']} "
          f"| docstatus={p['docstatus']} | po_items={len(items)}")
    tot = defaultdict(float)
    for c, q in items:
        tot[c] += float(q or 0)
    print(f"      produk: {dict(tot)}")

# ---------------------------------------------------------------- 2. WO 30 Sep
print()
print("2. WORK ORDER planned/actual start 29 Sep - 1 Okt (site lama)")
cache_w = os.path.join(OUT, "wos_start_29sep_1oct.json")
if os.path.exists(cache_w):
    _cw = json.load(open(cache_w))
    wos = _cw["wos"]
    by_plan = _cw["by_plan"]
else:
    wos = get_list(old, "Work Order",
                   [["company", "=", JURI],
                    ["planned_start_date", ">=", "2026-09-29"],
                    ["planned_start_date", "<", "2026-10-02"]],
                   ["name", "production_item", "qty", "status", "docstatus",
                    "planned_start_date", "actual_start_date",
                    "actual_end_date", "production_plan", "produced_qty"],
                   order="name asc")
    by_plan = defaultdict(list)
    for w in wos:
        by_plan[w.get("production_plan") or "-"].append(w)
    by_plan = {k: [w["name"] for w in v] for k, v in by_plan.items()}
    jdump("wos_start_29sep_1oct.json", {"wos": wos, "by_plan": by_plan})
print(f"   {len(wos)} WO (planned_start dalam window)")
by_pd = defaultdict(list)
for w in wos:
    by_pd[str(w["planned_start_date"])[:10]].append(w)
for d in sorted(by_pd):
    ws = by_pd[d]
    names = [w["name"] for w in ws]
    print(f"   planned_start {d}: {len(ws)} WO  {names[0]}..{names[-1]}")
for p, ws in sorted(by_plan.items()):
    print(f"   plan {p}: {len(ws)} WO")

# WO set dari replay docs/09 (yang dimigrasi) utk pembanding
replayed = set(json.load(open(os.path.join(HERE, "wo_dump", "wos.json"))))
sep30_starts = {w["name"] for w in wos
                if str(w["planned_start_date"])[:10] == "2026-09-30"}
print()
print("3. WO planned_start 30 Sep:", len(sep30_starts))
print("   diantaranya TIDAK dimigrasi docs/09:",
      len(sep30_starts - replayed))
# apakah 03867-92 masuk sini?
probe = {f"MFG-WO-2026-{n:05d}" for n in range(3860, 3940)}
hit = sep30_starts & probe
print(f"   irisan dgn range 03860-03939: {len(hit)} ->",
      sorted(hit)[:5], "...", sorted(hit)[-5:] if hit else "")

# ------------------------------------------------- 4. detail WO 03867..03931
print()
print("4. Detail WO 03867..03931 (site lama) — rencana vs aktual")
det = {}
for n in range(3867, 3932):
    nm = f"MFG-WO-2026-{n:05d}"
    st, d = old.get("/api/resource/Work Order/" + nm)
    if st != 200:
        det[nm] = None
        continue
    dd = d["data"]
    det[nm] = {k: dd.get(k) for k in
               ("name", "production_item", "qty", "produced_qty", "status",
                "docstatus", "planned_start_date", "actual_start_date",
                "actual_end_date", "production_plan", "custom_handover_status",
                "custom_handover_material_request")}
found = [v for v in det.values() if v]
print(f"   ada {len(found)} dari 65")
if found:
    pds = sorted({str(v["planned_start_date"])[:10] for v in found})
    ads = sorted({str(v["actual_start_date"])[:10] for v in found
                  if v["actual_start_date"]})
    aed = sorted({str(v["actual_end_date"])[:10] for v in found
                  if v["actual_end_date"]})
    plans_ = sorted({v["production_plan"] or "-" for v in found})
    print(f"   planned_start: {pds}")
    print(f"   actual_start : {ads}")
    print(f"   actual_end   : {aed}")
    print(f"   plan         : {plans_}")
    sts = defaultdict(int)
    for v in found:
        sts[v["status"]] += 1
    print(f"   status       : {dict(sts)}")
jdump("wo_3867_3931.json", det)

# ------------------------------- 5. arus TFM/MFG khusus WO Sep-30 batch
print()
print("5. TFM (30 Sep) & MFG (1 Okt) khusus batch WO 03867..03931")
se_rows = get_list(old, "Stock Entry",
                   [["company", "=", JURI], ["docstatus", "=", 1],
                    ["purpose", "in", ["Material Transfer for Manufacture",
                                       "Manufacture"]],
                    ["posting_date", ">=", "2026-09-30"],
                    ["posting_date", "<=", "2026-10-01"]],
                   ["name", "purpose", "posting_date", "work_order"],
                   order="posting_date asc, name asc")
batch = {f"MFG-WO-2026-{n:05d}" for n in range(3867, 3932)}
tfm_b, mfg_b = [], []
tfm_o, mfg_o = [], []
for r in se_rows:
    inb = r.get("work_order") in batch
    (tfm_b if inb else tfm_o).append(r) if \
        r["purpose"].startswith("Material Transfer") else \
        (mfg_b if inb else mfg_o).append(r)
print(f"   TFM: batch={len(tfm_b)} | lainnya={len(tfm_o)}")
print(f"   MFG: batch={len(mfg_b)} | lainnya={len(mfg_o)}")
for r in mfg_o[:6]:
    print(f"     MFG lain: {r['name']} {r['posting_date']} wo={r.get('work_order')}")


def sum_se(names):
    ins, outs = defaultdict(float), defaultdict(float)
    for nm in names:
        st, d = old.get("/api/resource/Stock Entry/" + nm)
        if st != 200:
            continue
        for x in d["data"].get("items", []):
            q = float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
            if x.get("t_warehouse") == WIP_O and x.get("s_warehouse") != WIP_O:
                ins[x["item_code"]] += q
            elif x.get("s_warehouse") == WIP_O:
                outs[x["item_code"]] += q
    return ins, outs


tfm_in, _ = sum_se([r["name"] for r in tfm_b])
_, mfg_out = sum_se([r["name"] for r in mfg_b])
print()
print("   per item: TFM-in(30Sep) vs MFG-out(1Okt) batch Sep:")
print(f"   {'item':<10}{'TFM_in':>14}{'MFG_out':>14}{'selisih':>14}")
res = {}
allc = sorted(set(tfm_in) | set(mfg_out))
for c in allc:
    a, b = tfm_in.get(c, 0), mfg_out.get(c, 0)
    res[c] = a - b
    print(f"   {c:<10}{a:>14,.2f}{b:>14,.2f}{a-b:>14,.2f}")
jdump("batch_sep30_flows.json",
      {"tfm_in": dict(tfm_in), "mfg_out": dict(mfg_out), "residual": res,
       "tfm_se": [r["name"] for r in tfm_b],
       "mfg_se": [r["name"] for r in mfg_b]})

# ------------------------- 6. saldo WIP per EOD (site lama) dari SLE lama
print()
print("6. Saldo WIP site lama per EOD (SLE tersimpan)")
sles = json.load(open(os.path.join(OUT, "sle_wip_old.json")))
bal = {}
for r in sles:
    d = str(r["posting_date"])[:10]
    bal.setdefault(r["item_code"], {})[d] = \
        float(r.get("qty_after_transaction") or 0)
dates = ["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05",
         "2026-10-06", "2026-10-07"]
print(f"   {'item':<10}" + "".join(f"{d[5:]:>12}" for d in dates))
for c in sorted(bal):
    row = "".join(f"{bal[c].get(d, 0):>12,.0f}" for d in dates)
    print(f"   {c:<10}{row}")
last = sles[-1]
print(f"   SLE WIP terakhir: {last['posting_date']} {last['posting_time']} "
      f"({last['voucher_no']})")

# ---------------------- 7. WO Sep30 yg MFG-nya ada di set replay? + support
print()
print("7. Cek: MFG SE batch Sep di site BARU (replay sebagai support?)")
idx = json.load(open(os.path.join(HERE, "wo_dump", "se_index.json")))
mfg_idx = [r for r in idx if r["purpose"] == "Manufacture"
           and r.get("work_order") in batch]
print(f"   MFG di se_index utk batch Sep: {len(mfg_idx)} dokumen")
mfg_wos = sorted({r["work_order"] for r in mfg_idx})
print(f"   WO: {mfg_wos[0]}..{mfg_wos[-1]} ({len(mfg_wos)} unik)")
# nama baru utk se lama:
ses_old = json.load(open(os.path.join(HERE, "wo_dump", "ses.json")))
tfm_set = set()
for r in idx:
    if r["purpose"] == "Manufacture" and r.get("work_order") in batch:
        tfm_set.add(r["name"])
# cari di site baru melalui remarks
found_new = 0
for nm in sorted(tfm_set)[:200]:
    st, d = new.get("/api/resource/Stock Entry", {
        "filters": json.dumps([["remarks", "like", f"%ERESTO {nm} |%"]]),
        "fields": json.dumps(["name", "docstatus"]),
        "limit_page_length": 1})
    if st == 200 and d.get("data"):
        found_new += 1
print(f"   dari {len(tfm_set)} MFG batch Sep, {found_new} ada di site baru "
      f"(via marker remarks)")
print("selesai.")
