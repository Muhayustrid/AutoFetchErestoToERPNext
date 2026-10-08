#!/usr/bin/env python3
"""READ-ONLY v3: hitung WIP batch 30 Sep + rekonsiliasi WIP site baru.

Output: pos_sync/wip_audit/*.json + tabel stdout. Tidak menulis ke site.
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

BATCH30 = {f"MFG-WO-2026-{n:05d}" for n in range(3867, 3931)}

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


def fetch_se(n):
    st, d = old.get("/api/resource/Stock Entry/" + n)
    return d.get("data", {}) if st == 200 else {}


def wip_in_out(doc):
    """Kembalikan (ins, outs) dict item->qty utk baris WIP saja."""
    ins, outs = defaultdict(float), defaultdict(float)
    for x in doc.get("items", []):
        q = float(x.get("qty") or 0) * float(x.get("conversion_factor") or 1)
        if x.get("t_warehouse") == WIP_O and x.get("s_warehouse") != WIP_O:
            ins[x["item_code"]] += q
        elif x.get("s_warehouse") == WIP_O:
            outs[x["item_code"]] += q
    return ins, outs


# ================================================================ 1. OLD SEs
print("=" * 78)
print("1. SE site lama: batch-30 (30Sep & 1Okt) + SE 7 Okt (yang dikecualikan)")
tfm30_rows = get_list(old, "Stock Entry",
                      [["company", "=", JURI], ["docstatus", "=", 1],
                       ["purpose", "=", "Material Transfer for Manufacture"],
                       ["posting_date", "=", "2026-09-30"]],
                      ["name", "work_order", "posting_date"],
                      order="name asc")
mfg_rows = get_list(old, "Stock Entry",
                    [["company", "=", JURI], ["docstatus", "=", 1],
                     ["purpose", "=", "Manufacture"],
                     ["posting_date", "in", ["2026-09-30", "2026-10-01"]]],
                    ["name", "work_order", "posting_date"],
                    order="name asc")
oct7_tfm_rows = get_list(old, "Stock Entry",
                         [["company", "=", JURI], ["docstatus", "=", 1],
                          ["purpose", "=", "Material Transfer for Manufacture"],
                          ["posting_date", "=", "2026-10-07"]],
                         ["name", "work_order"], order="name asc")
oct7_mfg_rows = get_list(old, "Stock Entry",
                         [["company", "=", JURI], ["docstatus", "=", 1],
                          ["purpose", "=", "Manufacture"],
                          ["posting_date", "=", "2026-10-07"]],
                         ["name", "work_order"], order="name asc")
print(f"   TFM 30Sep: {len(tfm30_rows)} | MFG 30Sep+1Okt: {len(mfg_rows)}")
print(f"   TFM 7Okt: {len(oct7_tfm_rows)} | MFG 7Okt: {len(oct7_mfg_rows)}")

t_batch = [r for r in tfm30_rows if r.get("work_order") in BATCH30]
m_batch = [r for r in mfg_rows if r.get("work_order") in BATCH30]
print(f"   -> batch-30: TFM {len(t_batch)} | MFG {len(m_batch)}")

M30, M41, M23 = defaultdict(float), defaultdict(float), defaultdict(float)
mfg_split = defaultdict(list)
m23_docs = []
for r in t_batch:
    ins, _ = wip_in_out(fetch_se(r["name"]))
    for c, q in ins.items():
        M30[c] += q
for r in m_batch:
    _, outs = wip_in_out(fetch_se(r["name"]))
    d = str(r["posting_date"])[:10]
    mfg_split[d].append(r["name"])
    tgt = M41 if d == "2026-09-30" else M23
    for c, q in outs.items():
        tgt[c] += q
    if d == "2026-10-01":
        m23_docs.append({"se": r["name"], "wo": r["work_order"]})

INS7, OUTS7 = defaultdict(float), defaultdict(float)
for r in oct7_tfm_rows:
    ins, _ = wip_in_out(fetch_se(r["name"]))
    for c, q in ins.items():
        INS7[c] += q
for r in oct7_mfg_rows:
    _, outs = wip_in_out(fetch_se(r["name"]))
    for c, q in outs.items():
        OUTS7[c] += q

jdump("v3_data.json", {
    "M30": dict(M30), "M41": dict(M41), "M23": dict(M23),
    "INS7": dict(INS7), "OUTS7": dict(OUTS7),
    "mfg_split": {k: v for k, v in mfg_split.items()},
    "m23_docs": m23_docs,
    "counts": {"tfm30": len(tfm30_rows), "tfm_batch": len(t_batch),
               "mfg_batch": len(m_batch),
               "oct7_tfm": len(oct7_tfm_rows),
               "oct7_mfg": len(oct7_mfg_rows),
               "mfg_30": len(mfg_split.get("2026-09-30", [])),
               "mfg_01": len(mfg_split.get("2026-10-01", []))}})

print()
print("   MFG batch-30 per tanggal: "
      f"30Sep={len(mfg_split.get('2026-09-30', []))} "
      f"1Okt={len(mfg_split.get('2026-10-01', []))}")
print("   23 WO yang finish 1 Okt:", sorted(
    {d['wo'] for d in m23_docs}))
print(f"   M30 total = {sum(M30.values()):,.2f} "
      f"({len(M30)} item)")
print(f"   M41 total = {sum(M41.values()):,.2f} "
      f"({len(M41)} item)")
print(f"   M23 total = {sum(M23.values()):,.2f} "
      f"({len(M23)} item)")
print(f"   INS7 total = {sum(INS7.values()):,.2f} ({len(INS7)} item)")
print(f"   OUTS7 total = {sum(OUTS7.values()):,.2f} ({len(OUTS7)} item)")

print()
print(f"   {'item':<10}{'M30':>14}{'M41(30Sep)':>14}{'M23(1Okt)':>14}"
      f"{'cek M41+M23==M30':>18}")
bad = 0
for c in sorted(M30):
    s = M41.get(c, 0) + M23.get(c, 0)
    ok = abs(s - M30[c]) < 0.01
    if not ok:
        bad += 1
    print(f"   {c:<10}{M30[c]:>14,.2f}{M41.get(c, 0):>14,.2f}"
          f"{M23.get(c, 0):>14,.2f}{'OK' if ok else 'BEDA '+format(s-M30[c], ',.2f'):>18}")
print(f"   selisih tak balance: {bad} item")

# ================================================================ 2. NEW SLE
print()
print("=" * 78)
print("2. SITE BARU: SLE WIP lengkap")
sles = get_list(
    new, "Stock Ledger Entry",
    [["warehouse", "=", WIP_N], ["is_cancelled", "=", 0]],
    ["name", "item_code", "posting_date", "posting_time", "actual_qty",
     "voucher_type", "voucher_no"],
    order="posting_date asc, posting_time asc")
print(f"   {len(sles)} baris SLE WIP site baru")
jdump("sle_wip_new.json", sles)

opening, replay = defaultdict(float), defaultdict(float)
groups = defaultdict(lambda: defaultdict(float))
for r in sles:
    q = float(r.get("actual_qty") or 0)
    if r.get("voucher_type") == "Stock Reconciliation":
        opening[r["item_code"]] += q
    else:
        replay[r["item_code"]] += q
        groups[(r.get("voucher_no") or "")[:12]][r["item_code"]] += q

bins = get_list(new, "Bin", [["warehouse", "=", WIP_N]],
                ["item_code", "actual_qty"])
live = {b["item_code"]: float(b["actual_qty"]) for b in bins}

print()
print(f"   {'item':<10}{'opening':>14}{'replay_net':>14}{'open+replay':>14}"
      f"{'bin(live)':>14}  cek")
for c in sorted(set(list(opening) + list(live))):
    o = opening.get(c, 0.0)
    rp = replay.get(c, 0.0)
    lv = live.get(c, 0.0)
    ok = "OK" if abs(o + rp - lv) < 0.01 else f"BEDA {o+rp-lv:+,.2f}"
    print(f"   {c:<10}{o:>14,.2f}{rp:>14,.2f}{o+rp:>14,.2f}{lv:>14,.2f}  {ok}")

# voucher kelompok besar yang menyentuh WIP + contoh untuk item negatif
print()
print("   kelompok voucher (prefix) yang menyentuh WIP:")
pref_net = defaultdict(float)
pref_cnt = defaultdict(set)
for r in sles:
    if r.get("voucher_type") == "Stock Reconciliation":
        continue
    s = (r.get("voucher_no") or "")[:12]
    pref_net[s] += float(r.get("actual_qty") or 0)
    pref_cnt[s].add(r.get("voucher_no"))
for s in sorted(pref_net):
    print(f"     {s:<14} net={pref_net[s]:>16,.2f}  dok={len(pref_cnt[s])}")

neg = [c for c in live if live[c] < -0.01]
print()
print("   item negatif & voucher penyebab (out terbesar):")
for c in sorted(neg):
    contrib = []
    for s, items in groups.items():
        if items.get(c, 0) < -0.01:
            contrib.append((items[c], s))
    contrib.sort()
    top = ", ".join(f"{s}={v:,.2f}" for v, s in contrib[:4])
    print(f"     {c:<10} live={live[c]:>12,.2f} | out: {top}")

# ================================================================ 3. COMPARE
print()
print("=" * 78)
print("3. Rekonsiliasi: site lama EOD vs site baru vs komponen")
bal_old = json.load(open(os.path.join(OUT, "bal_old.json")))
bydate = bal_old["by_date"]
EOD30 = {c: bydate[c].get("2026-09-30") for c in bydate}
EOD1 = {c: bydate[c].get("2026-10-01") for c in bydate}
EOD7 = {c: bydate[c].get("2026-10-07") for c in bydate}

print(f"{'item':<10}{'EOD30':>13}{'EOD7':>13}{'open':>13}{'live':>13}"
      f"{'M23':>11}{'ins7':>11}{'outs7':>10}{'live-ekspektasi':>16}")
print("  ekspektasi = EOD7 - ins7 + outs7 (= EOD7 minus efek SE 7Okt yang "
      "dikecualikan)")
for c in sorted(set(list(EOD30) + list(live))):
    e30 = EOD30.get(c)
    e7 = EOD7.get(c)
    o = opening.get(c, 0)
    lv = live.get(c, 0)
    m23 = M23.get(c, 0)
    i7 = INS7.get(c, 0)
    o7 = OUTS7.get(c, 0)
    if e7 is None:
        exp = None
        dev = None
    else:
        exp = e7 - i7 + o7
        dev = lv - exp
    sc = lambda v: f"{v:,.2f}" if v is not None else "-"
    dstr = f"{dev:+,.2f}" if dev is not None else "-"
    print(f"{c:<10}{sc(e30):>13}{sc(e7):>13}{o:>13,.2f}{lv:>13,.2f}"
          f"{m23:>11,.2f}{i7:>11,.2f}{o7:>10,.2f}{dstr:>16}")
print("selesai.")
