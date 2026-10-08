#!/usr/bin/env python3
"""READ-ONLY: audit WIP 30 Sep vs 1 Okt utk keputusan stock reconciliation.

Pertanyaan user (7 Okt 2026):
  - WO tanggal 30 Sep tidak dimigrasi -> tidak muncul request di site baru.
  - Sebagian WIP (mungkin) tidak perlu stock reconciliation.
  - Cek: production plan 30 Sep apa saja; di WIP terakhir tanggal berapa.
  - User finish H+1 -> bahan baku stay di WIP.
  - Hitung WIP utk production tanggal 30 Sep + WO mana -> utk mengurangi
    WIP per 1 Okt.

Output: pos_sync/wip_audit/*.json + ringkasan stdout. Tidak menulis ke
site mana pun.
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
WIP_N = "Work In Progress - JURI"

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


# ==================================================== 1. SITE LAMA: plan 30 Sep
print("=" * 78)
print("1. PRODUCTION PLAN 29-30 Sep + 1 Okt (site lama)")
plans = get_list(old, "Production Plan",
                 [["company", "=", JURI],
                  ["posting_date", ">=", "2026-09-29"],
                  ["posting_date", "<=", "2026-10-01"]],
                 ["name", "posting_date", "status", "docstatus"],
                 order="posting_date asc")
for p in plans:
    print("   ", p)
jdump("plans.json", plans)
plan_names = [p["name"] for p in plans]

# WO per plan + WO dengan planned_start_date 29 Sep-1 Okt
print()
print("2. WORK ORDER terkait plan di atas / planned_start_date 29 Sep-1 Okt")
wos_plan = {}
for pn in plan_names:
    rows = get_list(old, "Work Order",
                    [["production_plan", "=", pn]],
                    ["name", "production_item", "qty", "status", "docstatus",
                     "planned_start_date", "actual_start_date",
                     "actual_end_date"],
                    order="name asc")
    wos_plan[pn] = rows
    print(f"   {pn}: {len(rows)} WO")
    if rows:
        print(f"      pertama {rows[0]['name']} .. terakhir {rows[-1]['name']}")
wos_by_date = get_list(
    old, "Work Order",
    [["company", "=", JURI],
     ["planned_start_date", ">=", "2026-09-29"],
     ["planned_start_date", "<", "2026-10-02"]],
    ["name", "production_item", "qty", "status", "docstatus",
     "planned_start_date", "actual_end_date", "production_plan"],
    order="name asc")
print(f"   planned_start_date 29Sep-1Okt: {len(wos_by_date)} WO")
by_date = defaultdict(list)
for w in wos_by_date:
    by_date[str(w.get("planned_start_date"))[:10]].append(w)
for d in sorted(by_date):
    names = [w["name"] for w in by_date[d]]
    print(f"     {d}: {len(names)} WO  ({names[0]}..{names[-1]})")
jdump("wos_by_date.json", {k: v for k, v in by_date.items()})

# WO yang direferensikan MR gagal (23 handover 1 Okt) + tetangganya
fail_wos = [f"MFG-WO-2026-{n}" for n in range(3860, 3896)]
print()
print("3. WO kisaran 03860-03895 (termasuk 23 WO yg direferensikan MR "
      "gagal) di site lama:")
for n in fail_wos:
    st, d = old.get("/api/resource/Work Order/" + n)
    if st != 200:
        print(f"   {n}: TIDAK ADA di site lama")
        continue
    dd = d["data"]
    print(f"   {n}: item={dd.get('production_item')} qty={dd.get('qty')} "
          f"status={dd.get('status')} planned={dd.get('planned_start_date')} "
          f"actual_start={dd.get('actual_start_date')} "
          f"actual_end={dd.get('actual_end_date')} "
          f"plan={dd.get('production_plan')}")

# ============================================ 4. SITE LAMA: mutasi WIP 28Sep-8Okt
print()
print("=" * 78)
print("4. MUTASI WIP site lama (SLE Work In Progress - ROPI, 28 Sep - 7 Okt)")
sles = get_list(
    old, "Stock Ledger Entry",
    [["warehouse", "=", WIP_O], ["is_cancelled", "=", 0],
     ["posting_date", ">=", "2026-09-28"],
     ["posting_date", "<=", "2026-10-08"]],
    ["name", "item_code", "posting_date", "posting_time", "actual_qty",
     "qty_after_transaction", "voucher_type", "voucher_no",
     "incoming_rate"],
    order="posting_date asc, posting_time asc")
print(f"   {len(sles)} baris SLE")
jdump("sle_wip_old.json", sles)

daily = defaultdict(lambda: [0.0, 0.0])
bal_last = {}          # per item, terakhir (semua waktu dlm window)
bal_by_date = {}       # per item: {tanggal: qty_after terakhir hari itu}
for r in sles:
    d = str(r["posting_date"])[:10]
    q = float(r.get("actual_qty") or 0)
    daily[d][0 if q >= 0 else 1] += q
    bal_last[r["item_code"]] = float(r.get("qty_after_transaction") or 0)
    bal_by_date.setdefault(r["item_code"], {})[d] = \
        float(r.get("qty_after_transaction") or 0)
print("   net per tanggal (masuk + keluar):")
for d in sorted(daily):
    i, o = daily[d]
    print(f"     {d}: in={i:>12,.0f}  out={o:>12,.0f}  net={i+o:>12,.0f}")
print(f"   tanggal SLE WIP terakhir: {sles[-1]['posting_date']} "
      f"{sles[-1]['posting_time']} ({sles[-1]['voucher_no']})"
      if sles else "   (tidak ada SLE)")

# saldo per item: 30 Sep EOD vs terakhir (+ negatif?)
print()
print("   saldo per item: 30Sep EOD -> terakhir (window) [site lama]:")
neg_old = []
for code in sorted(bal_by_date):
    d30 = bal_by_date[code].get("2026-09-30")
    last = bal_last[code]
    mark = ""
    if last < -0.01:
        mark = "  <-- NEGATIF di site lama!"
        neg_old.append(code)
    print(f"     {code:<10} 30Sep={d30 if d30 is not None else '-':>14} "
          f"terakhir={last:>14,.2f}{mark}")
jdump("bal_old.json", {"last": bal_last,
                       "by_date": {k: v for k, v in bal_by_date.items()},
                       "neg": neg_old})

# ================================== 5. SITE LAMA: SE TFM/MFG sekitar 29Sep-2Okt
print()
print("=" * 78)
print("5. SE TFM/MFG site lama 29 Sep - 2 Okt (utk pasangan bahan in/out)")
se_rows = get_list(
    old, "Stock Entry",
    [["company", "=", JURI], ["docstatus", "=", 1],
     ["posting_date", ">=", "2026-09-29"], ["posting_date", "<=", "2026-10-02"],
     ["purpose", "in",
      ["Material Transfer for Manufacture", "Manufacture"]]],
    ["name", "purpose", "posting_date", "posting_time", "work_order"],
    order="posting_date asc, posting_time asc")
print(f"   {len(se_rows)} SE")
jdump("se_tfm_mfg_old.json", se_rows)

# fetch detail utk hitung per-item in/out WIP (dipakai saat WO 30 Sep)
tfms = [r for r in se_rows if r["purpose"] == "Material Transfer for Manufacture"]
mfgs = [r for r in se_rows if r["purpose"] == "Manufacture"]
print(f"   TFM={len(tfms)} MFG={len(mfgs)}")


def fetch_se(n):
    st, d = old.get("/api/resource/Stock Entry/" + n)
    return d.get("data", {}) if st == 200 else {}


flows = {"sep30_tfm_in": defaultdict(float),   # supply buat batch 30 Sep
         "oct01_mfg_out": defaultdict(float),  # konsumsi batch 30 Sep
         "oct01_tfm_in": defaultdict(float),
         "oct02_mfg_out": defaultdict(float),
         "sep30_mfg_out": defaultdict(float)}   # finish batch 29 Sep
for r in se_rows:
    if r["purpose"] == "Material Transfer for Manufacture" and \
            r["posting_date"] == "2026-09-30":
        doc = fetch_se(r["name"])
        for x in doc.get("items", []):
            if x.get("t_warehouse") == WIP_O:
                flows["sep30_tfm_in"][x["item_code"]] += \
                    float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
    if r["purpose"] == "Manufacture" and r["posting_date"] == "2026-10-01":
        doc = fetch_se(r["name"])
        for x in doc.get("items", []):
            if x.get("s_warehouse") == WIP_O:
                flows["oct01_mfg_out"][x["item_code"]] += \
                    float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
    if r["purpose"] == "Manufacture" and r["posting_date"] == "2026-09-30":
        doc = fetch_se(r["name"])
        for x in doc.get("items", []):
            if x.get("s_warehouse") == WIP_O:
                flows["sep30_mfg_out"][x["item_code"]] += \
                    float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
    if r["purpose"] == "Material Transfer for Manufacture" and \
            r["posting_date"] == "2026-10-01":
        doc = fetch_se(r["name"])
        for x in doc.get("items", []):
            if x.get("t_warehouse") == WIP_O:
                flows["oct01_tfm_in"][x["item_code"]] += \
                    float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
    if r["purpose"] == "Manufacture" and r["posting_date"] == "2026-10-02":
        doc = fetch_se(r["name"])
        for x in doc.get("items", []):
            if x.get("s_warehouse") == WIP_O:
                flows["oct02_mfg_out"][x["item_code"]] += \
                    float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)

jdump("flows_old.json", {k: dict(v) for k, v in flows.items()})
tot = {k: sum(v.values()) for k, v in flows.items()}
print("   total per arus:")
for k, v in tot.items():
    print(f"     {k:<14} = {v:>14,.0f}")

# ============================================= 6. SITE BARU: RECO WIP & bin
print()
print("=" * 78)
print("6. SITE BARU: RECO WIP + saldo + mutasi")
recos = get_list(new, "Stock Reconciliation",
                 [["set_warehouse", "=", WIP_N]],
                 ["name", "posting_date", "posting_time", "docstatus",
                  "purpose"])
print("   RECO utk WIP:")
for r in recos:
    print("   ", r)
reco_items = {}
for r in recos:
    st, d = new.get("/api/resource/Stock Reconciliation/" + r["name"])
    if st == 200:
        dd = d["data"]
        reco_items[r["name"]] = [
            {"item_code": x.get("item_code"), "qty": x.get("qty"),
             "rate": x.get("valuation_rate")}
            for x in dd.get("items", [])]
        print(f"      {r['name']}: {len(dd.get('items', []))} item, "
              f"docstatus={dd.get('docstatus')}")
jdump("recos_new.json", {"docs": recos, "items": reco_items})

bins = get_list(new, "Bin", [["warehouse", "=", WIP_N]],
                ["item_code", "actual_qty", "valuation_rate"])
print("   Bin WIP site baru (semua):")
for b in sorted(bins, key=lambda x: x["item_code"]):
    mark = "  <-- NEGATIF" if float(b["actual_qty"]) < -0.01 else ""
    print(f"     {b['item_code']:<10} {float(b['actual_qty']):>14,.2f}{mark}")
jdump("bins_new.json", bins)

sles_new = get_list(
    new, "Stock Ledger Entry",
    [["warehouse", "=", WIP_N], ["is_cancelled", "=", 0]],
    ["name", "item_code", "posting_date", "posting_time", "actual_qty",
     "qty_after_transaction", "voucher_type", "voucher_no"],
    order="posting_date asc, posting_time asc")
print(f"   SLE WIP site baru: {len(sles_new)} baris")
if sles_new:
    last = sles_new[-1]
    print(f"   SLE WIP baru terakhir: {last['posting_date']} "
          f"{last['posting_time']} ({last['voucher_no']})")

# net per item di site baru
net_new = defaultdict(lambda: {"in": 0.0, "out": 0.0})
for r in sles_new:
    q = float(r.get("actual_qty") or 0)
    if q >= 0:
        net_new[r["item_code"]]["in"] += q
    else:
        net_new[r["item_code"]]["out"] += -q
jdump("net_new.json", {k: dict(v) for k, v in net_new.items()})

print()
print("=" * 78)
print("7. TRIANGULASI per item: B(30Sep) | RECO-B diposting | live baru")
posted = {}
for dn, rows in reco_items.items():
    for x in rows:
        posted[x["item_code"]] = posted.get(x["item_code"], 0) + float(x["qty"] or 0)
wd = json.load(open(os.path.join(HERE, "oct7_dump", "wip_sep30.json")))
live = {b["item_code"]: float(b["actual_qty"]) for b in bins}
d09 = json.load(open("/tmp/wip_docs09_net.json"))
allc = sorted(set(list(wd) + list(posted) + list(live) + list(d09)))
print(f"{'item':<10}{'B_sep30':>13}{'posted':>13}{'live':>13}"
      f"{'d09net':>13}{'live-posted':>13}  cek live==posted+d09?")
for c in allc:
    b = float((wd.get(c) or {}).get("qty_after_transaction") or 0)
    p = posted.get(c, 0.0)
    lv = live.get(c, 0.0)
    n9 = (d09.get(c) or {})
    n9v = float(n9.get("in", 0)) - float(n9.get("out", 0))
    lp = lv - p
    ok = "OK" if abs(lv - (p + n9v)) < 0.5 else f"BEDA {lv-(p+n9v):+,.2f}"
    print(f"{c:<10}{b:>13,.2f}{p:>13,.2f}{lv:>13,.2f}{n9v:>13,.2f}"
          f"{lp:>13,.2f}  {ok}")
print("selesai.")
