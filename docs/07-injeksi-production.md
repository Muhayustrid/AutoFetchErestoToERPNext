# 07 — Injeksi data ke PRODUCTION (ropierpnext.frappe.cloud)

Sumber: site LOKAL `http://erp.localhost:8081` (hasil migrasi site lama,
docs/06), jendela transaksi **1–2 Oktober 2026**. Tujuan:
`https://ropierpnext.frappe.cloud` (Frappe 16.36.1 / ERPNext 16.37.0, IDR).

Dijalankan dan diverifikasi **2026-10-05** (sesi kedua). Hasil akhir:
paritas penuh dengan lokal — dokumen 100% dan **Bin 697 pasangan tanpa
selisih** (TJBK dikecualikan, data uji pilot lokal).

## Konsep: opening dihitung, bukan disalin

Prod kosong total (0 SLE). Gagal submit karena stok negatif terjadi bila
dokumen stok "drift" dari posisi Bin. Karena itu stok pembukaan **dihitung
per (item, warehouse)** agar sisa akhir persis:

```
opening = bin_final_lokal − Σ SLE_lokal(dokumen yang diinjeksi)
```

- Yang diinjeksi = SE `ERESTO MAT-STE-*` (308) + PR (27) + DN (46);
  voucher unik 381. Efek scaffolding lokal (SEED/pilot) otomatis terserap
  ke dalam opening.
- Hasil: 353 baris opening → 8 RECO `Opening Stock`, posting 2026-09-30
  23:59:59, expense account `1171.000 - Pembukaan sementara - <abbr>`.
- Warehouse TJBK (data uji POS pilot lokal) dikecualikan — tidak ada di prod.
- **Tanggal dokumen stok (PR/SE/DN) tidak di-backdate**: ERPNext memvalidasi
  negative stock per titik waktu (`validate_negative_stock`, "current datetime
  onwards"), jadi urutan submit = urutan waktu = rantai valid. Dokumen stok
  tercap waktu submit (2026-10-05); dokumen non-stok (WO/PO/SO) memakai
  tanggal aslinya.

## Urutan injeksi (semua idempoten via marker `ERESTO <nama-lama>`)

1. **prod_master.py** — Manufacturing Settings `overproduction_percentage_
   for_work_order` 0→50; 8 company baru anak `OUTLET` (6 FRC + RSUP
   Palembang + Jambi Sarulangun); customer internal + allow JURI; 9 supplier
   baru; FY 2026; baris MoP 8 company; 8 item baru; BOM-PJ260016-001.
2. **prod_itemdefs.py** — 159 baris `Item Default` akun inventory JURI
   (sumber: lokal; fallback pola per item_group) + baris RPMD/RQLY yang
   kosong; 11 item yang di lokal non-stock disamakan (`is_stock_item=0`)
   — prod memakai `enable_item_wise_inventory_account`; terakhir *cache
   touch* semua Item (validasi memakai `get_cached_doc`, TTL 1 jam, insert
   child lewat REST tidak memicunya).
3. **prod_opening.py** — 8 RECO Opening Stock (submitted).
4. **prod_docs.py** — WO (120) → PO (86; 43 draft tetap draft, 1 cancelled
   di-cancel) → SO (17; 1 draft) → PR (27, relink `purchase_order`) →
   SE 308 kronologis (Material Receipt → MTFM → Manufacture → Transfer →
   Repack → Issue; relink `work_order`; Manufacture non-JURI dilewati —
   tidak ada di data) → DN (46, relink `against_sales_order`).
   Kegagalan stok di-defer, diulang maks 5 ronde.
5. **prod_verify.py** — hitung + baris item + docstatus per doctype,
   WO produced_qty, paritas Bin → `pos_sync/Injeksi_Prod.xlsx`.

## Hasil verifikasi (2026-10-05)

| Dokumen | Jumlah | Status |
|---|---|---|
| Work Order | 120/120 | 98 Completed + 22 In Process; produced 26.628 = 26.628 |
| Purchase Order | 86/86 | 42 submitted / 43 draft / 1 cancelled |
| Sales Order | 17/17 | 16 submitted / 1 draft |
| Purchase Receipt | 27/27 | semua submitted |
| Stock Entry | 308/308 | semua submitted (2352 baris item) |
| Delivery Note | 46/46 | semua submitted |
| Bin | 697 pasangan | **0 selisih** vs lokal |

## Jebakan yang ditemukan (reusable)

- `frappe.client.set_value` untuk Single doctype butuh parameter `name`
  (bukan `docname`).
- Child row (`Item Default`) valid dibuat via POST `/api/resource/Item Default`
  `{parent, parenttype, parentfield, ...}`; tapi **cache dokumen Item tidak
  ikut bersih** — validasi berikutnya masih lihat data lama. Obat: PUT/set_value
  pada parent (memicu `doc.save()` → clear cache).
- `enable_item_wise_inventory_account` aktif di prod → SEMUA baris stok butuh
  default inventory account per item; item tanpa baris Item Default langsung
  ditolak saat submit.
- Customer prod beda kapitalisasi ("Harapan indah (FRC)" vs lokal
  "Harapan Indah (FRC)") dan duplikat → pencocokan case-insensitive +
  pilih kode terkecil, dicatat di `state.json`.
- Baris MoP (Debit Card) untuk company baru sudah ada otomatis dari template
  tapi menunjuk akun salah (Kas USD) → timpa dengan akun benar.
- `is_cancelled` pada SLE penting bila membandingkan ledger vs Bin di lokal
  (3.364 baris cancelled).

## File

- Kode: `pos_sync/prod_common.py`, `prod_dump.py`, `prod_master.py`,
  `prod_itemdefs.py`, `prod_opening.py`, `prod_docs.py`, `prod_verify.py`.
- Dump sumber + meta + state: `pos_sync/prod_src/` (state idempotensi +
  alias customer di `state.json`).
- Laporan: `pos_sync/Injeksi_Prod.xlsx`.
- Kredensial: `/tmp/eresto_mig.env` (lokal) + `/tmp/eresto_prod.env` (prod) —
  jangan pernah masuk repo.
