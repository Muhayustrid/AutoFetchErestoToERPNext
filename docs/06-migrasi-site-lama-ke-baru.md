# Migrasi dokumen site-lama → site-baru (Oktober 2026) — SELESAI

Hasil: 2026-10-04/05. Jendela aktual **1–2 Okt 2026** (site lama tidak punya
WO/PO/PR/SO/DN/PL bertanggal 3–4 Okt). POSNext diabaikan. Pick List nihil
(terakhir 31 Agu).

## Hasil akhir (site baru, verifikasi LOLOS semua)

| DocType | Migrasi | Status |
|---|---|---|
| Work Order | 120/120 | 42 Completed + 78 In Process (submitted) |
| Stock Entry (terkait WO) | 218/218 | 120 transfer + 98 manufacture (submitted); manufacture 26.751 = site lama |
| Purchase Order | 86/86 | 43 draft + 42 submitted + 1 cancelled |
| Purchase Receipt | 27/27 | submitted |
| Sales Order | 17/17 | 16 submitted + 1 draft |
| Delivery Note | 46/46 | 11 submitted + 35 draft (shortfall stok outlet, disetujui user) |
| Master | 2 item + 9 supplier + 2 customer + 1 BOM Krim Kopi | dibuat + submitted |

Qty per item lama vs baru = sama untuk semua DocType (0 selisih).

## Keputusan user (fix)

- September diabaikan; DN/PR Oktober yg merujuk SO/PO September = dokumen mandiri.
- WO pakai BOM baru + item baru; WO dengan pergerakan stok (SE ikut).
- Seed awal disetujui: 4 bahan (Material Receipt 30 Sep) + top-up susulan.
- 12→35 DN shortfall = tetap draft (tanpa seed fiktif).
- DN-011026-007: customer Harapan Indah (FRC) dibuatkan (grup Outlet Franchise).
- Workflow site baru dinonaktifkan user sebelum migrasi.

## Pemetaan (aktual, sesuai implementasi)

- Item: kode sama; `BB260057` lama (Botol) → `BB26001`; `PEL260072/097` dibuat baru.
- BOM: `-002` → `-001` baru; `BOM-PJ260016-001` dibuat dari resep lama + submitted.
- Supplier kode → nama (case-insensitive); 9 dibuat baru.
- Customer via `customer_name` + alias `CUST260029/044`; jangan via kode `CUST-xxx`.
- Gudang `- ROPI` → `- JURI`; akun expense/cost-center ikut pola abbr per company.
- Pajak: `Purchase Tax [- ROPI]` → `Purchase Tax [- <abbr>]`;
  `11% (Include)` → `Purchase Tax (Termasuk Pajak) - JURI`.
- Link September dikosongkan, nomor lama dicatat (MR/PP/PO/SO-lama di description).
- Idempotency: WO `description`, SE `remarks`, PO/PR/SO/DN `title` = `ERESTO <nama-lama>`.
- Custom field WO disalin penuh (field sudah ada di site baru).
- Alamat/contact/letter head tidak ikut (dinamis).
- Item group `Produk Jadi` → `Produk Jadi Pabrik`.
- Setting disamakan dgn site lama: overproduction WO 50%.
- Perbaikan data: `BHP260033.default_inventory_account` dilengkapi (ikut BHP260035).

## File (`pos_sync/`)

`common.py` (klien REST + peta), `dump_window.py` (baca site lama → `window/*.json`),
`seed_opening.py`, `migrate_master.py`, `migrate_wo.py`, `migrate_po_pr.py`,
`migrate_so_dn.py`, `verify_migration.py` → `Migrasi_Okt2026.xlsx`
(Rekap/Validation/Failed). Env: `/tmp/eresto_mig.env`
(`ERPNEXT_OLD_API_KEY` = key site lama, sudah terverifikasi).

## Catatan teknis (pelajaran)

- `rename_doc` harus form-encoded (bukan JSON).
- Material Receipt backdate memakai `qty_after_transaction` absolut utk Bin —
  cancel seed merusak Bin; perbaikan via Stock Reconciliation ke saldo ledger.
- Validasi negative-stock memakai Bin saat ini (bukan replay kronologis) —
  urutan submit: transfer dulu, manufacture kemudian.
- PO/SO/DN tidak punya `remarks` — kunci di `title`.
- Customer `CUST-260029/044` beda arti di kedua site — selalu via `customer_name`.

## Penyelesaian penuh (2026-10-05, sesi kedua)

Target "migrasi harus tuntas" tercapai — DN tidak lagi menggantung sebagai draft:

- 103 Stock Entry non-WO jendela (58 MT + 36 Manufacture + 4 MI + 3 MR + 2 Repack)
  ikut dimigrasi — ternyata sumber inflow stok ke gudang barang jadi; tanpa ini
  DN tidak bisa submit.
- Opening stock direplikasi dari data site lama (bukan tebakan):
  titik pembuka = saldo lama − neto gerakan jendela, di-set via Stock
  Reconciliation per gudang (JURI 6 gudang + RPMD/RQLY; Gudang Produksi pakai
  RECO ber-tanggal hari-migrasi karena SE terposting dengan tanggal submit).
- Hasil: DN **46/46 submitted**; SE 308 submitted (321 − 13 Repack/Manufacture
  bundel yang di-skip — di model baru bundel non-stock, konsumsi komponennya
  terjadi otomatis saat DN jual; memigrasi SE-nya = dobel konsumsi);
  WO 98 Completed + 22 In Process = persis sumber; PO/PR/SO persis sumber.
- Manufacture (stock item) 45.777 = 45.777 (LOLOS).
- Paritas saldo 9 gudang: 388/461 pasangan persis; 73 selisih terklasifikasi
  semua: 22 item non-stock di model baru, 38 gerakan 3–4 Okt outlet (luar
  jendela), 13 item dihapus dari master baru/rename/batch (BB260057→BB26001
  paritas cocok lewat mapping).
- Keterbatasan tercatat: 14 PR + ±308 SE + 1 DN memakai tanggal posting hari
  migrasi (Frappe reset posting_date saat submit tanpa set_posting_time);
  dokumen lain (PO/SO/WO/DN 45) tanggal sumber terjaga. 13 SE bundel di-skip
  tercatat di /tmp/se_skip.json (sesi) — daftar juga di Excel Migrasi.
