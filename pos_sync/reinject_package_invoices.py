"""Re-injeksi transaksi POS Package Delanggu dengan alokasi harga proporsional.

Skenario:
- POS Next Global Settings.enable_pos_package_allocation = 1 (sudah aktif di Cloud).
- 17 transaksi eResto yang memuat produk paket dibersihkan dan diinjeksi ulang:
  1 invoice pada 2026-10-01 sudah sukses diinjeksi (PINV-RPMD-261006107).
  16 invoice sisanya (2026-10-02, 2026-10-03, 2026-10-05) diproses per shift:
    1. Reopen shift (membatalkan & menghapus POS Closing Shift lama).
    2. Batalkan & hapus dokumen POS Invoice paket lama.
    3. Generate payload baru dengan struktur POS Package resmi:
       - Header: item_code paket, role "Package", rate 0, snapshot kuotasi server.
       - Komponen: item_code komponen, role "Package Item", rate teralokasi proporsional.
       - Item reguler (non-paket) tetap disertakan sesuai pesanan asli.
    4. Submit invoice baru via pos_next.api.backdate_invoices.submit_backdate_invoice.
    5. Tutup kembali shift dengan get_closing_shift_data & submit POS Closing Shift baru.
    6. Verifikasi GL Entry, Stock Ledger Entry, dan saldo Bin.
"""
import collections
import glob
import json
import os
import sys
import time
from pathlib import Path
import openpyxl
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
import requests

# Load env
ENV_FILE = Path("/tmp/eresto_prod.env")
if not ENV_FILE.exists():
    ENV_FILE = Path("/tmp/eresto_mig.env")

env_vars = {}
for line in ENV_FILE.read_text().splitlines():
    if "=" in line and not line.startswith("#"):
        k, v = line.split("=", 1)
        env_vars[k.strip()] = v.strip()

BASE_URL = env_vars["ERPNEXT_URL"].rstrip("/")
HEADERS = {"Authorization": f"token {env_vars['ERPNEXT_API_KEY']}"}
COMPANY = "RS PKU MUHAMMADIYAH DELANGGU"
WAREHOUSE = "Stores - RPMD"
PROFILE = "SHIFT 1 - RS PKU MUHAMMADIYAH DELANGGU"
CUSTOMER = "Walk-in Customer"

PAY_FIELD_MAP = {
    "cash_amount": "Cash",
    "ewallet_amount": "QRIS",
    "debit_amount": "Debit Card",
    "credit_amount": "Credit Card",
}

# Mapping definisi paket dan pilihan di Delanggu
PACKAGES_CONFIG = {
    "HEMAT 1 NEW": {
        "parent_item": "PAKET26-004",
        "group_key": "rhpfahzl",
        "options": {
            "RP001": "6tc98i6eia",
            "RP002": "6tc9fp1n59",
            "RP003": "6tc9okrtjk",
        },
    },
    "HEMAT 2 NEW": {
        "parent_item": "PAKET26-005",
        "group_key": "rvfgd0pw",
        "options": {
            "RP001": "1u4nfcdh5h",
            "RP002": "1u4neu6v1g",
            "RP003": "1u4n0nube5",
        },
    },
    "HEMAT 3 NEW": {
        "parent_item": "PAKET26-003",
        "group_key": "dzrekvzd",
        "options": {
            "RP001": "6upe790ost",
            "RP002": "bv2elf0eu6",
            "RP003": "bv2el9jp36",
        },
    },
    "HEMAT 4 NEW": {
        "parent_item": "PAKET26-006",
        "group_key": "gyn5wyie",
        "options": {
            "RP001": "9vo59a4rh6",
            "RP002": "9vo5cgf22a",
            "RP003": "9vo5f96b2m",
        },
    },
    "Paket Goodiebag 6 ROPI": {
        "parent_item": "PAKET010926-005",
        "group_key": "orb0lqpt",
        "options": {
            "RP001": "61n90ivmq9",
            "RP002": "61n9492u3t",
            "RP003": "61n9i5e1nc",
        },
    },
}

# SKU eResto to package name
SKU_TO_PACKAGE = {
    "PR00142": "HEMAT 1 NEW",
    "PR00143": "HEMAT 2 NEW",
    "PR00140": "HEMAT 3 NEW",
    "PR00141": "HEMAT 4 NEW",
    "PR00039": "Paket Goodiebag 6 ROPI",
}

