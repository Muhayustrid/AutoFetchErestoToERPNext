"""Tarik SO Monthly September (93 SA) + baris item -> Excel stok per outlet.

Sumber: /v2/stock_adjustments (list) + /v2/stock_adjustment_items
(stock_adjustment_id) + /v2/inventories (nama kategori).
Filter: reason == 'SO Monthly September'; 'Auto stock balancing' diskip.
Kolom kunci: current_quantity (sistem), real_quantity (hasil hitung),
adjustment_quantity/value (selisih). Stok opname = real_quantity.

Env dari /tmp/eresto_mig.env. Output: experiments/Stock_SO_Monthly_September.xlsx
(SO_Items, Rekap_Outlet, Meta) + stock_so_monthly.json. Idempoten (cache list).
"""
import json
import os
import sys
import time

import requests
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

ENV_PATH = "/tmp/eresto_mig.env"
BASE = "https://ropi.eresto.id"
DOMAIN = "ropi"
PER_PAGE = 200
MAX_RETRIES = 3
TIMEOUT = 90
TEMP_CODES = {429, 500, 502, 503, 504}
REASON = "SO Monthly September"
LIST_CACHE = "/tmp/sa_sep.json"
OUT_XLSX = "experiments/Stock_SO_Monthly_September.xlsx"
OUT_JSON = "experiments/stock_so_monthly.json"


def load_env(path):
    d = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip().strip('"').strip("'")
    return d


ENV = load_env(ENV_PATH)


def make_session():
    s = requests.Session()
    s.headers.update({
        "accept": "application/json, text/plain, */*",
        "authorization": f"Token token={ENV['ERESTO_TOKEN']}, "
                         f"email={ENV['ERESTO_EMAIL']}",
        "referer": "https://ropi.eresto.id/manager/v2/index.html",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
        "cache-control": "no-cache", "pragma": "no-cache",
    })
    return s


S = make_session()


def get(path, **params):
    p = {"current_user_id": ENV["ERESTO_USER_ID"], "domain": DOMAIN,
         "token": ENV["ERESTO_TOKEN"], "_": int(time.time() * 1000)}
    p.update(params)
    last = None
    for a in range(1, MAX_RETRIES + 1):
        try:
            r = S.get(BASE + path, params=p, timeout=TIMEOUT)
            if r.status_code in TEMP_CODES:
                last = f"HTTP {r.status_code}"
                time.sleep(2 ** a)
                continue
            r.raise_for_status()
            return r.json()
        except requests.RequestException as e:
            last = str(e)[:150]
            time.sleep(2 ** a)
    print(f"FATAL: {path} gagal: {last}")
    sys.exit(1)


def num(v):
    try:
        return float(v) if v not in (None, "") else 0.0
    except (TypeError, ValueError):
        return 0.0


def fetch_september_list():
    if os.path.exists(LIST_CACHE):
        rows = json.load(open(LIST_CACHE))
        print(f"list cache: {len(rows)} baris ({LIST_CACHE})")
        return rows
    rows, page = [], 1
    while True:
        d = get("/v2/stock_adjustments",
                **{"date[geq]": "Mon, 1 Sep 2026 00:00:00.000",
                   "date[leq]": "Tue, 30 Sep 2026 23:59:59.999",
                   "division_id": "", "page": page, "per_page": PER_PAGE,
                   "sort[order]": "desc", "sort[property]": "updated_at"})
        batch = d.get("stock_adjustments", [])
        rows.extend(batch)
        meta = d.get("meta", {})
        print(f"  list page {page}: {len(batch)}")
        if len(batch) < PER_PAGE or not meta.get("next_page"):
            break
        page += 1
    json.dump(rows, open(LIST_CACHE, "w"))
    return rows


def fetch_items(sa_id):
    out, page = [], 1
    while True:
        d = get("/v2/stock_adjustment_items",
                stock_adjustment_id=sa_id, page=page, per_page=PER_PAGE)
        batch = d.get("stock_adjustment_items", [])
        out.extend(batch)
        meta = d.get("meta", {})
        if len(batch) < PER_PAGE or not meta.get("next_page"):
            return out, meta


def fetch_inventory_categories():
    cat, page = {}, 1
    while True:
        d = get("/v2/inventories", page=page, per_page=200)
        for inv in d.get("inventories", []):
            ic = inv.get("inventory_category") or {}
            cat[inv["id"]] = ic.get("name") or ""
        meta = d.get("meta", {})
        if not meta.get("next_page"):
            return cat
        page += 1


