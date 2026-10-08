"""Stock Reconciliation pembukaan untuk PROD (docs/07).

Formula per (item, warehouse):
  opening = bin_final_lokal - sum(SLE_lokal dari dokumen yang AKAN diinjeksi)

Dokumen yang diinjeksi = SE "ERESTO MAT-STE-*" + PR + DN (submitted).
Efek scaffolding lokal (SEED/pilot TJBK) TIDAK diinjeksi -> otomatis terserap
ke dalam opening. Warehouse - TJBK (data uji POS pilot) dikecualikan total.

RECO dibuat per (company, warehouse), purpose "Opening Stock",
posting 2026-09-30 23:59:59 (paling awal), expense_account
"1171.000 - Pembukaan sementara - <abbr>".

Mode:
  --dry-run   hitung + tulis pos_sync/prod_src/opening.json + laporan konsol
  (tanpa flag) buat + submit RECO ke prod (idempoten via state + query prod)

Usage: python3 prod_opening.py [--dry-run] [--company NAMA]
"""
import argparse
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from prod_common import (JURI, LOCAL_ENV, PROD_ENV, SRC_DIR, Client,  # noqa: E402
                         jload, load_env, load_state, save_state)

OPENING_DATE = "2026-09-30"
OPENING_TIME = "23:59:59"
RECO_COMPANIES = {JURI, "RS PKU MUHAMMADIYAH DELANGGU",
                  "RSU QUEEN LATIFA YOGYAKARTA"}