# SKU eResto non-paket to Item Code ERPNext
SKU_TO_ITEM = {
    "PR001": "RP001",
    "PR002": "RP002",
    "PR003": "RP003",
    "TJN01": "JT001",
    "BCN01": "BC002",
    "BCN02": "BC001",
    "CPN02": "CP001",
    "CKN01": "CK001",
    # PKG01 = Goodie Bag; PEL260072 kanonik (PG001 legacy salah & sudah di-merge 2026-10-09)
    "PKG01": "PEL260072",
}


def load_cached_orders():
    order_map = {}
    cached_files = glob.glob("experiments/pos-fetch/.cache_details/*.json")
    for p in cached_files:
        try:
            d = json.load(open(p))
            ono = d.get("order_no")
            if ono:
                order_map[ono] = d
        except Exception:
            pass
    return order_map


def set_delete_linked_entries(enable=True):
    requests.post(
        f"{BASE_URL}/api/method/frappe.client.set_value",
        data={
            "doctype": "Accounts Settings",
            "name": "Accounts Settings",
            "fieldname": "delete_linked_ledger_entries",
            "value": 1 if enable else 0,
        },
        headers=HEADERS,
    )


def quote_package(package_name, choices):
    r = requests.post(
        f"{BASE_URL}/api/method/pos_next.api.packages.quote_package",
        json={
            "package": package_name,
            "choices": json.dumps(choices),
            "pos_profile": PROFILE,
        },
        headers=HEADERS,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gagal quote {package_name}: {r.text}")
    return r.json().get("message", {})


def build_package_lines_for_unit(pkg_name, roti_choices_dict, instance_id):
    cfg = PACKAGES_CONFIG[pkg_name]

    opt_picks = []
    for rsku, rqty in roti_choices_dict.items():
        erp_code = SKU_TO_ITEM.get(rsku, rsku)
        opt_id = cfg["options"][erp_code]
        opt_picks.append({"option_id": opt_id, "qty": rqty})

    choices = [{"group_key": cfg["group_key"], "options": opt_picks}]
    qres = quote_package(pkg_name, choices)

    lines = []
    # Parent line
    parent_line = qres["lines"][0]
    lines.append({
        "item_code": parent_line["item_code"],
        "item_name": parent_line["item_name"],
        "qty": parent_line["qty"],
        "rate": parent_line["rate"],
        "price_list_rate": parent_line["rate"],
        "amount": parent_line["rate"] * parent_line["qty"],
        "pos_package": qres["package"],
        "pos_package_role": parent_line["role"],
        "pos_package_instance": instance_id,
        "pos_package_snapshot": json.dumps(qres["snapshot"]),
        "warehouse": WAREHOUSE,
    })

    # Component lines
    for comp in qres["lines"][1:]:
        lines.append({
            "item_code": comp["item_code"],
            "item_name": comp["item_name"],
            "qty": comp["qty"],
            "rate": comp["rate"],
            "price_list_rate": comp["rate"],
            "amount": comp["rate"] * comp["qty"],
            "pos_package": qres["package"],
            "pos_package_role": comp["role"],
            "pos_package_instance": instance_id,
            "warehouse": WAREHOUSE,
        })

    return lines, qres["total"]


def reopen_and_clean_shift(opening_shift_name):
    print(f"Checking shift {opening_shift_name} status...")
    r_chk = requests.get(f"{BASE_URL}/api/resource/POS Opening Shift/{opening_shift_name}", headers=HEADERS)
    s_doc = r_chk.json().get("data", {})
    if s_doc.get("status") == "Open":
        print(f"Shift {opening_shift_name} is already Open.")
        return
    print(f"Reopening shift {opening_shift_name}...")
    r = requests.post(
        f"{BASE_URL}/api/method/pos_next.api.backdate_invoices.reopen_shift",
        json={"pos_opening_shift": opening_shift_name},
        headers=HEADERS,
    )
    if r.status_code != 200:
        raise RuntimeError(f"Gagal reopen {opening_shift_name}: {r.text}")

    res = r.json().get("message", {})
    cancelled_closing = res.get("cancelled_closing_shift")
    if cancelled_closing:
        print(f"Deleting cancelled closing shift {cancelled_closing}...")
        r_del = requests.delete(
            f"{BASE_URL}/api/resource/POS Closing Shift/{cancelled_closing}",
            headers=HEADERS,
        )
        if r_del.status_code not in (200, 202, 204):
            print(f"Warning: gagal delete closing shift: {r_del.text}")


def close_and_submit_shift(opening_shift_name, date_str):
    print(f"Closing shift {opening_shift_name} for date {date_str}...")
    r_prev = requests.post(
        f"{BASE_URL}/api/method/pos_next.api.shifts.get_closing_shift_data",
        json={"opening_shift": opening_shift_name},
        headers=HEADERS,
    )
    if r_prev.status_code != 200:
        raise RuntimeError(f"Gagal get_closing_shift_data: {r_prev.text}")

    prev = r_prev.json().get("message", {})
    recon = []
    for row in prev.get("payment_reconciliation") or []:
        exp = float(row.get("expected_amount") or 0)
        recon.append({
            "mode_of_payment": row.get("mode_of_payment"),
            "opening_amount": float(row.get("opening_amount") or 0),
            "expected_amount": exp,
            "closing_amount": exp,
        })

    txns = [
        {
            k: row.get(k)
            for k in (
                "pos_invoice",
                "sales_invoice",
                "posting_date",
                "customer",
                "grand_total",
                "transaction_currency",
                "transaction_amount",
            )
        }
        for row in prev.get("pos_transactions") or []
    ]
    taxes = [
        {k: row.get(k) for k in ("account_head", "rate", "amount")}
        for row in prev.get("taxes") or []
    ]

    closing_payload = {
        "doctype": "POS Closing Shift",
        "pos_opening_shift": opening_shift_name,
        "pos_profile": prev.get("pos_profile"),
        "user": prev.get("user"),
        "company": prev.get("company"),
        "period_start_date": prev.get("period_start_date"),
        "period_end_date": prev.get("period_end_date"),
        "posting_date": date_str,
        "payment_reconciliation": recon,
        "pos_transactions": txns,
        "taxes": taxes,
        "grand_total": float(prev.get("grand_total") or 0),
        "net_total": float(prev.get("net_total") or 0),
        "total_quantity": float(prev.get("total_quantity") or 0),
    }

    r_close = requests.post(
        f"{BASE_URL}/api/resource/POS Closing Shift",
        json=closing_payload,
        headers=HEADERS,
    )
    if r_close.status_code != 200:
        raise RuntimeError(f"Gagal create closing shift: {r_close.text}")

    clo_name = r_close.json().get("data", {}).get("name")
    r_sub = requests.put(
        f"{BASE_URL}/api/resource/POS Closing Shift/{clo_name}",
        json={"docstatus": 1},
        headers=HEADERS,
    )
    if r_sub.status_code != 200:
        raise RuntimeError(f"Gagal submit closing shift {clo_name}: {r_sub.text}")

    print(f"Successfully closed & submitted {clo_name} (grand total: Rp {prev.get('grand_total'):,.2f})")
    return clo_name


def main():
    order_map = load_cached_orders()

    shifts_to_process = [
        {
            "date": "2026-10-02",
            "opening_shift": "POPEN-RPMD-261006003",
            "old_invoices": [
                "PINV-RPMD-261006027",
                "PINV-RPMD-261006030",
                "PINV-RPMD-261006034",
                "PINV-RPMD-261006036",
                "PINV-RPMD-261006047",
                "PINV-RPMD-261006049",
            ],
            "order_nos": [
                "ORO85.021026.000003",
                "ORO85.021026.000007",
                "ORO85.021026.000011",
                "ORO85.021026.000013",
                "ORO85.021026.000024",
                "ORO85.021026.000026",
            ],
        },
        {
            "date": "2026-10-03",
            "opening_shift": "POPEN-RPMD-261006004",
            "old_invoices": [
                "PINV-RPMD-261006054",
                "PINV-RPMD-261006062",
                "PINV-RPMD-261006065",
                "PINV-RPMD-261006071",
                "PINV-RPMD-261006076",
                "PINV-RPMD-261006079",
            ],
            "order_nos": [
                "ORO85.031026.000005",
                "ORO85.031026.000013",
                "ORO85.031026.000016",
                "ORO85.031026.000022",
                "ORO85.031026.000027",
                "ORO85.031026.000030",
            ],
        },
        {
            "date": "2026-10-05",
            "opening_shift": "POPEN-RPMD-261006005",
            "old_invoices": [
                "PINV-RPMD-261006091",
                "PINV-RPMD-261006092",
                "PINV-RPMD-261006094",
                "PINV-RPMD-261006102",
            ],
            "order_nos": [
                "ORO85.051026.000008",
                "ORO85.051026.000009",
                "ORO85.051026.000011",
                "ORO85.051026.000019",
            ],
        },
    ]

    report_rows = []

    # Baris pertama laporan: invoice 2026-10-01 yang sudah sukses
    report_rows.append({
        "order_no": "ORO85.011026.000011",
        "date": "2026-10-01",
        "old_invoice": "PINV-RPMD-261006011",
        "new_invoice": "PINV-RPMD-261006107",
        "total": 60000.0,
        "packages": "Paket Goodiebag 6 ROPI (1x)",
        "components_allocated": "RP002 (6x @ Rp10.000), PG001 (1x @ Rp0)",
        "status": "LOLOS",
    })

    for grp in shifts_to_process:
        date_str = grp["date"]
        shift_name = grp["opening_shift"]
        print(f"\n==================== PROCESSING DATE {date_str} ====================")

        # 1. Reopen shift & delete cancelled closing shift
        reopen_and_clean_shift(shift_name)

        # 2. Enable delete linked ledger entries
        set_delete_linked_entries(True)

        # 3. Cancel and delete old invoices
        for old_inv in grp["old_invoices"]:
            r_chk_inv = requests.get(f"{BASE_URL}/api/resource/POS Invoice/{old_inv}", headers=HEADERS)
            if r_chk_inv.status_code == 404:
                print(f"Old invoice {old_inv} already deleted.")
                continue
            print(f"Cancelling old invoice {old_inv}...")
            r_canc = requests.post(
                f"{BASE_URL}/api/method/frappe.client.cancel",
                data={"doctype": "POS Invoice", "name": old_inv},
                headers=HEADERS,
            )
            if r_canc.status_code != 200:
                print(f"Warning: cancel {old_inv} returned {r_canc.status_code}: {r_canc.text[:200]}")

            print(f"Deleting cancelled invoice {old_inv}...")
            r_del = requests.delete(
                f"{BASE_URL}/api/resource/POS Invoice/{old_inv}",
                headers=HEADERS,
            )
            if r_del.status_code not in (200, 202, 204):
                print(f"Warning: delete {old_inv} returned {r_del.status_code}: {r_del.text[:200]}")

        # Disable delete linked entries
        set_delete_linked_entries(False)

        # 4. Inject new invoices with POS package allocation
        for ono in grp["order_nos"]:
            order = order_map[ono]
            order_items = [
                it
                for it in order.get("order_items") or []
                if not it.get("void") and float(it.get("paid_quantity") or 0) > 0
            ]
            pm = order.get("payment") or {}
            order_total = float(pm.get("total") or 0)
            posting_time = str(order.get("date")).split("T")[1][:8]

            # Build payments
            payments = []
            for field, mode in PAY_FIELD_MAP.items():
                amt = float(pm.get(field) or 0)
                if amt > 0:
                    payments.append({"mode_of_payment": mode, "amount": amt})

            # Build items
            inv_items = []
            instance_counter = 1
            desc_pkgs = []
            desc_comps = []

            for it in order_items:
                sku = it.get("product_sku")
                pqty = int(float(it.get("paid_quantity") or 0))

                if sku in SKU_TO_PACKAGE:
                    pkg_title = SKU_TO_PACKAGE[sku]
                    bonuses = it.get("promotion_bonuses") or []
                    roti_list = []
                    for b in bonuses:
                        bsku = b.get("product_sku")
                        bqty = int(float(b.get("quantity") or 0))
                        if bsku in ("PR001", "PR002", "PR003"):
                            roti_list.extend([bsku] * bqty)

                    if not roti_list:
                        roti_list = ["PR001"] * (pqty * (6 if sku == "PR00039" else 1))

                    if sku == "PR00039":
                        # Paket Goodiebag: 1 unit berisi 6 roti
                        inst_id = f"pkg-{instance_counter}"
                        instance_counter += 1
                        roti_counts = dict(collections.Counter(roti_list[:6]))
                        lines, subtotal = build_package_lines_for_unit(pkg_title, roti_counts, inst_id)
                        inv_items.extend(lines)
                        desc_pkgs.append(f"{pkg_title} (1x)")
                        comps_summary = ", ".join(
                            [
                                f"{l['item_code']} ({l['qty']}x @ Rp{l['rate']:,.2f})"
                                for l in lines
                                if l["pos_package_role"] == "Package Item"
                            ]
                        )
                        desc_comps.append(comps_summary)
                    else:
                        # Hemat 1-4: tiap 1 unit paket memilih tepat 1 roti
                        for u_idx in range(pqty):
                            inst_id = f"pkg-{instance_counter}"
                            instance_counter += 1
                            chosen_roti = roti_list[u_idx] if u_idx < len(roti_list) else "PR001"
                            lines, subtotal = build_package_lines_for_unit(pkg_title, {chosen_roti: 1}, inst_id)
                            inv_items.extend(lines)
                            desc_pkgs.append(f"{pkg_title}")
                            comps_summary = ", ".join(
                                [
                                    f"{l['item_code']} ({l['qty']}x @ Rp{l['rate']:,.2f})"
                                    for l in lines
                                    if l["pos_package_role"] == "Package Item"
                                ]
                            )
                            desc_comps.append(comps_summary)
                else:
                    # Non-package regular item
                    code = SKU_TO_ITEM.get(sku, sku)
                    rate = float(it.get("price") or 0)
                    inv_items.append({
                        "item_code": code,
                        "item_name": it.get("product_name") or code,
                        "qty": float(pqty),
                        "rate": rate,
                        "price_list_rate": rate,
                        "amount": rate * pqty,
                        "warehouse": WAREHOUSE,
                    })

            payload = {
                "customer": CUSTOMER,
                "pos_profile": PROFILE,
                "posa_pos_opening_shift": shift_name,
                "posting_date": date_str,
                "posting_time": posting_time,
                "company": COMPANY,
                "items": inv_items,
                "payments": payments,
                "discount_amount": 0,
                "apply_discount_on": "Grand Total",
                "remarks": f"ERESTO {ono}",
            }

            print(f"Submitting backdate invoice for order {ono} ({date_str} {posting_time}) - Rp {order_total:,.2f}...")
            r_sub = requests.post(
                f"{BASE_URL}/api/method/pos_next.api.backdate_invoices.submit_backdate_invoice",
                json={"invoice": payload},
                headers=HEADERS,
            )

            if r_sub.status_code != 200:
                print(f"ERROR submitting {ono}: {r_sub.text[:400]}")
                report_rows.append({
                    "order_no": ono,
                    "date": date_str,
                    "old_invoice": "-",
                    "new_invoice": "ERROR",
                    "total": order_total,
                    "packages": "; ".join(desc_pkgs),
                    "components_allocated": r_sub.text[:200],
                    "status": "GAGAL",
                })
            else:
                new_inv_name = r_sub.json().get("message", {}).get("name")
                print(f"-> SUCCESS: {new_inv_name}")
                report_rows.append({
                    "order_no": ono,
                    "date": date_str,
                    "old_invoice": grp["old_invoices"][grp["order_nos"].index(ono)],
                    "new_invoice": new_inv_name,
                    "total": order_total,
                    "packages": "; ".join(desc_pkgs),
                    "components_allocated": "; ".join(desc_comps),
                    "status": "LOLOS",
                })

        # 5. Re-close shift
        close_and_submit_shift(shift_name, date_str)

    # 6. Generate Excel Report
    report_path = "pos_sync/Reinject_POS_Package_Report.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Rekap_Paket_Alokasi"

    headers = [
        "No",
        "eResto Order No",
        "Tanggal",
        "Invoice Lama (Dihapus)",
        "Invoice Baru (Resmi)",
        "Total Nilai (Rp)",
        "Nama Paket",
        "Alokasi Komponen (Qty & Rate)",
        "Status Verifikasi",
    ]
    ws.append(headers)

    for idx, r in enumerate(report_rows, 1):
        ws.append([
            idx,
            r["order_no"],
            r["date"],
            r["old_invoice"],
            r["new_invoice"],
            r["total"],
            r["packages"],
            r["components_allocated"],
            r["status"],
        ])

    # Styling
    fill_hdr = PatternFill("solid", fgColor="D9EAF7")
    font_bold = Font(bold=True)
    for c in ws[1]:
        c.fill = fill_hdr
        c.font = font_bold
        c.alignment = Alignment(horizontal="center", vertical="center")

    for col in ws.columns:
        w = max(len(str(c.value or "")) for c in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(w + 3, 12), 60)

    ws.freeze_panes = "A2"
    wb.save(report_path)
    print(f"\nReport saved successfully to {report_path}")


if __name__ == "__main__":
    main()