def style_sheet(ws):
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    fill = PatternFill("solid", fgColor="D9EAF7")
    for c in ws[1]:
        c.fill, c.font = fill, Font(bold=True)
        c.alignment = Alignment(horizontal="center", vertical="center")
    for col in ws.columns:
        w = max(len(str(c.value or "")) for c in col)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(w + 2, 45)


def main():
    rows = fetch_september_list()
    # filter: SO Monthly September, buang yang deleted
    sas = [x for x in rows
           if (x.get("reason") or "").strip() == REASON
           and not x.get("deleted_at")]
    dropped_del = sum(1 for x in rows if (x.get("reason") or "").strip() == REASON
                      and x.get("deleted_at"))
    print(f"SA '{REASON}': {len(sas)} (deleted dilewati: {dropped_del})")
    if not sas:
        print("FATAL: tidak ada SA yang cocok")
        sys.exit(1)

    # dedup nomor SA (list bisa memuat baris kembar)
    seen, uniq = set(), []
    for x in sas:
        if x["number"] in seen:
            continue
        seen.add(x["number"])
        uniq.append(x)
    print(f"unik: {len(uniq)} nomor SA")
    sas = uniq

    print("fetch kategori inventory...")
    cat = fetch_inventory_categories()
    print(f"  {len(cat)} inventory berkategori")

    out_rows, rekap, errors = [], [], []
    for i, sa in enumerate(sas, 1):
        div = sa.get("division") or {}
        outlet = div.get("name") or sa.get("division_id")
        branch = div.get("branch_number") or ""
        items, meta = fetch_items(sa["id"])
        tot = 0.0
        for it in items:
            inv = it.get("inventory") or {}
            if it.get("deleted_at") or inv.get("deleted_at"):
                continue
            rows_ = {
                "outlet": outlet, "branch": branch,
                "sa_number": sa["number"], "sa_date": sa.get("date"),
                "sku": inv.get("sku"), "item_name": inv.get("name"),
                "category": cat.get(inv.get("id"), ""),
                "unit": (it.get("unit") or {}).get("name") or "",
                "current_qty": num(it.get("current_quantity")),
                "real_qty": num(it.get("real_quantity")),
                "adj_qty": num(it.get("adjustment_quantity")),
                "adj_value": num(it.get("adjustment_value")),
                "current_cost": num(it.get("current_cost")),
                "real_cost": num(it.get("real_cost")),
            }
            tot += rows_["adj_value"]
            out_rows.append(rows_)
        exp = num(meta.get("total_value"))
        ok = abs(tot - exp) < 1.0
        if not ok:
            errors.append({"sa": sa["number"], "outlet": outlet,
                           "sum_adj": tot, "meta_total": exp})
        rekap.append({
            "outlet": outlet, "branch": branch, "sa_number": sa["number"],
            "sa_date": sa.get("date"), "items": len(items),
            "sum_adj_value": round(tot, 2),
            "meta_total_value": exp, "check": "OK" if ok else "SELISIH",
        })
        print(f"  [{i}/{len(sas)}] {sa['number']:22} {outlet[:38]:38} "
              f"{len(items):4} item  {tot:>14,.0f}  {'OK' if ok else 'CEK'}",
              flush=True)

    os.makedirs("experiments", exist_ok=True)
    import pandas as pd
    with pd.ExcelWriter(OUT_XLSX, engine="openpyxl") as w:
        pd.DataFrame(out_rows).to_excel(w, sheet_name="SO_Items", index=False)
        pd.DataFrame(rekap).to_excel(w, sheet_name="Rekap_Outlet", index=False)
        pd.DataFrame([{"param": k, "value": v} for k, v in {
            "sumber": "/v2/stock_adjustments + /v2/stock_adjustment_items",
            "filter_reason": REASON,
            "periode": "2026-09-01 s/d 2026-09-30",
            "sa_count": len(sas), "rows": len(out_rows),
            "auto_stock_balancing": "diskip total",
        }.items()]).to_excel(w, sheet_name="Meta", index=False)
        for ws in w.sheets.values():
            style_sheet(ws)
    json.dump({"sa": rekap, "rows": out_rows, "errors": errors},
              open(OUT_JSON, "w"), indent=1)

    print(f"\nRows: {len(out_rows)} | SA: {len(sas)} | "
          f"outlet unik: {len({r['outlet'] for r in out_rows})}")
    print(f"Selisih checksum: {len(errors)}")
    for e in errors[:10]:
        print("  ", e)
    tot_val = sum(r["adj_value"] for r in out_rows)
    print(f"Total adjustment value: {tot_val:,.2f}")
    print(f"Excel: {OUT_XLSX}")
    print(f"JSON : {OUT_JSON}")


if __name__ == "__main__":
    main()