EXCLUDE_WH_SUFFIX = "- TJBK"  # data uji POS pilot, jangan dibawa ke prod


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--company", default="")
    args = ap.parse_args()

    bins = jload("bin.json")
    sles = jload("sle.json")
    wh_docs = jload("work_order.json")  # untuk cek

    # dokumen yang akan diinjeksi -> himpunan voucher stock-moving
    se = [d for d in jload("stock_entry.json")
          if d["docstatus"] == 1 and (d.get("remarks") or "").startswith(
              "ERESTO MAT-STE-")]
    pr = [d for d in jload("purchase_receipt.json") if d["docstatus"] == 1]
    dn = [d for d in jload("delivery_note.json") if d["docstatus"] == 1]
    inj_vouchers = set()
    for d in se:
        inj_vouchers.add(("Stock Entry", d["name"]))
    for d in pr:
        inj_vouchers.add(("Purchase Receipt", d["name"]))
    for d in dn:
        inj_vouchers.add(("Delivery Note", d["name"]))

    # warehouse -> company
    le = load_env(LOCAL_ENV)
    pe = load_env(PROD_ENV)
    lc = Client(le["ERPNEXT_URL"], le["ERPNEXT_API_KEY"], label="local")
    pc = Client(pe["ERPNEXT_URL"], pe["ERPNEXT_API_KEY"], label="prod")
    lwh = {w["name"]: w.get("company") for w in
           lc.list_all("Warehouse", ["name", "company"])}
    lco = {w["name"]: w.get("abbr") for w in
           lc.list_all("Company", ["name", "abbr"])}

    # 1. hitung injected sum
    inj = {}
    for s in sles:
        key = (s.get("voucher_type"), s.get("voucher_no"))
        if key not in inj_vouchers:
            continue
        if not s.get("warehouse"):
            continue
        k = (s["item_code"], s["warehouse"])
        inj[k] = inj.get(k, 0.0) + float(s.get("actual_qty") or 0)

    # 2. bin final
    final = {}
    rates = {}
    for b in bins:
        k = (b["item_code"], b["warehouse"])
        final[k] = float(b.get("actual_qty") or 0)
        rates[k] = float(b.get("valuation_rate") or 0)

    # 3. opening = final - inj
    opening = {}
    stats = {"neg": [], "zero": 0, "rows": 0}
    for k in set(final) | set(inj):
        item, wh = k
        if any(wh.endswith(sfx) for sfx in (EXCLUDE_WH_SUFFIX, "- TJBK")):
            continue
        co = lwh.get(wh)
        if co not in RECO_COMPANIES:
            continue
        q = round(final.get(k, 0.0) - inj.get(k, 0.0), 4)
        if abs(q) < 1e-9:
            stats["zero"] += 1
            continue
        if q < 0:
            stats["neg"].append({"item": item, "wh": wh, "opening": q,
                                 "final": final.get(k), "inj": inj.get(k)})
            continue
        opening[k] = (q, rates.get(k, 0.0))

    print(f"== himpunan dokumen ==")
    print(f"  SE={len(se)} PR={len(pr)} DN={len(dn)} "
          f"(voucher unik {len(inj_vouchers)})")
    print(f"== opening ==")
    print(f"  baris: {len(opening)}; nol-diskeep: {stats['zero']}; "
          f"negatif: {len(stats['neg'])}")
    for n in stats["neg"][:10]:
        print("   NEG", n)

    # cek konsistensi ledger lokal (informasi saja — selisih apa pun TERSERAP
    # ke opening; yang penting Bin prod akhir == Bin lokal akhir)
    sle_sum = {}
    for s in sles:
        if not s.get("warehouse"):
            continue
        k = (s["item_code"], s["warehouse"])
        sle_sum[k] = sle_sum.get(k, 0.0) + float(s.get("actual_qty") or 0)
    hidden = 0
    for k, v in final.items():
        d = v - sle_sum.get(k, 0.0)
        if abs(d) > 0.01 and not any(k[1].endswith(sfx) for sfx in ("- TJBK",)):
            hidden += 1
    print(f"  ledger lokal vs Bin: {hidden} pasangan punya efek tersembunyi "
          f"(ternormalisasi ke opening)")

    # 4. grup per company+warehouse
    bywh = {}
    for (item, wh), (q, r) in sorted(opening.items()):
        bywh.setdefault(wh, []).append((item, q, r))
    print(f"  warehouse: {len(bywh)}")
    for wh, rows in sorted(bywh.items()):
        co = lwh.get(wh, "?")
        tot = sum(x[1] for x in rows)
        print(f"   {wh:<42} {co[:34]:<34} {len(rows):>4} item, sum qty {tot:>16,.3f}")

    # simpan
    payload = []
    for wh, rows in sorted(bywh.items()):
        co = lwh[wh]
        payload.append({
            "company": co, "warehouse": wh,
            "posting_date": OPENING_DATE, "posting_time": OPENING_TIME,
            "expense_account": f"1171.000 - Pembukaan sementara - "
                               f"{lco.get(co, '')}",
            "cost_center": f"Main - {lco.get(co, '')}",
            "items": [{"item_code": i, "warehouse": wh, "qty": q,
                       "valuation_rate": r} for i, q, r in rows]})
    json.dump(payload, open(os.path.join(SRC_DIR, "opening.json"), "w"),
              indent=1, default=str)
    print(f"  -> opening.json ({len(payload)} grup)")

    if args.dry_run:
        print("DRY-RUN OK")
        return

    # ---------- apply ----------
    st = load_state()
    st.setdefault("reco", {})
    # idempotency: RECO Opening Stock yang sudah ada di prod (draft/submitted)
    existing = pc.list_all("Stock Reconciliation",
                           ["name", "company", "docstatus"],
                           filters=[["purpose", "=", "Opening Stock"]])
    covered = {}   # (company, warehouse) -> {"name","docstatus","items"}
    for r in existing:
        if r.get("docstatus") == 2:
            continue
        st2, d2 = pc.get("/api/resource/Stock Reconciliation/"
                         + urllib.parse.quote(r["name"]))
        doc = d2.get("data", {}) if st2 == 200 else {}
        whs = {it.get("warehouse") for it in doc.get("items", [])}
        for wh in whs:
            k = (r["company"], wh)
            cur = covered.get(k)
            if cur is None or (cur["docstatus"] == 0
                               and r.get("docstatus") == 1):
                covered[k] = {"name": r["name"],
                              "docstatus": r.get("docstatus", 0),
                              "n_items": len(doc.get("items", []))}

    created, failed, submitted_draft = 0, [], 0
    for grp in payload:
        key = (grp["company"], grp["warehouse"])
        cur = covered.get(key)
        if cur and cur["docstatus"] == 1:
            print(f"  skip {key[0]} / {key[1]}: sudah submitted "
                  f"({cur['name']})")
            st["reco"][f"{key[0]}|{key[1]}"] = cur["name"]
            continue
        if cur and cur["docstatus"] == 0:
            if args.dry_run:
                print(f"  DRY-RUN submit draft {cur['name']}")
                continue
            st3, d3 = pc.submit("Stock Reconciliation", cur["name"])
            if st3 != 200:
                failed.append({"grp": f"{key}", "name": cur["name"],
                               "err": json.dumps(d3)[:400]})
                print(f"  GAGAL SUBMIT draft {cur['name']}: "
                      f"{json.dumps(d3)[:200]}")
                continue
            submitted_draft += 1
            st["reco"][f"{key[0]}|{key[1]}"] = cur["name"]
            print(f"  OK submit draft {cur['name']} {key[1]}")
            continue
        body = {
            "doctype": "Stock Reconciliation", "purpose": "Opening Stock",
            "company": grp["company"], "set_posting_time": 1,
            "posting_date": grp["posting_date"],
            "posting_time": grp["posting_time"],
            "expense_account": grp["expense_account"],
            "cost_center": grp["cost_center"],
            "items": [{"item_code": i["item_code"],
                       "warehouse": i["warehouse"], "qty": i["qty"],
                       "valuation_rate": i["valuation_rate"],
                       "allow_zero_valuation_rate": 1}
                      for i in grp["items"]],
        }
        if args.dry_run:
            print(f"  DRY-RUN buat RECO {key[0]} / {key[1]} "
                  f"({len(grp['items'])} item)")
            continue
        st2, d2 = pc.post("Stock Reconciliation", body)
        if st2 != 200:
            failed.append({"grp": f"{key}", "err": json.dumps(d2)[:400]})
            print(f"  GAGAL POST {key}: {json.dumps(d2)[:200]}")
            continue
        name = d2["data"]["name"]
        st3, d3 = pc.submit("Stock Reconciliation", name)
        if st3 != 200:
            failed.append({"grp": f"{key}", "name": name,
                           "err": json.dumps(d3)[:400]})
            print(f"  GAGAL SUBMIT {name}: {json.dumps(d3)[:250]}")
            continue
        st["reco"][f"{key[0]}|{key[1]}"] = name
        created += 1
        print(f"  OK {name} {key[1]} ({len(grp['items'])} item)")
    save_state(st)
    print(f"RECO baru: {created}; draft di-submit: {submitted_draft}; "
          f"gagal: {len(failed)}")
    for f in failed:
        print("  ", f)
    if failed:
        sys.exit(1)
    print("OPENING OK")


if __name__ == "__main__":
    main()
