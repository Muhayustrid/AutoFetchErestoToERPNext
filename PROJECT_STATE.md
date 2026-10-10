# PROJECT_STATE.md — eResto → ERPNext

> Update tiap selesai sesi kerja, bukan tiap commit. Jangan taruh token/password.
> Aturan tetap (style, constraint, alur) ada di `AGENTS.md`; file ini untuk hal yang sering berubah.

## Ringkasan

Migrasi paralel POS eResto → ERPNext untuk ~160 outlet (Ropi). eResto tetap jalan
sampai cutover; ERPNext diisi data order, refund, produksi, dan pembelian via API.
Target user: tim finance/operasional Ropi — single operator dibantu AI agent.

## Status (2026-10-09)

Fase: **setup lokal + pilot OK + agregat OK + migrasi site-lama→baru OK +
injeksi production 1–2 Okt OK + POS INVOICE LOKAL 1–5 Okt OK +
REPLAY PENUH 244 WO 1–6 Okt JURI OK + PRINT FORMAT 10/10 OK +
MIGRASI & REKONSILIASI PENUH PO & PR 1–7 OKT JURI OK (97 PO / 73 PR) +
RANTAI INTERCOMPANY PO-SO-DN-PR DELANGGU OK + MASTER ASSET 42/42 OK +
MIGRASI PO OUTLET→JURI 25 SEP–7 OKT OK (252 PO) +
MIGRASI SO + DN OUTLET→JURI 1–8 OKT OK (122 SO / 126 DN) +
MIGRASI PRODUCTION PLAN & WORK ORDER 8 OKT JURI OK (PP261008001 / 62 WO) +
INJEKSI STOK TRAINING VIA MATERIAL RECEIPT DELANGGU OK (SE-MR-261008001 / 30 ITEM) +
TARIK PO DIFAKTUR OKT 2026 OK (66 PO sebelum Okt, `fetch_po_invoiced_okt.py`) +
MIGRASI PI DIVISI SENTRAL OKT 2026 OK (7 faktur: 5 PI baru + 2 existing, PO+PR Sinar, `migrate_pi_central_okt.py`) +
AUDIT BANDING PO PT. JURI LAMA↔BARU OK (280 vs 124; 26 draft eResto duplikat PO native submitted, 3 pasangan stok dobel, `compare_po_juri_lama_baru.py`) +
BERSIH-BERSIH DUPLIKAT PO PT. JURI OK (26 draft dihapus + 12 dokumen di-cancel, Bin 3 item turun tepat, `bersih_po_juri.py`) +
AUDIT STOCK BALANCE 30 SEP LAMA↔BARU OK (revisi scope 2026-10-09: HANYA company PT. JUARA ROTI INDONESIA — 418 posisi item×gudang: 232 sama persis, 186 beda semua terjelaskan per kategori, `compare_stock_sep30.py`; keputusan angka utk 16 drift buku-vs-fisik + PEL260087 menunggu user) +
ISI SALDO 30 SEP 23:00 KE BARU OK (170 posisi di 13 gudang via 13 RECO + 3 gudang & 38 item baru; 377/407 posisi = LAMA @23:00; 30 posisi pending audit; `fill_opening_sep30.py`) +
LUNAS 30 SEP 23:00 & EOD LAMA=BARU + HAPUS LOAN PINJAM STOCK OK (48+6+6+2+7 selisih ditutup via 12 RECO `RECO-JURI-261009016..028,032..034`; 6 item Dough/Deactivate dibuat+batch; loan `SE-MR-261009001-1` DICANCEL, CS kembali 0/positif; EOD Sep30 = 0 selisih; 0 Bin negatif JURI; 226 Item Default `Stores - JURI`→`Gudang Bahan Baku - JURI`; top-up operasional `RECO-JURI-261009029/030/031`, `fixsep30.py`/probe `/tmp/zprobes/`) +
	MIGRASI PO ERESTO 8-9 OKT JURI OK (`POGPT.081026.001` submitted + `POGPK.021026.001` draft, 11 PO gudang dikecualikan, `migrate_po_eresto_8_9_okt.py`) +
	TARIK PO eRESTO GUDANG JAKARTA 9 OKT OK (12 PO / Rp 109.844.645, ID identik, 3 submitted + 9 draft; PO140.091026.002 + BB0312→PJ260009 ditambahkan 9 Okt sore, `migrate_po_gudang_jakarta_9okt.py`) +
	HAPUS COMPANY OUTLET PAMERAN OK (cascade on_trash + prep 1 baris supplier & 5 baris ECT; backup `audit_logs/backup_OUTLET_PAMERAN_261009_092439.json`, `delete_outlet_pameran.py`) +
	SINKRONISASI TAG PO PT. JURI LAMA→BARU OK (38 PO berhasil dipasangi tag pesanan Shopee, `sync_po_tags.py`) +
	PERBAIKAN WO & SE PRODUCTION PLAN 9 OKT JURI OK (61 WO target Cold Storage & sumber Gudang Produksi, 2 MTF + 25 MFG + 35 MTFM dibatalkan & dibuat ulang dengan gudang benar, 0 minus di Stores & Produksi, adonan masuk Cold Storage, `fix_production_plan_09okt.py`) +
	FIX "Persiapan Gagal" WO KRIM KOPI 9 OKT OK (WO-JURI-261009061 rebind baris 60→61 + ordered_qty 60/61 diluruskan; submit WO-060 bebas dari gate `ProductionPlanWorkOrderQuantities` native v16; `fix_wo_061_rebind_9okt.py` — dry-run default, `--execute`, idempoten) +
	BERSIH 30 DOKUMEN CANCELLED PT. JURI OK (PI 3 + PO 6 + PR 4 + DN 3 + SE loan 3 + RECO 9 + MR 2; backup 30 JSON; ledger sweep 0; Bin net-zero; `bersih_dokumen_cancelled.py`) +
	MERGE ITEM GOODIE BAG OK (PG001 'Goodie Bag 6 Roti' -> PEL260072 'Goodie Bag', rename_doc merge=1; POS Package & 4 POS Invoice RPMD ikut pindah; Bin pasca-merge dikoreksi: GBJ 43.217 / RPMD 71 / TRNG 75 / Jakarta 6.194; `merge_goodie_bag_items.py` + `fix_goodie_bins_post_merge.py`) +
	STOCK MINUS 0 & allow_negative_stock=0 PERMANEN OK (repack Telur Cair `SE-RPK-261009006` 139835->0 g; smoke submit minus DITOLAK NegativeStockError; `fix_stock_minus_9okt.py`) +
	AUDIT PI SITE LAMA OK (5 PI lama, 0 termigrasi ke BARU — PI lama trial, jangan migrasi) +
	KONSOLIDASI RECO JURI TAHAP-1 OK (akun 1171/5110 dibenahi; 7 gudang non-GBJ jadi 1 opening per gudang @30 Sep 23:00 `RECO-JURI-261009042..048`; SR7 026→049, 030→SE-MR-261009002, 031→SE-MR-261009003, 033→050, 029 no-op; 13 dok cancelled dihapus; sisa 7 gudang + SR7 032/034 MENUNGGU IZIN flag; `konsolidasi_opening_reco.py`) +
	HAPUS WAREHOUSE TESTING DI 2 SITE OK (LAMA: Gudang Finished Goods Testing / Gudang Testing Manufacture / WIP Testing `- ROPI`; BARU: `Gudang Testing Manufacture - JURI` & `WIP Testing - JURI`; +4 SE +2 draft +2 RECO +26 RIV; semua 404 & 0 sisa; `hapus_warehouse_testing.py`) +
	MIGRASI PO222.091026.001/.002 (RS MUHAMMADIYAH SELOGIRI) OK (2 PO / Rp 8.036.849, ID identik, submitted; company RSMS baru di-onboard + FY 2026 + allowed supplier + customer internal, `migrate_po_selogiri_9okt.py`)** —
- **Injeksi Stok Company TRAINING via Material Receipt (SE-MR-261008001 / 30 Item): SELESAI 2026-10-08.**
  Atas instruksi user ("memasukan stock di eprnext baru pada company training. pake stock reconcilation di pku delanggu, tapi ini material receipt aja!").
  - 1 Stock Entry berjenis Material Receipt `SE-MR-261008001` dibuat dan disubmit (`docstatus = 1`) pada Company `TRAINING` ke warehouse `Stores - TRNG`.
  - Seluruh 30 item persediaan fisik dari seluruh Stock Reconciliation Delanggu (`RECO-RPMD-261006001`, `002`, `003`, `261008001`) dimasukkan dengan quantity dan valuation rate persis (total Rp 6.277.422,89).
  - 30 SLE aktif diposting tanpa kendala akun GL (`enable_perpetual_inventory = 0` di TRAINING). Skrip: `pos_sync/create_training_material_receipt.py`.
- **Production Plan & Work Order 8 Okt (PP261008001 / 62 WO): SELESAI 2026-10-08.**
  Atas instruksi user ("menarik production plan 8oktober 2026 disite lama, trus kan konek ke workordernya juga").
  - 1 Production Plan `PP261008001` (docstatus 1 Submitted, 62 baris `po_items`, planned qty 29.578 Pcs) berhasil dibuat dan disubmit ke Cloud Baru.
  - 62 Work Order (`MFG-WO-2026-04238` s/d `MFG-WO-2026-04299`) dibuat dengan ID identik (via rename_doc), berstatus Draft (`docstatus = 0`, `status = Draft`) persis seperti data asli site lama, terhubung 1-to-1 ke `PP261008001` dan baris `po_items`-nya.
  - Di `production_app`, seluruh 62 WO tampil aktif di tahap **Persiapan** (`stage: persiapan`), siap dijalankan oleh operator pabrik.
  - Verifikasi lintas-site 62/62 LOLOS 100% (0 selisih, 0 gagal, 0 duplikat). Script: `pos_sync/migrate_wo_08okt.py`.
- **SO + DN Outlet → PT. JURI (1–8 Okt): SELESAI 2026-10-09.**
  Rantai balik PO: 122 Sales Order (JURI → customer internal outlet) +
  126 Delivery Note, dengan ID identik, docstatus persis
  (SO 122 Submitted; DN 123 Submitted + 3 Cancelled), ke Cloud Baru.
  Jangkar = DN `posting_date` 1–8 Okt; SO yang ditarik DN ikut walau
  tanggalnya lebih tua (mis. DN 1 Okt atas SO 29/30 Sep). Total
  Rp 965.474.771 (SO) / Rp 988.939.091 (DN). 0 gagal, 0 duplikat.
  Link native 100%: SO → PO (`inter_company_order_reference` + baris
  `purchase_order`/`purchase_order_item`), DN → SO (`against_sales_order`
  + `so_detail`). Cross-check independen 11/11 LOLOS; self-test mapper 8/8.
  Laporan: `pos_sync/Laporan_Migrasi_SO_DN_Outlet_ke_JURI.xlsx`
  (Validation SELURUH CEK LOLOS, 26 dokumen di-skip terdokumentasi).
  Script: `pos_sync/migrate_outlet_so_dn_to_juri.py`
  (`--dump/--prep/--so/--dn/--verify/--dry-run/--only/--limit/--workers`).
- **Work Order 1–7 Okt JURI & Zero Negative Stock (306 WO, 100% Selesai & Non-Negatif): SELESAI 2026-10-08.**
  Seluruh 306 WO (5 Production Plan: `PP261001001/002/005/006/007`) terdaftar penuh dengan seluruh 5 tahapan `production_app` lengkap
  (Persiapan, Material, Pre-Packing, Post-Packing, Finish). 283 Selesai (Completed), 23 Berjalan (In Process batch 7 Okt). 0 selisih tahapan vs site lama.
  Seluruh 13 Bin negatif sebelumnya berhasil dibersihkan via 3 RECO penyesuaian/opening (`RECO-JURI-261008001`, `RECO-JURI-261008002`, `RECO-RPMD-261008001`).
  Cek live: **0 Bin negatif di seluruh warehouse JURI & RPMD**. Laporan: `pos_sync/Laporan_Migrasi_WO_1_7_Okt2026_Final.xlsx`. Script: `pos_sync/execute_fix_wip_and_wos.py`.
- **PO Outlet → PT. JURI (252 PO, 25 Sep–7 Okt): SELESAI 2026-10-08.**
  Seluruh PO dari 114 company outlet ke supplier `PT. JUARA ROTI INDONESIA`
  (site lama: `SUP260008`) termigrasi ke Cloud Baru dengan ID identik,
  docstatus persis (142 Submitted + 110 Draft), total Rp 1.763.981.574.
  **Gudang target = `Stores - <ABBR>` per company** (revisi user 2026-10-08;
  bukan `Goods In Transit - <ABBR>` bawaan site lama) — 252/252 header +
  seluruh baris, 0 sisa Transit.
  0 gagal, 0 duplikat; cross-check independen LOLOS
  (jumlah, nilai, docstatus, company, baris item, duplikat). Round-trip:
  nilai sumber 1.764.139.574 − Rp 158.000 (1 baris di-skip terdocumentasi)
  = 1.763.981.574 tepat. Rerun script = 252 SKIP_EXISTS (idempoten).
  Laporan: `pos_sync/Laporan_Migrasi_PO_Outlet_ke_JURI.xlsx` (Validation: LOLOS).
  Script: `pos_sync/migrate_outlet_po_to_juri.py --dump/--prep/--migrate/--verify`.
- Seluruh 97 Purchase Order (63 PO 1-7 Okt + 34 PO historis rujukan PR) = 97 PO di Cloud (`ropierpnext.frappe.cloud`), 0 duplikat, 100% ID identik bawaan lama.
- Seluruh 73 Purchase Receipt (1-7 Okt) berstatus Submitted, direlink penuh ke PO pasangannya (status PO update terhubung), gudang `- JURI`, 0 duplikat, 100% ID identik bawaan lama.
- Rantai intercompany Delanggu 1-7 Okt selesai penuh di site Lama & Baru Cloud (`ropierpnext.frappe.cloud`):
  PO `POO85.021026.001` (Delanggu) -> SO `SLS-051026-006` (JURI) -> DN `DN-051026-008` (JURI) -> PR `PR-071026-013` (Delanggu, eResto `PCO85.051026.001`).
  Seluruh 4 dokumen berstatus Submitted (`To Bill`), cross-link native 100% klop, per_received/per_delivered 100%, stok Stores - RPMD terupdate.
- Seluruh 42 dokumen master Asset (`ACC-ASS-2026-00001` s/d `00042`) termigrasi ke Cloud Baru lengkap dengan serial number dan user.
- Laporan audit lengkap di `pos_sync/Laporan_Migrasi_PO_PR_1_7_Okt2026.xlsx` (Validation: LOLOS).

- **Sesi 6 (2026-10-06):** Migrasi JURI 1 Okt 2026 ke site baru cloud (`ropierpnext.frappe.cloud`):
  - **Purchase Order (23 PO):** 6 PO per 1 Okt 2026 + 17 PO historis (Sep) yang memiliki Purchase Receipt pada 1 Okt 2026. Seluruh 23 PO termigrasi dengan nomor ID identik (`PUR-ORD-...` / `PO-...`), remarks referensi, supplier termutasi nama baru, total nilai cocok 100%.
  - **Purchase Receipt (22 PR):** Seluruh 22 PR per 1 Okt 2026 atas nama PT. JUARA ROTI INDONESIA disubmit dengan ID identik (`PR-...`), direlink penuh ke PO pasangannya (status PO update terhubung), gudang `- JURI`, dan remarks terpasang.
  - **Work Order (60 WO):** *Digantikan* oleh replay penuh 1–6 Okt di bawah (WO 1 Okt lama tanpa SE di-refresh ulang via alur plan → WO → SE).
  - **REPLAY PENUH 244 WO 1–6 Okt 2026 (`pos_sync/migrate_wo_full_okt.py`, docs/09):** seluruh 244 WO pabrik direplay menurut alur riil production_app: 4 Production Plan (`PP261001001/002/005/006`) dibuat + 244 WO dari plan (ID identik, custom field lengkap, 221 Completed + 23 In Process persis sumber, Σ produced 81.620 = 81.620) + 85 MR serah terima (hook app otomatis `Diminta Gudang` → `Terkirim` via SE) + 629 SE (244 TFM + 244 MFG + 122 MT + 8 MI + 6 Repack + 5 Receipt). Verifikasi **244/244 LOLOS, 0 selisih** (`Laporan_Migrasi_WO_1_6_Okt2026.xlsx`); box 1–3 tidak ditulis (dipensiunkan app) — arsip di sheet `Arsip_Box_Lama`. Laporan lama `Laporan_Migrasi_PO_PR_WO_1Okt2026.xlsx` bagian WO digantikan laporan baru ini.

- **Sesi 4 (2026-10-05):** injeksi POS Invoice lokal 38.852 order eResto
  (1–5 Okt) → 38.168 invoice + 553 outlet-hari; skip 684 order
  (void/tanpa bayar 401; SKU butuh item baru 222 [19 SKU];
  outlet baru `RS RIDHOKA SALMA CIKARANG` 47 — company belum dibuat;
  total beda 10; total nol 4) — semuanya di sheet `Skipped`, tidak ditebak.
  Tiga fase (data 5 Okt mengalir): 29.919 (mapping awal) → 32.315 (setelah
  24 SKU di-ACC, docs/02) → 38.168 (`--refresh-list` tarikan 20:47,
  +5.973 order 5 Okt). Baris rate < price list dikirim dengan diskon
  eksplisit + `discount_confirmation_code` (`Z86BKK3D`) agar lolos gate
  SEC-04. Jebakan: satu user = satu shift terbuka (grup berurutan);
  backdate butuh `allow_change_posting_date`; valuation rate wajib saat
  stok 0 (`set_item_valuation.py`, SLE site lama); race `tabSeries` →
  retry serial; `reopen_shift` untuk shift yang sudah tertutup.
  `PINV-TJBK-261004001` (pilot) dibatalkan; draft/shift uji UI user tidak
  disentuh. Flag sementara sudah dipulihkan ke 0.
- **Catatan FRC:** keputusan docs/02 "FRC tidak ikut injeksi" baru
  diterapkan di jalur JE agregat (27 JE FRC masih submitted, belum
  dibatalkan); lane POS Invoice lokal masih memuat 554 invoice FRC
  (Rp18.351.000). Perlu keputusan user apakah ikut dibatalkan.

- **Selesai sesi 3 (2026-10-05):** injeksi prod via `pos_sync/prod_*.py` —
  8 company FRC/RSUP/Jambi (anak `OUTLET`) + customer internal + allow JURI;
  9 supplier; 8 item; BOM Krim Kopi; 159 item_defaults + 11 non-stock;
  8 RECO Opening Stock (formula opening = bin lokal − ΣSLE dokumen yang
  diinjeksi); 120 WO + 86 PO + 17 SO + 27 PR + 308 SE + 46 DN.
  `overproduction_percentage_for_work_order` prod 0→50 (samakan lokal).
  Workflow PO/PR dinonaktifkan user sebelum injeksi.
- **Selesai 2026-10-05:** migrasi site-lama→baru jendela 1–2 Okt (docs/06) —
  120 WO + 218 SE + 86 PO + 27 PR + 17 SO + 46 DN, qty 0 selisih;
  35 DN jadi draft (shortfall stok outlet); kode `pos_sync/`
  (dump/seed/master/wo/po-pr/so-dn/verify).

- **Selesai:** fetch eResto (list/detail/refund/recap/productions) + Excel;
  mapping SKU (51 baris; 24 ACC user 2026-10-05 — docs/02); ERPNext lokal:
  company baru (RSUP Palembang + 7 FRC aktif),
  customer internal, supplier JURI, Mode of Payment, Fiscal Year;
  16 Price Group (harga per tier); 322 POS Profile (161 SHIFT 1 + 161 SHIFT 2)
  dengan 4 metode bayar; 2 Shift Group; 6 profil duplikat dihapus.
  **Pilot 2026-10-04:** order Kebumen `OR045.031026.000001` (Rp36.000)
  → `PINV-TJBK-261004001` submit (GL balance, 5 SLE) →
  `POCLO-TJBK-261004001` closing (diff 0). Temuan: item jual = Product
  Bundle (komponen perlu seed stok lokal); posting_date = hari POST
  (backdate HO belum dicoba).
  **Stok opname 2026-10-04:** 93 dokumen `SO Monthly September`
  (91 outlet, 2.782 baris, checksum 93/93 OK;
  `Auto stock balancing` diskip) → `Stock_SO_Monthly_September.xlsx`.
  **Mapping stok 2026-10-04:** 47 SKU → 39 target + 8 skip
  (`Template_Mapping_Stok.xlsx`); 6 item baru `BB260057-62` dibuat;
  RR* barang jadi diarahkan ke PJO* matang.
  **Injeksi agregat 2026-10-04 (malam):** `inject_sales_aggregate.py`
  → 418 Journal Entry `ERESTO-<branch>-<date>` submitted
  (1 JE uji dibatalkan), 27.366 order → 27.057 bayar + 309 void/nol
  diskip, Rp717.395.000 (Dr Kas Kasir 508.027.000 + Dr Qris/Debit/
  Kredit 209.368.000, Cr Penjualan 717.395.000; GL balance 0,
  selisih 0 vs eResto). Rerun = 418 sudah-ada, 0 duplikat.
  Rekap 4 Okt naik 415 → 728 order (data siang belum masuk semua).

- **Jalan:** fetch eResto per outlet/hari; bulk setup ERPNext via API key
  (idempoten); injeksi POS Invoice lokal idempoten (marker `ERESTO <order_no>`;
  rerun aman; `--refresh-list` bila data hari berjalan masih mengalir).
- **Belum/rusak:** 19 SKU POS butuh item baru (CM01/MC01/MC02, CP02, dst —
  daftar di docs/02); outlet baru `RS RIDHOKA SALMA CIKARANG` belum punya
  company; keputusan FRC utk lane POS Invoice lokal (554 invoice terposting);
  mapping produksi (PJO/BOM) belum.

## Tech stack

- Python 3.14 (`.venv`) — requests, pandas, openpyxl. Tanpa build step.
- ERPNext 16 / Frappe 16 + app POSNext — Docker lokal, port 8081, site `erp.localhost`.
- MariaDB 11.8 + Redis (container, ikut frappe_docker).
- Layanan eksternal: eResto API (`ropi.eresto.id`) v3 orders / v2 refunds,
  productions, price_groups, purchases (legacy).

## Struktur kode

- `experiments/pos-fetch/` — spike fetch (`test_*.py`) + Excel/JSON output.
- `experiments/*.py` — setup ERPNext: `create_companies/rsup/frc.py`,
  `apply_pos_bulk.py`, `update_pos_payments.py`, `create_shift2.py`,
  `delete_duplicate_profiles.py`, `build_pos_matrix/report.py`, `fetch_tier_prices.py`,
  `pilot_post_one.py` (pilot 1 order), `fetch_so_monthly.py` (stok opname),
  `build_stok_mapping.py` + `create_stok_items.py` (mapping stok),
  `inject_sales_aggregate.py` (injeksi agregat JE per outlet-hari),
  `pos-fetch/fetch_details_bulk.py` (detail SKU massal, cache resume).
- `experiments/*.xlsx|csv|json` — artefak keputusan (mapping SKU, tier, laporan).
- `docs/` — 01 eResto API, 02 mapping, 03 desain sync produksi,
  04 cara kerja penjualan POSNext, 05 alur barang dough→matang→bundle,
  06 migrasi site-lama→baru (Okt 2026, selesai),
  07 injeksi production (Okt 2026, selesai),
  08 injeksi POS Invoice lokal 1–5 Okt (backdate HO + shift).
- `KNOWLEDGE.md` — peta sistem untuk AI/engineer baru (eResto + ERPNext
  baru/lama: URL, endpoint, aturan, jebakan) + skill
  `.agents/skills/eresto-erpnext/` supaya AI pengguna lain langsung paham
  setelah clone.
- `dokumen/` — template import (Mode of Payment, Fiscal Year).
- `Backup SIte Production/` — read-only, jangan disentuh.
- `pos_sync/` — kode migrasi site-lama→baru (lihat docs/06):
  `common/dump_window/seed_opening/migrate_master/migrate_wo/
  migrate_po_pr/migrate_so_dn/verify_migration.py` + `window/*.json` +
  `Migrasi_Okt2026.xlsx`.
- `pos_sync/prod_*` — injeksi ke PRODUCTION (lihat docs/07):
  `prod_common/prod_dump/prod_master/prod_itemdefs/prod_opening/
  prod_docs/prod_verify.py` + `prod_src/*.json` (dump sumber + meta + state) +
  `Injeksi_Prod.xlsx`. Env: `/tmp/eresto_mig.env` (lokal) +
  `/tmp/eresto_prod.env` (prod) — jangan commit.
- `pos_sync/inject_pos_invoice.py` + `pos_sync/set_item_valuation.py` —
  injeksi POS Invoice + Opening/Closing Shift ke site LOKAL (lihat docs/08);
  output `PosInvoice_Lokal_*.xlsx` + `pos_invoice_state.json`.
- `pos_sync/migrate_wo_full_okt.py` — replay 244 WO JURI 1–6 Okt ke cloud
  (lihat docs/09): `--dump` → `--plans` → `--wos` → `--mrs` → `--ses` →
  `--verify [--repair]`; dump cache di `pos_sync/wo_dump/`, laporan
  `Laporan_Migrasi_WO_1_6_Okt2026.xlsx`. Semua idempoten (skip yang sudah ada).
- Tidak ada entry point tunggal; semua script CLI terpisah.

## Task aktif

- Desain `pos_sync/` produksi dari pola pilot (fetch → mapping → shift
  → invoice → closing; idempotency `order_no`).
- Sinkron produksi eResto → Stock Entry per sesi masak, mengikuti
  resep terukur docs/05 (Ropi 12/Gempi 3/Croissant 6 per pack dough);
  bahan pendamping (krim/gula) menunggu probe resep resmi.
- Keputusan 64 SKU unmapped POS (MC01/MC05, AIR03, TJ02, PR00072–75, PG002–004, dll).
- Coba jalur backdate HO (posting_date = tanggal eResto asli).
- Konfirmasi sisa mapping stok: BB0066 Goodie Bag→PG001; asumsi
  Pack dough→Pcs 1:1. (`PJ260015` Dubai = dijual bentuk dough,
  tanpa matang/bundle — keputusan produk, bukan gap.)
- **Print format (docs/11): SELESAI 2026-10-07** — header global di LH
  `Company Letterhead - Grey` (konten diganti) + 10 format default site lama
  di-push ke lokal & cloud; render parity 10/10, PDF 6/6 lokal / 5/5 cloud;
  POS Next Receipt/EOD tidak disentuh. Rerun: `pos_sync/migrate_print_formats.py
  --build/--push/--verify --stage local|cloud` (rollback `--revert`).
- Pemegang: keputusan bisnis di user; eksekusi teknis di agent.
- Blocker: menunggu keputusan SKU + hasil probe produksi sebelum bulk.

## Next steps / TODO

0. **Catch-up migrasi WO/handover** (docs/10): keputusan scope user →
   eksekusi batch (7 WO pagi 7 Okt, 04130, feed Bahan Baku, PP261007001)
   + sinkron delta harian sampai cutover; keputusan WO September &
   SOP Krim Kopi (bulk vs per-WO) menunggu user.
1. Putuskan SKU unmapped (PG002–004 Gempi, TJ01/TJ02, PR00072–75 Hemat,
   CKN02, dll dari daftar sheet `Skipped`) → tambah ke mapping + Price Group.
2. Konfirmasi 9 order `TOTAL_BEDA` (payment.total ≠ jumlah baris) + outlet
   RSUD HJ. ANNA LASMANAH (beda ejaan) untuk melengkapi injeksi 1–5 Okt.
3. Probe 1 detail production → mapping BOM/PJO → pola Stock Entry.
4. Mapping SKU inventory eResto → Item Code ERPNext **selesai** untuk
   SO September (`stok_sku_to_item.csv`); sisa konfirmasi BB0066 +
   asumsi Pack dough 1:1, lalu seed stok outlet via Stock Entry.
5. Produksi `pos_sync/` harian: sync eResto → POS Invoice + shift
   otomatis (pola `inject_pos_invoice.py` sudah teruji untuk backfill).
6. ~~Purchase flow~~ **PO Outlet → JURI 25 Sep–7 Okt selesai 2026-10-08**
   (252 PO, `pos_sync/migrate_outlet_po_to_juri.py`). Sisa: PR/GR atas PO
   outlet (barang diterima outlet) + rantai intercompany SO-DN per outlet
   (pola `sync_delanggu_intercompany.py`) belum digarap untuk 114 outlet.
7. Rotasi token eResto (pernah terekspos di shell/arsip) + 3 API key Frappe
   (cloud baru, cloud lama, dev 8082) — nilainya pernah tersimpan plaintext
   di script lokal (sudah di-scrub 2026-10-08; belum pernah ter-push).
8. ~~Print format (docs/11)~~ **selesai 2026-10-07** — header global di LH
   Grey + 10 format default; rerun/rollback via
   `pos_sync/migrate_print_formats.py` (`--build/--push/--verify/--revert`,
   `--stage local|cloud`). Sisa follow-up: eyeball PDF di cloud oleh user
   (`pos_sync/pf_reports/cloud/*.pdf`).
9. **Faktur divisi Gudang Bahan Baku** (di luar scope 2026-10-08): 2 PI
   Cancelled perlu keputusan (`PI-JURI-261008005` Dairyfood Rp36,96 jt,
   `261008006` Polyta Rp9,11 jt) + `INVGBBK.081026.001` (Heri Wahyu
   Rp3,57 jt) belum ada PI. Detail sheet `GBBK_Catatan` di
   `Laporan_Migrasi_PI_Central_Okt2026.xlsx`.
10. **Diskrepansi harga PI vs PR** (wajar, tercatat): Mitra Olesan Tiramisu
    299.243,23 (faktur) vs 270.000 (PR); Sinnar Minyak Oles 29.000 vs 24.703,05.
    Bila finance ingin PR disesuaikan, perlu keputusan terpisah.
11. ~~PR duplikat~~ **SELESAI 2026-10-08** — sisi native (`PR-061026-011/012/014`)
    di-cancel; rantai eResto (PR-011026-020/021/022 + PI) dipertahankan.
12. ~~Draft PO eResto duplikat~~ **SELESAI 2026-10-08** — 26 draft dihapus.
13. ~~3 pasangan stok dobel~~ **SELESAI 2026-10-08** — sisi native di-cancel,
    Bin turun tepat (BB260031 −204.000g, PEL260075 −1.000, PEL260011 −5),
    repost valuasi selesai. Laporan `Laporan_Bersih_PO_JURI.xlsx`.
14. **182 PO PT JURI (window Sep–Okt) belum ada di BARU** (157 native +
    25 eResto-ID Sep) — bahan keputusan scope migrasi lanjutan.
15. **Extra native-native duplikat (ditemukan 2026-10-08 saat bersih-bersih)**:
    `PO-021026-020`↔`PO-061026-003` (Floren, PEL260078 220 Pack) dan
    `PO-021026-022`↔`PO-061026-001` (Arta Boga, PJ260009 30 ctn) — sisi tanpa
    rantai sudah di-cancel; sisi ber-PR dipertahankan.

## Keputusan desain

- **Kunci mapping = `product_sku`**, bukan nama. Dua SKU bisa satu Item; satu produk
  bisa beda SKU per tipe outlet (FRC vs reguler).
- **Harga per tier** dari sampling transaksi (`paid_quantity` > 0, non-void, modus
  per SKU); bukan dari price group eResto langsung (endpoint-nya tak memuat harga).
- **Void/refund:** skip void; refund eResto = auto-void → tanpa Sales Return negatif.
- **Outlet = Company**, anak `OUTLET REGULER` agar CoA seragam (Existing Company).
- **Opsi A:** company→tier dari price group takeaway eResto, bukan bikin manual
  per outlet.
- **POSNext:** Price Group memiliki Price List + Item Price dan mengklaim semua POS
  Profile company-nya — jangan buat Price List/Item Price manual.
- **Shift Group:** membership hanya lewat tabel Members milik grup (bukan field profil).
- **Kredensial via env**; tulis ERPNext via API key, bukan session login.
- **FRC:** hanya yang aktif transaksi 30 hari; nama persis eResto termasuk `(FRC)`.
- **Repack Gula Cair & Olesan Pastry (2026-10-09):** Gudang merepack bahan baku bulk (kg/ctn) ke botol 250 g untuk dikirim ke outlet. Gula Cair bulk = `BB26008` (kg, receipt ctn 25 kg), botol repack = `BB26009` (Botol). Olesan Pastry bulk = `BB260046`, botol repack = `BB26012` (Olesan Pastry 250 g). Pada PO outlet ke PT. JURI sebelum 7 Okt 2026, item 'Olesan Pastry' diganti menjadi `BB26012`.

## Known issues

- ~~**Telur Cair `BB260055` minus 12,49 kg di `Gudang Produksi - JURI`**~~ — **SUDAH SELESAI 2026-10-07**
  via `RECO-JURI-261007001` (+32,46 kg opening) & SE Repack 09605 (+143,36 kg) → saldo sekarang +163,33 kg positif.
- ~~**13 Bin negatif persediaan JURI & RPMD**~~ — **SUDAH SELESAI 2026-10-08** via 3 RECO
  (`RECO-JURI-261008001`, `RECO-JURI-261008002`, `RECO-RPMD-261008001`) → 0 Bin negatif di seluruh sistem.
- **WO outlet multi-level BOM — GUARD SELESAI & E2E BROWSER LULUS 2026-10-07
  di `production_app` (DI-COMMIT+PUSH; BELUM deploy cloud)**: WO "Mulai
  Produksi" SPA (pos_next `start_production`) tidak set `use_multi_level_bom`
  → default 1 → SE Manufacture meledakkan resep dough (kasus
  SE-MFG-261007001). Fix: doc_events `Work Order.before_validate` memaksa
  mlb=0 + rebuild required_items untuk item grup "Produk Jadi Outlet" (test
  4/4 + bukti live 8081 + **E2E browser built-in alur kasir penuh: WO
  mlb=0, 2 baris; Selesai → SE-MFG-261007001 hanya konsumsi dough+krim, WO
  Completed**). Menunggu keputusan user: deploy app + cleanup 2 WO cloud
  (cancel+hapus) lalu kasir ulang.
- Token capture lama eResto mati (semua endpoint 500) → pakai token alternatif;
  rotasi belum dilakukan.
- Respons detail order dibungkus `data.attributes` (pernah di root) — parser harus
  handle keduanya.
- 43 SKU POS pernah unmapped → 24 ACC user 2026-10-05 (docs/02);
  sisa 19 butuh item baru (CM01/MC01/MC02, CP02, P0005, AIR03, dst) —
  belum masuk Price Group mana pun (sheet `Unmapped_SKU`).
- 1 profil tanpa Price Group: RSUD Taman Husada Bontang (tidak ada di eResto).
- 7 company varian ejaan dibiarkan (profilnya sudah dihapus); data dari backup.
- **Item jual = Product Bundle** (Ropi/Croissant/Gempi non-stok, meledak
  jadi komponen PJO/PEL/BB). Invoice per-transaksi butuh stok komponen
  (fase paralel: dari produksi eResto atau seed lokal) — lihat
  docs/02 "Pilot 1 order". `pos_closing_entry` tak ada di site lokal.
- **Alur produksi terverifikasi** (docs/05): dough (PJ*) → matang (PJO*,
  sesi "Masak" outlet) → bundle jual (RP*/CR*/GM*). Yield terukur:
  Ropi 1 pack dough → 12 pcs, Gempi → 3, Croissant → 6. Pengecualian:
  `PJ260015` Dubai Dough Salt Butter dijual sebagai dough (tanpa
  matang/bundle). Bundle GM001 sempat berisi dirinya sendiri;
  diperbaiki 2026-10-04 jadi PJO2604+box.
- SKU inventory eResto (BB/RR/PJO/PEL) belum punya mapping ke Item
  ERPNext; `sku_to_item_code.csv` hanya memuat SKU POS (PR/P000x).
  Dibutuhkan sebelum seed stok outlet dari SO.
  *(2026-10-04: mapping stok SO selesai — `stok_sku_to_item.csv`;
  sisa BB0066 TEBAKAN + asumsi Pack dough→Pcs 1:1.)*
- `PJ260015` Dubai Dough Salt Butter **dijual dalam bentuk dough**
  (keputusan produk, bukan gap): tanpa matang/bundle, SKU eResto belum
  terlihat di sampel. Jangan buatkan PJO/padanan untuknya.
- Item doctype site ini ber-naming series `BB26-.###` yang menimpa
  `item_code` saat create — wajib rename pasca-create
  (`create_stok_items.py` sudah menangani).
- Hutang teknis: script `experiments/` belum jadi modul; fetch harga masih manual;
  belum ada test otomatis.
- Pertanyaan terbuka: skema stok franchise (beli-putus vs konsinyasi);
  apakah POS Invoice outlet FRC di lokal (554 invoice / Rp18,4jt) ikut
  dibatalkan (27 JE agregat FRC juga belum dibatalkan); pembuatan company
  baru utk outlet `RS RIDHOKA SALMA CIKARANG` (47 order 5 Okt tertahan).

## Cara jalanin

- `source .venv/bin/activate`; deps: `pip install requests pandas openpyxl`.
- Env (nama saja): `ERESTO_TOKEN`, `ERESTO_EMAIL`, `ERESTO_USER_ID`,
  `ERPNEXT_URL`, `ERPNEXT_API_KEY`.
- Fetch eResto: `python experiments/pos-fetch/test_fetch_orders.py --date ... --outlet-id ...`.
- Setup ERPNext: `python experiments/apply_pos_bulk.py [--only "Company"] [--tier "..."]`.
- Update metode bayar: `python experiments/update_pos_payments.py`.
- Clone SHIFT 2: `python experiments/create_shift2.py`.
- Laporan: `python experiments/build_pos_report.py` → `POS_Setup_Report.xlsx`.
- Stok opname: `python experiments/fetch_so_monthly.py` →
  `Stock_SO_Monthly_September.xlsx` (pakai cache /tmp/sa_sep.json bila ada).
- Mapping stok: `python experiments/build_stok_mapping.py` →
  `Template_Mapping_Stok.xlsx`; item baru: `create_stok_items.py`.
- Injeksi agregat: `python experiments/inject_sales_aggregate.py [--dry-run]`
  (sumber `pos-fetch/Penjualan_*.xlsx`, kunci `cheque_no=ERESTO-<branch>-<date>`).
- Injeksi production (docs/07, urut): `python pos_sync/prod_dump.py` →
  `prod_master.py` → `prod_itemdefs.py` → `prod_opening.py` → `prod_docs.py`
  → `prod_verify.py` (semua idempoten; prod env di `/tmp/eresto_prod.env`).
- Injeksi POS Invoice lokal (docs/08): `python pos_sync/set_item_valuation.py`
  (sekali) → `python pos_sync/inject_pos_invoice.py --date-from ... --date-to ...`
  (idempoten via remarks `ERESTO <order_no>`; `--refresh-list` untuk tarik ulang
  list eResto bila data hari berjalan masih mengalir; `--dry-run`/`--limit-groups`
  untuk uji; output `PosInvoice_Lokal_*.xlsx`).
- Migrasi WO JURI 1–6 Okt ke cloud (docs/09): `python pos_sync/migrate_wo_full_okt.py`
  `--dump` (sekali; `--refresh` untuk tarik ulang) → `--plans` → `--wos` →
  `--mrs` → `--ses` → `--verify` (`--repair` untuk sinkronkan custom field WO
  yang belum terisi). Rerun aman; untuk 23 WO 6 Okt yang belum selesai di lama,
  cukup `--ses` lagi setelah lama tuntas.
- Migrasi PO Outlet → JURI (25 Sep–7 Okt): `python pos_sync/migrate_outlet_po_to_juri.py`
  `--dump` (sekali; `--refresh` untuk tarik ulang) → `--prep` → `--migrate`
  → `--verify`; `--rewarehouse` untuk mengubah gudang PO yang sudah masuk ke
  `Stores - <ABBR>`; `--dry-run`/`--only <PO>`/`--limit` untuk uji. Env: butuh
  `ERPNEXT_OLD_CLOUD_API_KEY` di `/tmp/eresto_mig.env` + `ERPNEXT_API_KEY`
  di `/tmp/eresto_prod.env`. Rerun aman (252 SKIP_EXISTS).
- Migrasi SO + DN Outlet → JURI (1–7 Okt): `python pos_sync/migrate_outlet_so_dn_to_juri.py`
  `--dump` (sekali; `--refresh`) → `--prep` → `--so` → `--dn` → `--verify`;
  `--dry-run`/`--only <dokumen>`/`--limit`/`--workers`. Jangkar DN 1–7 Okt,
  SO lebih tua ikut bila ditarik DN; Delanggu di-skip. Rerun aman
  (termasuk self-heal dokumen yang tertinggal draft).
- Tarik PO eResto difaktur Okt: `python pos_sync/fetch_po_invoiced_okt.py`
  (`--date-from/--date-to/--refresh`; cache `pos_okt_dump/`) → laporan
  `Laporan_PO_Diinvoice_Okt2026.xlsx`.
- Migrasi faktur → PI divisi sentral (GBJ/GPK/GJKT): `python pos_sync/migrate_pi_central_okt.py`
  (`--dry-run/--only <INV>`; idempoten `bill_no`+docstatus<2); cek lama↔baru
  per nama item/qty/unit/harga, auto-migrasi PO/PR Sinar bila absen, sheet
  `GBBK_Catatan` utk divisi bahan baku (di luar scope). Rerun = 7 SKIP_EXISTS.
- Tarik PO eResto Gudang Jakarta per hari: `python pos_sync/migrate_po_gudang_jakarta_9okt.py`
  (`--date YYYY-MM-DD` default 2026-10-09; `--dry-run`/`--verify`/`--only`;
  idempoten by name/title + self-heal rename; ID = nomor PO eResto; status
  eResto processing/completed → submit, lainnya → draft) → laporan
  `Laporan_Migrasi_PO_Gudang_Jakarta_9Okt2026.xlsx`. Jebakan rename_doc
  sudah ditangani (wajib form-encoded; lihat memori `erpnext-migration-gotchas-sites`).
- PO outlet baru tanpa company (mis. SELOGIRI): `python pos_sync/migrate_po_selogiri_9okt.py`
  (`--dry-run`/`--verify`/`--only`; onboard company anak `OUTLET` + FY 2026 +
  allowed supplier + customer internal, lalu migrasi PO222.091026.001/.002
  ID identik → laporan `Laporan_Migrasi_PO_Selogiri_9Okt2026.xlsx`).
- Audit banding PO PT JURI LAMA↔BARU: `python pos_sync/compare_po_juri_lama_baru.py`
  (`--refresh`; read-only) → `Laporan_Banding_PO_PT_JURI.xlsx` (Baru_eRestoID,
  Draft_Item_Detail, Rekap_Lama, Rekap_Baru, Duplikat_Submitted,
  Rekomendasi_Draft, Double_Receipt, Validation).
- Bersih-bersih duplikat PO PT JURI (>1 jam): `python pos_sync/bersih_po_juri.py`
  (default dry-run; `--execute` untuk jalan). Hapus 26 draft eResto-ID +
  cancel 12 dokumen (3 PR + 5 PO native + 4 PO eResto submitted). Guard per
  dokumen: dicek dulu tidak ada referensi PR/PI/PE di luar pasangan cancel;
  rerun aman (draft hilang/PO cancelled di-skip). Post-check Bin otomatis.
  Env: `/tmp/eresto_prod.env` saja (site BARU).
- Banding stock balance LAMA vs BARU per 30 Sep (audit 2026-10-08):
  `python pos_sync/compare_stock_sep30.py` (`--dump`/`--compare`/`--report`;
  default semua; read-only dua site). Saldo = qty_after_transaction baris
  SLE terakhir <= cutoff (23:00 literal & EOD); cache
  `pos_sync/stock_sep30_dump/`; laporan
  `pos_sync/Laporan_Stock_Sep30_LAMA_vs_BARU.xlsx` (Ringkasan, Sama,
  Sama_EOD_Beda_2300, Beda_* per kategori penyebab, Hanya_Baru,
  Gudang_Lama_Tanpa_Pasangan). Rerun idempoten (cache; `--dump` untuk
  tarik ulang). **Temuan utama (per EOD 30 Sep): 236 sama persis,
  227 beda — hampir semua terjelaskan**: 43 tidak dihitung opname,
  66 gudang non-BIG6 belum diinjeksi (GA/R&D/Peralatan/Vendor/Outlet:
  opening-nya di BARU diposting 2 Okt), 34 buku LAMA vs opname fisik
  (drift pra-migrasi), 15 koreksi disengaja 7-8 Okt, 9 cek khusus
  (UOM/kode bentrok), 7 waktu opname (opname pagi/siang vs buku malam),
  6 item baru, 5 posisi buku jam lain; 42 baris di 3 gudang LAMA tanpa
  pasangan (Mini Outlet/Testing). Sisa keputusan: angka opname mana yang
  dianggap benar utk 34 BUKU_LAMA_VS_FISIK + PEL260087 GBJ/JKT
  (RECO 261007004/5 menetapkan 201.000/34.000 vs buku LAMA 238.100/27.850).
- Isi saldo 30 Sep 2026 23:00 LAMA→BARU (instruksi user 2026-10-09):
  `python pos_sync/fill_opening_sep30.py` (`--plan` dry-run default;
  `--execute`; `--report`; `--refresh-lama`/`--refresh-bins`). Scope
  company JURI; saldo = qty_after_transaction LAMA @30 Sep 23:00.
  Hasil: 13 RECO Opening Stock `RECO-JURI-261009002..261009014`
  (170 posisi), 3 gudang baru (Mini Outlet, Gudang Testing Manufacture,
  WIP Testing), 38 item baru + 1 batch (DubaiKK-260814-012 utk PJ260008),
  Stock Settings `enable_serial_and_batch_no_for_item` 0→1 (parity LAMA).
  Verifikasi: 377/407 posisi LAMA ber-stok kini sama persis @23:00;
  30 posisi (angka beda dr audit) sengaja menunggu keputusan user.
  Loan `SE-MR-261009001` (23:59:59) tidak disentuh. Laporan
  `pos_sync/Laporan_Fill_Saldo_Sep30_2300.xlsx` (Terisi/Pending_Audit/Item_Baru).
  Rerun aman (hitung ulang; yang sudah terisi dilewati).
- Bersih dokumen cancelled (BARU, scope company): `python pos_sync/bersih_dokumen_cancelled.py`
  (dry-run default; `--execute`; backup JSON + ledger sweep + Bin net-zero otomatis;
  idempoten — rerun = 0 ditemukan).
- Merge item Goodie Bag: `python pos_sync/merge_goodie_bag_items.py [--execute]`
  (preflight properti item + bundle + RECO clash; `rename_doc merge=1`; poll repost).
  Koreksi Bin pasca-merge: `python pos_sync/fix_goodie_bins_post_merge.py [--execute]`
  (target = jumlah saldo pra-merge dari backup).
- Stock minus + lock: `python pos_sync/fix_stock_minus_9okt.py [--execute] [--lock]`
  (repack idempoten via marker remarks; `--lock` set `allow_negative_stock=0` +
  smoke test tolak-minus). Kebijakan: minus DILARANG — jangan matikan lock tanpa izin user.
- Konsolidasi RECO (opening 30 Sep 23:00 per gudang + akun 1171/5110):
  `python pos_sync/konsolidasi_opening_reco.py` (`--plan` default read-only →
  `reco_consolidate_plan.json`; `--execute [--warehouses "A,B"] [--sr7-only]
  [--enable-negative-window]`; `--cleanup [--execute-cleanup]`; `--report`
  → `Laporan_Konsolidasi_Opening_RECO.xlsx`). Gate: subset yang butuh flag
  REFUSE tanpa `--enable-negative-window` (restore 0 di finally). State:
  `reco_consolidate_state.json`. Substitusi zero-out:
  `python pos_sync/restore_sr7_zeroouts.py [--execute]`.
- Hapus warehouse testing (LAMA & BARU): `python pos_sync/hapus_warehouse_testing.py`
  (`--plan` dry-run; `--execute [--only baru|lama]`; `--patch-state` utk
  bersihkan state konsolidasi) → `Laporan_Hapus_Warehouse_Testing.xlsx`.
- Tidak ada build/test suite; verifikasi = Excel + cek stdout semua "OK".

## Changelog

- **2026-10-09 (HAPUS WAREHOUSE TESTING DI LAMA & BARU — SELESAI):**
  Atas instruksi user ("warehouse namanya Gudang Finished Goods Testing /
  Gudang Testing Manufacture / WIP Testing DIHAPUS! Stock yang ada di web lama
  itu cuma testing aja, jadi hapus ajaa"):
  - **Recon 2 site (read-only):** LAMA punya 3 gudang testing (Finished Goods
    Testing tanpa stok; Testing Manufacture 12 item; WIP Testing 1 item);
    BARU punya 2 padanan (dibuat sesi opening 30 Sep: `RECO-JURI-261009046`
    & `261009043`). Nol referensi POS Profile/MR/WO (selain draft testing).
  - **Eksekusi `pos_sync/hapus_warehouse_testing.py` (dry-run default):**
    BARU — cancel+delete 2 RECO opening testing, bersihkan 26 Repost Item
    Valuation (13 `Queued` di-`Skipped` via Property Setter `allow_on_submit`
    sementara — `before_cancel` RIV menolak Queued), hapus 2 warehouse.
    LAMA — hapus 2 draft SE testing Agustus (pemblokir), cancel+delete 4 SE
    testing (`MAT-STE-2026-01469/05894/05900/05901`), bersihkan 27 RIV, hapus
    3 warehouse. Jebakan LAMA: `Accounts Settings.delete_linked_ledger_entries`
    tak bisa disetel (doc settings rusak "Row #6: Expense Claim") → fallback
    **hapus langsung baris GL/SLE `is_cancelled=1`** via REST baru delete dok.
  - **Verifikasi:** 5 warehouse **HTTP 404** di kedua site, 0 SLE/0 RIV sisa,
    0 Property Setter tertinggal, Bin negatif 0, `allow_negative_stock` tetap
    0, RECO aktif JURI 35. Backup: `audit_logs/backup_hapus_wh_testing_*`.
    Guard: `fill_opening_sep30.py` tidak lagi membuat gudang testing.
  - Laporan: `pos_sync/Laporan_Hapus_Warehouse_Testing.xlsx`.

- **2026-10-09 (BERSIH DOKUMEN CANCELLED PT. JURI + MERGE GOODIE BAG + STOCK NON-NEGATIF — SELESAI):**
  Atas instruksi user ("dokumen yang dicancel dihapus aja", "PI dari site lama jangan
  dimigrasi — cek dulu, kalau ada yang termigrasi hapus!", "sistem ga mau kalau stock
  minus!", "aku ingin hapus item goodie bag 6 roti agar ga kedoublean", "ini untuk
  PT. JUARA ROTI INDONESIA aja YA!"):
  - **Audit PI site lama (read-only): 5 PI (`PI-011026-001/002`, `PI-250926-001`
    [cancelled], `PI-250926-001-1`, `PI-270826-001`) — 0 termigrasi ke BARU**
    (dicek nama persis/fuzzy per total, supplier, item). Tidak ada yang dihapus;
    aturan "PI lama = trial, jangan migrasi" dikunci di AGENTS/KNOWLEDGE.
  - **Bersih dokumen cancelled (BARU, scope company PT. JURI):** 30 dokumen
    dihapus permanen dengan `pos_sync/bersih_dokumen_cancelled.py` (scan live
    docstatus=2 + filter company; backup 30 JSON; purge POS Print Log;
    `delete_linked_ledger_entries=1` sementara + restore; hapus berurutan
    dependency-safe; 2 MR terkunci `amended_from` dilepas via Property Setter
    sementara). Hasil: 30/30 deleted, sisa docstatus=2 JURI = 0, GL/SLE/PLE per
    dokumen = 0, **Bin net-zero (491 posisi identik sebelum-sesudah)**.
    Non-JURI `WO-TRNG-261007001` (company TRAINING) sengaja tidak disentuh.
    Laporan: `pos_sync/Laporan_Bersih_Dokumen_Cancelled.xlsx`.
  - **Merge Goodie Bag (`pos_sync/merge_goodie_bag_items.py`):** root cause
    "kedoublean" = item legacy `PG001` "Goodie Bag 6 Roti" (18.052 pcs di GBJ)
    vs `PEL260072` "Goodie Bag" (kanonik); POS Package "Paket Goodiebag 6 ROPI"
    salah memasang `PG001` (bug mapping lama `PKG01->PG001`). Eksekusi
    `rename_doc(merge=1)` `PG001 -> PEL260072`: semua referensi (7 SLE,
    4 POS Invoice RPMD, SE TRNG, 2 RECO, POS Package, Item Price) pindah;
    `PG001` terhapus (404). Pasca-merge, repost menggabungkan 2 RECO absolute
    saling timpa (GBJ 16.492 & RPMD −2) -> koreksi `RECO-JURI-261009040`
    (+43.217 @1368,78) & `RECO-RPMD-261009001` (+71 @1.900) via
    `pos_sync/fix_goodie_bins_post_merge.py`. Bin akhir: GBJ 43.217, RPMD +71,
    TRNG 75, Jakarta 6.194, Mini 40. RPMD −2 lenyap; POS Package kini
    `PEL260072`. Backup `audit_logs/backup_merge_goodie_*.json`.
  - **Stock non-negatif & kunci sistem (`pos_sync/fix_stock_minus_9okt.py`):**
    minus `BB260055` Telur Cair −19.982,8 g (repack 9 Okt kurang catat: fisik
    sudah dipecah) ditutup dgn Repack `SE-RPK-261009006` (BB260027
    −23.155,041 g -> BB260055 +19.982,8 g, posting 16:20). Verifikasi **0 Bin
    negatif se-sistem** lalu `Stock Settings.allow_negative_stock = 0`
    **PERMANEN** + smoke test: submit SE minus DITOLAK `NegativeStockError`
    (draft dibersihkan). Kebijakan "stock minus dilarang" masuk AGENTS/KNOWLEDGE.
  - **Data repo diselaraskan:** `experiments/stok_sku_to_item.csv` &
    `build_stok_mapping.py`: `BB0066 -> PEL260072` (status TEBAKAN -> COCOK);
    `pos_sync/reinject_package_invoices.py`: `PKG01 -> PEL260072` (sumber bug
    package); `docs/02` + `PROMPT_SESI_BERIKUTNYA.md`: pertanyaan BB0066 ditutup.
  - Laporan: `Laporan_Bersih_Dokumen_Cancelled.xlsx`, `Laporan_Merge_Goodie_Bag.xlsx`,
    `Laporan_Fix_Goodie_Bins.xlsx`, `Laporan_Fix_Stock_Minus_9Okt.xlsx`.

- **2026-10-09 (KONSOLIDASI STOCK RECONCILIATION JURI — TAHAP-1 SELESAI, SISA MENUNGGU IZIN):**
  Atas instruksi user ("benerin stock reconciliation — akun yang dipakai salah;
  penyesuaian pakai akun penyesuaian, opening pakai pembukaan sementara; jadiin
  satu — opening per gudang, kejadiannya 30 Sep 2026 jam 23:00"; scope JURI saja;
  dough di GBJ tidak diotak-atik dulu):
  - **Temuan:** 42 dok RECO JURI aktif — 31 opening tersebar (jam 11:00–23:59,
    3 dok bertanggal 2 Okt) + 7 dok penyesuaian salah akun (1171, harus 5110).
    Akun kanonik: opening=`1171.000 Pembukaan sementara` (1/gudang @30 Sep
    23:00), penyesuaian=`5110.020 Penyesuaian Stock`.
  - **Eksekusi TAHAP-1 (`pos_sync/konsolidasi_opening_reco.py`):** 7 gudang
    non-GBJ dikonsolidasi **tanpa flag** — GIT, WIP Testing, GA, R&D, Testing
    Manufacture, Vendor, Mini Outlet → `RECO-JURI-261009042..048` (opening
    gabungan @2026-09-30 23:00, akun 1171). SR7: `026→049` (5110), `033→050`
    (5110), `030→SE-MR-261009002` & `031→SE-MR-261009003` (substitusi Material
    Receipt, karena zero-out di atas saldo minus tak bisa di-recreate tanpa
    flag), `029` no-op (dihapus). 13 dok cancelled dihapus permanen via
    `--cleanup` (backup `audit_logs/backup_reco_consolidated_20261009_230454.json`,
    ledger 0). Verifikasi tiap gudang: trail >30 Sep identik, checkpoint 23:00
    sesuai, Bin 0 selisih, **0 Bin negatif**.
  - **Blokir sisa (JUJUR, belum dikerjakan):** 7 gudang (Gudang Bahan Baku,
    Gudang Barang Jadi, Jakarta, Outlet, Peralatan, Produksi, WIP) + SR7
    `032`/`034` **butuh `--enable-negative-window`** — validasi native v16
    (`NegativeStockError`) menolak cancel/recreate karena trail menyimpan
    2.521 baris minus historis fase migrasi. Flag TIDAK dinyalakan tanpa izin
    user (kebijakan AGENTS). Lanjutan: `python pos_sync/konsolidasi_opening_reco.py
    --execute --enable-negative-window` (restore 0 otomatis di finally) lalu
    `--cleanup --execute-cleanup` + `--report`.
  - **Jebakan didokumentasikan** (KNOWLEDGE §6 + `docs/12`): cancel RECO v16
    menggeser trail (shift −qty, dibatasi RECO berikutnya), urutan cancel harus
    ascending creation; zero-out di atas minus → substitusi Material Receipt.
  - Laporan: `pos_sync/Laporan_Konsolidasi_Opening_RECO.xlsx` (interim).
    Semua script dry-run default + `--execute`; rerun idempoten.

- **2026-10-09 (FIX "Persiapan Gagal" WO Krim Kopi `MFG-PP-2026-00007` — SELESAI):**
  Atas laporan user ("production di WO krim kopi tanggal 9 oktober ga bisa distart, muncul eror"):
  - **Gejala**: submit/prepare WO Krim Kopi gagal — popup app `Persiapan Gagal` + pesan
    *"Row 60 in Production Plan Item MFG-PP-2026-00007: Work Order quantity after process loss 25.0 exceeds the remaining allowed quantity 12.5"*.
  - **Sumber error**: validasi **native ERPNext v16** `ProductionPlanWorkOrderQuantities.validate_work_order`
    (`erpnext/manufacturing/doctype/production_plan/services/work_order_quantities.py`), dipanggil dari
    `Work Order.before_submit` / `set_process_loss_qty`. `maximum = planned*1.5 (overproduction 50%) - committed(WO submitted lain di baris yang sama)`.
  - **Akar masalah**: WO-JURI-261009061 (Krim Kopi, baris plan idx 61 `caj8tpvd7p`) di-cancel & **dihapus 14:57**,
    lalu dibuat ulang 14:59 **salah nempel ke baris idx 60** (`caj87op4b5`) — baris milik WO-JURI-261009060 (draft).
    Akibatnya baris 60 punya 2 WO (kuota kepakai: 25/37.5 → sisa 12.5) dan baris 61 kehilangan WO. Submit WO-060
    (25 > 12.5) ditolak `OverProductionError` → tampil sebagai `Persiapan Gagal`. (Plan tetap 61 baris × 1 WO;
    hanya WO-061 yang pindah baris, baris 61 jadi kosong.)
  - **Fix (`pos_sync/fix_wo_061_rebind_9okt.py`, dry-run default / `--execute`)**: rebind `production_plan_item`
    WO-061 `caj87op4b5 → caj8tpvd7p` (via Property Setter `allow_on_submit` sementara, lalu dihapus) +
    luruskan `ordered_qty` baris 60 → 0, baris 61 → 25 (semantik native = Σ qty WO submitted).
  - **Verifikasi**: binding benar; 1 WO aktif per baris plan (0 dup, 0 baris kosong seluruh plan); allowance submit
    WO-060 bebas (25 ≤ 37.5); `ordered_qty` 0/25; rerun = SKIP (idempoten). Backup
    `audit_logs/backup_wo_krim_kopi_rebind_9okt.json` + snapshot WO-061 asli
    `audit_logs/deleted_WO-JURI-261009061_snapshot_9okt.json`. Sisa 6 draft plan ini aman (allowance per baris).
  - **Catatan**: data adonan asli WO-061 (di-prepare sebelum dihapus: adonan_ke 34, jam 15:05, penimbang Tegar, leader Shabrina)
    ada di snapshot; WO-061 pengganti bersih (belum diisi prep) — siap dijalankan ulang oleh operator.

- **2026-10-09 (Migrasi PO140.091026.002 eResto Gudang Jakarta → BARU — SELESAI):**
  Atas instruksi user ("tarikin PO140.091026.002 di eresto trus input ke erpnext"):
  - **PO140.091026.002** (Gudang Jakarta → RSI AYSHA CIBINONG BOGOR, 8 baris, Rp 1.399.380, status eResto `processing`) berhasil masuk BARU via `python pos_sync/migrate_po_gudang_jakarta_9okt.py --only PO140.091026.002`: Submitted (`To Receive and Bill`), ID identik, `Stores - RACB`, source `Gudang Jakarta - JURI`, price list `Harga Outlet`; 0 selisih, rerun = SKIP_EXISTS (0 duplikat); cross-check fresh GET 100% klop (qty×rate=amount, stock_qty=qty×cf).
  - **SKU baru di ITEM_MAP**: `BB0312` 'Air Mineral Outlet 600 ml' → `PJ260009` (bukti `inject_reco_gudang_jakarta.py`; UOM eResto `ctn` = 24 Botol di master, rate per ctn). Gunakan `--only` untuk rerun satuan: script default `--date` menarik semua PO Jakarta hari itu.
  - Catatan: `PO140.091026.001` sudah masuk lebih awal hari ini (ds=0/pending); `.003` masih `pending` di eResto (belum diminta). Laporan harian `Laporan_Migrasi_PO_Gudang_Jakarta_9Okt2026.xlsx` diregenerasi mencakup 12 PO (Rp 109.844.645).

- **2026-10-09 (MIGRASI PO eResto PO222.091026.001/.002 → ERPNext BARU — SELESAI):**
  Atas instruksi user ("aku ingin kamu masukin po dari eresto berikut PO222.091026.001, PO222.091026.002 input ke erpnext site baru"):
  - **Scope**: 2 PO eResto tanggal 9 Okt 2026, divisi pemesan `RS MUHAMMADIYAH SELOGIRI` (outlet yang sebelumnya TUNDA di Kandidat_Company_Baru karena 0 trx POS); supplier internal gudang:
    `PO222.091026.001` (Gudang Outlet - PH Klaten, 5 baris peralatan outlet, Rp 6.078.849) + `PO222.091026.002` (Gudang Peralatan Klaten, Panel 3 Phase, Rp 1.958.000); status eResto keduanya `processing`.
  - **Onboarding company (pola RSUD KRAMAT JATI 2026-10-09)**: Company `RS MUHAMMADIYAH SELOGIRI` (abbr `RSMS`, anak `OUTLET`, CoA Existing) + Fiscal Year 2026 + Allowed To Transact With supplier `PT. JUARA ROTI INDONESIA` (175 rows) + customer internal `CUST-260213`; `enable_perpetual_inventory` dijaga 1 (parity outlet lain); warehouse `Stores - RSMS` dll auto-created.
  - **Pemetaan SKU peralatan (bukti, bukan tebakan)**: PO lama `PO332.100926.002` (RS PKU AISYIYAH BOYOLALI) identik 1:1 dengan PO222.091026.001 (nama/qty/harga) → site lama menyimpannya sebagai `PEL260059` (Orbit→Modem WiFi), `PEL260056` (CCTV), `PEL260058` (Memory Card→MMC), `PEL260060` (USB), `PEL260057` (Alat Kasir→Mesin Kasir); `BB0291`→`PER260004` sudah ada di ITEM_MAP migrasi 8-9 Okt (PO223/PO332 seri sama). Semua UOM (`Unit`/`Pcs`) ada di master, cf=1.
  - **Konvensi dokumen (sama dgn `migrate_po_gudang_jakarta_9okt.py`)**: Company = divisi outlet, Supplier = `PT. JUARA ROTI INDONESIA`, `set_warehouse` = `Stores - RSMS`, `set_from_warehouse` = gudang asal JURI (`Gudang Outlet - JURI` / `Gudang Peralatan - JURI`), price list `Harga Outlet`, beban `4210.000 - HPP Pembelian - RSMS`, CC `Main - RSMS`; ID dokumen = nomor PO eResto (rename_doc form-encoded), status processing → submit.
  - **Hasil & verifikasi**: 2/2 Submitted (`To Receive and Bill`), ID identik `PO222.091026.001`/`PO222.091026.002`, total Rp 8.036.849 = eResto 0 selisih (≤Rp1); line math (qty×rate=amount, stock_qty=qty×cf) klop; rerun = 2 SKIP_EXISTS (0 duplikat, idempoten); cross-check independen fresh GET 100% klop (company/FY/supplier/customer/dokumen, judul `ERESTO <PO>` tak ada kembar).
  - **Artefak**: `pos_sync/migrate_po_selogiri_9okt.py` (`--dry-run`/`--verify`/`--only`; idempoten + self-heal rename) dan laporan `pos_sync/Laporan_Migrasi_PO_Selogiri_9Okt2026.xlsx` (sheet Onboarding/Rekap_Migrasi/Raw_eResto/Skipped/Validation/Catatan).

- **2026-10-09 (AUDIT & PERBAIKAN STOK COLD STORAGE, SE MANUFACTURE 7-8 OKT, IN-TRANSIT JAKARTA, & SELESAI ERROR WO 04261 — SELESAI):**
  Atas master prompt audit komprehensif user ("kembalikan stock ERPNext agar sesuai dengan stock balance gudang Cold Storage pada 30 September 2026 pukul 23:59:59... jangan hapus WO dan MR... keluarkan item deactivate... tangani SE-MR-261009002... ingat ada stock entry in transit dari barang jadi ke gudang jakarta"):
  - **Akar Masalah Popup "tidak punya lot tersedia" di `MFG-WO-2026-04261`**: `RECO-JURI-261009027` (dibuat 9 Okt 12:49) memaksakan saldo Cold Storage menjadi 0.0 untuk menutup stok minus; hal ini menelan saldo produksi riil `MFG-WO-2026-04261` (216 Pcs jam 11:07). Akibatnya fungsi `_checked_lot` di `production_app/api/handover.py` mendeteksi `physical_qty <= 0` dan menolak pembuatan MR/Serah Terima.
  - **Akar Masalah Minus di Cold Storage**: 123 Stock Entry Manufacture (WIP → Cold Storage) pada 7 & 8 Oktober tidak pernah dimigrasikan dari site lama, sementara SE Serah Terima (Cold Storage → GBJ) sudah dimigrasikan, menyebabkan defisit -1.542 Pcs per hari (-3.084 Pcs).
  - **Migrasi 123 SE Manufacture 7 & 8 Okt**: Seluruh 123 dokumen SE Manufacture (`MAT-STE-2026-09506` s/d `09747`) berhasil dibuat dan disubmit ke Cloud Baru via `pos_sync/migrate_se_mfg_7_8_okt.py` (118 baru + 5 pre-migrasi, 0 gagal), memulihkan pasokan riil adonan ke Cold Storage.
  - **Migrasi Stock Entry In-Transit ke Gudang Jakarta**: 2 SE Material Transfer (`MAT-STE-2026-09748` berisi 65.796 Pcs adonan `PJ260010..016` dan `MAT-STE-2026-09752` berisi BB & kemasan) berhasil dimigrasikan ke site baru sebagai `SE-MTF-261009020` & `SE-MTF-261009021` dengan asal `Gudang Barang Jadi - JURI` dan tujuan `Goods In Transit - JURI`.
  - **Koreksi & Pembatalan RECO Penambal / Fiktif**:
    * `RECO-JURI-261009027` (memaksa CS ke 0) DICANCEL → 216 Pcs `MFG-WO-2026-04261` langsung kembali aktif dan terdeteksi di board serah terima.
    * `RECO-JURI-261007006` (+1.542 pcs) & `RECO-JURI-261009016` (phantom opening Cold Storage) DICANCEL → saldo Cold Storage per 30 Sep 23:59:59 murni **0.0 Pcs** (0 baris SLE <= 30 Sep).
    * `SE-MR-261009002` (pinjaman 600.000 Pcs backdated ke 1 Sep) DICANCEL dengan aman tanpa menyebabkan stok minus di riwayat transaksi.
    * `RECO-JURI-261009023`, `024`, `025`, `028` DICANCEL → seluruh item deactivate (`PJ260001..007`, `BHP260004`) kini bersih dengan **saldo 0.0 Pcs** di semua gudang.
  - **Integritas Dokumen Operasional**: 100% Work Order dan Material Request utuh tanpa ada yang dihapus atau diubah.
  - **Verifikasi Akhir**: Board `handover_board` di `production_app` status 200, 164 lot aktif, `MFG-WO-2026-04261..04264` terdaftar `Unsupported: False`, stok live Cold Storage `PJ260010` = 654 Pcs (menutupi seluruh MR pending), 0 minus di Cold Storage.

- **2026-10-09 (LUNAS 30 SEP 23:00 + EOD LAMA=BARU, HAPUS LOAN, 0 MINUS — SELESAI):**
  Atas instruksi user ("fix dong stocknya... stock pinjaman yang aku bikin di
  material receipt tuh bisa dihapus tapi cold storage ga minus... current stock
  tanggal 30 malam di kedua site itu sama... company PT. JUARA ROTI INDONESIA
  saja... jangan masukin warehouse baru").
  - **Diagnosis 48 selisih @23:00**: fill 9 Okt hanya mengisi posisi kosong;
    30 posisi beda (RECO opname `RECO-JURI-261006xxx` posting 11:00-22:23) +
    12 item Dough (Deactivate) tidak ada di BARU (PJ260001-007, disabled,
    batch-tracked) + PEL260087 GIT + PJ260007 CS.
  - **RECO @2026-09-30 23:00:00** per gudang (GBB 7, GBJ 15, Jakarta 4,
    Produksi 8, GIT 1, CS 6 item target = angka RECO-23:30, dough via
    `RECO-JURI-261009023/024/025`): menimpa nilai 23:00; RECO 23:30/23:35
    & loan 23:59:59 tidak tersentuh. Items dough dibuat (disabled, batch,
    group Produk Jadi Pabrik) + batch `LAMA-PJ26000x` / `KK-260831001`,
    lalu di-disable lagi; BHP260004 (non-stock) diisi via `RECO-JURI-261009028`
    (is_stock_item sementara 1 + default acc 1145, rate 17.079) lalu disabled.
  - **RECO opname yang menimpa nilai 23:00 di-cancel** (`RECO-JURI-261007004`,
    `261007005`, `261008002`) + kompensasi @1 Okt 00:00
    (`RECO-JURI-261009032/033`) & WIP kompensasi hari-ini
    (`RECO-JURI-261009034`) supaya stok Okt tidak bergeser →
    **EOD 30 Sep pun 0 selisih**.
  - **Loan `SE-MR-261009001-1` DICANCEL** (dulu 60.000-120.000 Pack per item —
    hanya masker). CS di-top-up `RECO-JURI-261009027` → CS sekarang
    PJ260007=742, PJ260010-16=0, tidak minus.
  - **Root cause 22 minus `Stores - JURI` + BB260015/BB260019/BB260046**:
    226 Item Default `default_warehouse=Stores - JURI` (ter-set massal 5 Okt
    07:17) membuat WO form order & MTFM menarik bahan dari gudang kosong;
    LAMA pakai `Gudang Produksi`/`Gudang Bahan Baku`. Diperbaiki: 226 Item
    Default → `Gudang Bahan Baku - JURI`; minus lama ditutup via
    `RECO-JURI-261009029/030/031`.
  - **Verifikasi akhir**: 0 selisih @23:00, 0 selisih EOD Sep30 (JURI, gudang
    ber-pasangan), 0 Bin negatif seluruh gudang JURI, CS semua 0/positif.
  - Catatan: `Stores - JURI` (dibuat 29 Sep) TIDAK dipakai LAMA; tidak
    diisi/tidak dibuat gudang baru.

- **2026-10-09 (PERBAIKAN WORK ORDER & STOCK ENTRY PRODUCTION PLAN 9 OKT 2026 PT. JURI — SELESAI):**
  Atas instruksi user ("memperbaiki workorder dari production plan tanggal 9 oktober 2026 di site baru erpnext... source warehousenya itu di stores -JURI, seharusnya produksi -JURI, trus target finishgoods harusnya cold storage produksi... stocknya banyak yang minus. dough harunsya di coldstorage dulu malah langsung ke barang jadi... company PT. JUARA ROTI INDONESIA saja"):
  - **Akar Masalah**:
    * Pada Production Plan `MFG-PP-2026-00007` (9 Okt 2026), 61 Work Order (`WO-JURI-261009001` s/d `061`) terbuat dengan `required_items.source_warehouse = Stores - JURI` (bukan `Gudang Produksi - JURI`).
    * 23 Work Order (`WO-JURI-261009018..019` Gempi, `028..048` Krim Kopi) memiliki `fg_warehouse = Gudang Barang Jadi - JURI` (bukan `Cold Storage Produksi - JURI`).
    * Eksekusi manual operator menghasilkan 35 SE MTFM yang menarik bahan dari `Stores - JURI` (menyebabkan 18 item minus besar di Stores), 25 SE MFG yang menaruh dough/krim langsung ke `Gudang Barang Jadi - JURI`, serta 2 SE MTF manual (`SE-MTF-261009030/031`) yang memindahkan 405 Pcs Gempi dari Cold Storage ke GBJ dengan distorsi valuasi ekstrim (Rp 9,9 Miliar).
  - **Eksekusi Perbaikan (`pos_sync/fix_production_plan_09okt.py`)**:
    * Membatalkan 2 SE MTF manual (`SE-MTF-261009030`, `SE-MTF-261009031`) -> status 200 (Cancelled).
    * Membatalkan 25 SE Manufacture (`SE-MFG-261009017..022, 025..029, 035..048, 172..175`) -> status 200 (Cancelled).
    * Membatalkan 35 SE MTFM (`SE-MTFM-261009001..035`) -> status 200 (Cancelled). Seketika 18 saldo minus di `Stores - JURI` kembali murni **0 minus**.
    * Memperbarui seluruh 61 Work Order (`WO-JURI-261009001` s/d `061`) via Property Setter sementara: `source_warehouse = Gudang Produksi - JURI`, `fg_warehouse = Cold Storage Produksi - JURI`, dan 100% baris `required_items.source_warehouse = Gudang Produksi - JURI`.
    * Memperbarui Production Plan `MFG-PP-2026-00007`: baris `po_items.warehouse` diarahkan ke `Cold Storage Produksi - JURI`.
    * Merecreate dan mensubmit ulang 35 SE MTFM (`SE-MTFM-261009036..070`) mengambil bahan baku riil dari `Gudang Produksi - JURI` ke `Work In Progress - JURI`.
    * Merecreate dan mensubmit ulang 25 SE MFG (`SE-MFG-261009176..200`) menaruh hasil produksi dough & krim kopi ke `Cold Storage Produksi - JURI` dengan quantity presisi.
    * Membersihkan kembali Property Setter sementara.
  - **Verifikasi Akhir**:
    * Saldo minus di `Stores - JURI`: **0 item** (100% bersih).
    * Saldo minus di `Gudang Produksi - JURI`: **0 item** (100% bersih).
    * Saldo `Cold Storage Produksi - JURI`: `PJ260011` (Dough Gempi) = +813 Pcs, `PJ260016` (Krim Kopi) = +535 Pcs (adonan masuk ke Cold Storage sesuai SOP).
    * Saldo `Gudang Barang Jadi - JURI`: normal, tidak kemasukan adonan mentah.
    * Status 61 Work Order: 25 Draft, 25 Completed, 10 In Process, 1 Not Started; seluruhnya 100% ber-target `Cold Storage Produksi - JURI`.
    * **Pembersihan Dokumen Batal**: Seluruh 61 Stock Entry yang dibatalkan (`docstatus = 2`: 2 SE MTF + 25 SE MFG + 34 SE MTFM) telah dihapus permanen (0 dokumen cancelled tersisa pada 2026-10-09).
    * **Penyelesaian Stok Minus di Work In Progress - JURI**:
      1. Transfer penunjang `BB260002` (Karet Gelang) 1.000 Pcs dari GBB ke Gudang Produksi (`SE-MTF-261009035`).
      2. Migrasi 2 Repack Telur Cair 8 Okt (`SE-RPK-261009002` & `003`), memecah 193,3 kg Telur Utuh `BB260027` menjadi +167.900 g Telur Cair `BB260055`.
      3. Migrasi penuh seluruh 124 MTFM 7–8 Okt dari LAMA (`SE-MTFM-261009083` s/d `207`) memasok 4,18 juta gram bahan baku ke WIP secara berimbang.
      4. Eksekusi Repack 9 Okt (`SE-RPK-261009004`, 100 kg Telur Utuh -> 86,3 kg Telur Cair) + penyeimbang Filling Butter & Coklat (`SE-MTF-261009036`).
      5. **Hasil Live**: **0 Bin negatif di seluruh warehouse PT. JURI** (WIP, Produksi, GBB, Stores, Cold Storage, GBJ). 18 item di WIP yang sebelumnya minus pada laporan `Inventory Movements 2026-10-01_2026-10-09 (1).xlsx` kini 100% bersaldo positif.
    * Backup lengkap disimpan di `audit_logs/backup_mfg_pp_261009.json`.

- **2026-10-09 (Import PO-160926-005 dari Situs Lama ke Baru — SELESAI):**
  Atas permintaan user, mengimpor Purchase Order `PO-160926-005` (tanggal 2026-09-16) dari ERPNext Lama (`rotiropi.j.frappe.cloud`) ke ERPNext Baru (`ropierpnext.frappe.cloud`).
  - **Company:** `PT. JUARA ROTI INDONESIA`
  - **Supplier:** `SUP260168` dipetakan ke `CV Mitra Sukses Sejati`
  - **Item:** `BB260044` (Olesan Dark Choco (1 kg)), 150 kg @ Rp57.081, Net Total Rp8.562.150
  - **Pajak:** `Purchase Tax - JURI` (PPN 11% On Net Total, akun `1152.001 - PPN Masukan - JURI`) = Rp941.836,50
  - **Grand Total:** Rp9.503.986,50 (Rounded Total: Rp9.503.986,00)
  - **Status:** Berhasil rename ke `PO-160926-005` dan di-submit (`docstatus: 1`, status `To Receive and Bill`).
  - **Artefak:** `pos_sync/import_po_160926_005.py` (idempoten).

- **2026-10-09 (ISI SALDO 30 SEP 23:00 SELURUH GUDANG KE BARU — SELESAI):**
  Atas instruksi user ("aku tuh bikin stock pinjaman pada stock entry
  SE-MR-261009001, karna di coldstorage kosong stoknya. jadi aku ingin kamu
  memasukan balance seluruh gudang yang stock ke erpnext baru pada jam 23:00
  di 30 september 2026").
  - **Metode:** saldo(WH,item) = `qty_after_transaction` baris SLE terakhir
    <= 2026-09-30 23:00 (LAMA, company JURI). Posisi yang di BARU masih 0
    utk jam itu diisi lewat 1 RECO `Opening Stock` per gudang, posting
    `2026-09-30 23:00:00`. RECO = set absolut pada timestamp-nya — dokumen
    koreksi yang sudah ada (23:30/23:35, Oct-1/2) dan loan
    `SE-MR-261009001` (23:59:59) TIDAK berubah; poin 23:00 menjadi benar.
  - **Hasil:** 13 RECO (`RECO-JURI-261009002..261009014`, 170 posisi) di
    13 gudang; 3 gudang BARU dibuat (Mini Outlet, Gudang Testing
    Manufacture, WIP Testing); 38 item baru dibuat (12 item GA
    kaos/celana/hairnet multi-size, 4 balon, lakban, dll dari master LAMA,
    dgn `item_defaults` akun JURI); 1 batch `DubaiKK-260814-012` utk
    PJ260008 (satu-satunya item ber-batch yang diisi).
  - **Kendala & solusi:** (1) RECO GBJ gagal 2x — item PJ260008 ber-batch
    tp `Stock Settings.enable_serial_and_batch_no_for_item = 0` di BARU
    (LAMA=1); solusi: set 0→1 (parity) + kirim `batch_no` +
    `use_serial_batch_fields` di baris RECO. (2) Item baru butuh
    `item_defaults.default_inventory_account` utk submit RECO.
  - **Verifikasi:** recompute seluruh 407 posisi LAMA ber-stok: **377
    sama persis @23:00** (170 terisi + 207 sudah sama). 30 posisi sisanya
    adalah angka yang beda sejak audit 2026-10-08 (opname vs buku) —
    SENGAJA tidak disentuh, menunggu keputusan user. Loan check:
    SE-MR-261009001 utuh (docstatus 1, 6 item, tag "Pinjam Stock").
  - **Artefak:** `pos_sync/fill_opening_sep30.py`, plan+cache
    `pos_sync/stock_sep30_dump/` (fill_plan_result.json, fill_docs.json,
    sle_lama_live.json), laporan `pos_sync/Laporan_Fill_Saldo_Sep30_2300.xlsx`
    (Ringkasan/Terisi 170/Pending_Audit 30/Item_Baru). Rerun idempoten.
  - **REVISI lanjutan (2026-10-09):** (a) loan `SE-MR-261009001` di-cancel
    user → Cold Storage jadi minus (loan menutup MFG yg belum masuk).
    (b) Saya sempat pasang RECO penyeimbang `RECO-JURI-261009015` (set CS
    = kondisi LAMA saat itu). (c) Atas permintaan user ("baliki lagi stock
    pinjamannya") RECO-261009015 di-**cancel** dan loan di-**amend ulang**
    menjadi `SE-MR-261009001-1` (submit 2026-09-30 23:59:59, 6 item
    60.000 Pack, nilai Rp655jt, tag "Pinjam Stock", `amended_from`).
    Verifikasi: Cold Storage TIDAK minus (PJ260010 59.112, PJ260011 30.000,
    PJ260012 114.708, PJ260013 108.228, PJ260014 110.928, PJ260016 9.131).
    Minus yang MASIH ada di luar CS: `Stores - JURI` (19 item, sisa akibat
    SE-MTFM 9 Okt pagi dari outlet training/FORM ORDER) + 6 item gudang
    lain (order 8-9 Okt) — semua karena stok fisik belum masuk, dan
    sudah tercatat di laporan audit; TIDAK terkait loan. Kode/CLI: lihat
    `/tmp` probe `zc5_fix.py`/`zr1_restore.py` (sekali pakai, tidak
    dijadikan script repo).
- **2026-10-09 (Klarifikasi PO Duplikat & Sinkronisasi Tag PO PT. JURI LAMA→BARU — SELESAI):**
  - **Klarifikasi Duplikat 4 PO Tokopedia - Shopee (7 Okt 2026):**
    User menanyakan mengapa 4 PO `Tokopedia - Shopee` di site baru berstatus `Cancelled` padahal di site lama berstatus `To Receive and Bill`:
    - Bukti audit: Pada 7 Okt 2026 terjadi double-entry (8 PO untuk 4 transaksi barang yang sama persis):
      1. `POCK2.071026.001` (Tokopedia - Shopee) vs `PO-071026-014` (Shopee - Ionshop): 5 pair Sarung Tangan Oven (`PEL260038`), Rp 386.700.
      2. `POCK2.071026.002` (Tokopedia - Shopee) vs `PO-071026-012` (Shopee - Barre Official): 7 unit Timbangan (`PEL260050`), Rp 434.875.
      3. `POCK2.071026.003` (Tokopedia - Shopee) vs `PO-071026-013` (Shopee - Rnk Mart): 12 pcs Toples Tabung (`PEL260054`), Rp 72.000.
      4. `POCK2.071026.004` (Tokopedia - Shopee) vs `PO-071026-011` (Shopee - Lionelplastik): 180 pack Plastik Kresek Besar (`PEL260080`), Rp 1.083.820.
    - Di site lama, keduanya sama-sama dibiarkan submitted karena belum dibersihkan. Di site baru, sisi generic eResto (`POCK2.*`) sengaja di-cancel pada pembersihan 8 Okt agar tidak terjadi dobel penerimaan barang, sedangkan PO toko Shopee spesifik dipertahankan aktif (`To Receive and Bill`).
  - **Sinkronisasi Tag Purchase Order PT. JURI (38 PO):**
    Atas permintaan user ("aku juga ingin tagnya di site lama taruh di site baru juga ya, untuk purchase order olehh company PT. JUARA ROTI INDONESIA"):
    - Ditarik seluruh tag dari `Tag Link` di site lama untuk PT. JUARA ROTI INDONESIA (terdapat 71 tag, didominasi nomor pesanan Shopee seperti `NO. PESANAN. 261002J39E0TXD`).
    - Sebanyak 38 PO yang berada dalam rentang migrasi dan aktif di site baru berhasil disinkronkan tag-nya menggunakan API Frappe `frappe.desk.doctype.tag.tag.add_tag` (38 sukses, 0 gagal).
    - Verifikasi langsung via `Tag Link` dan field `_user_tags` membuktikan 38 PO di site baru kini memiliki tag yang identik dengan site lama. Skrip: `pos_sync/sync_po_tags.py`.

- **2026-10-09 (Hapus Company OUTLET PAMERAN dari ERPNext Baru — SELESAI):**
  Atas instruksi user ("aku ingin kamu menghapus OUTLET PAMERAN di erpnext baru, lakukan dengan aman"):
  - **Preflight:** `OUTLET PAMERAN` (abbr `OTPAMERAN`, dibuat 2026-10-05) murni master tanpa transaksi —
    0 POS Invoice/Sales Invoice/GL Entry/Stock Entry/PO/SO/dll; hanya 221 akun, 5 warehouse,
    2 cost center, 2+2+2 template pajak, dan TDL0003.
  - **Blocker yang dibereskan sebelum delete:**
    (1) 1 baris `Allowed To Transact With` di supplier `PT. JUARA ROTI INDONESIA` → dihapus
    (dari 175 → 174 baris; satu-satunya link statis yang TIDAK di-cascade saat company dihapus);
    (2) 5 baris `Expense Claim Account` (Calls/Food/Medical/Others/Travel) → dihapus;
    (3) `TDL0003` (Transaction Deletion Record "delete transactions" yang dijalankan user pagi 09:13)
    → ternyata di-cascade otomatis oleh `Company.on_trash` (cancel manual ditolak 403, DocPerm TDL read+write saja).
  - **Eksekusi:** `DELETE /api/resource/Company/OUTLET PAMERAN` → 202. Cascade `Company.on_trash`
    membersihkan akun/warehouse/cost center/Item Default/Mode of Payment Account/template pajak/TDL
    dalam satu transaksi (v16.51/16.50: kondisi 0 GL & 0 SLE membuat cleanup penuh lolos).
  - **Backup:** `audit_logs/backup_OUTLET_PAMERAN_261009_092439.json` (298 KB, seluruh 221 akun + 5
    warehouse + 2 cost center + 6 template + baris supplier + TDL0003). Entri `Deleted Document` untuk
    Company tercatat (masih recoverable).
  - **Verifikasi 30+ doctype + 6 child pos_next (Price Group Outlet, POS Offer/Package/Recipe Company,
    Profile Group Member, Discount Code Company) + Contact/Address + MoP + ECT: SEMUA 0 sisa.**
    Parent `OUTLET` utuh (172 leaf company tersisa; default_company tetap `PT. JUARA ROTI INDONESIA`).
  - Skrip: `pos_sync/delete_outlet_pameran.py` (`--backup/--prep/--delete/--verify`, dry-run default,
    `--execute` untuk jalan). Idempoten (rerun = SKIP_EXISTS).

- **2026-10-09 (Migrasi Sales Order & Delivery Note 1–8 Oktober 2026 ke ERPNext Baru — SELESAI):**
  Atas instruksi user ("menarik sales order, delivery note pada rentang tanggal 1-8 oktober 2026 dari erpnext lama ke erpnext baru, pastikan ga duplikat ya!, pertahankan id lama"):
  - **Skop & Ekstraksi Data LAMA**:
    - Memperluas skop `migrate_outlet_so_dn_to_juri.py` dari `2026-10-07` menjadi `2026-10-08`.
    - Total terdata di LAMA: 106 SO dan 139 DN. Setelah filter kriteria intercompany (wajib memiliki `inter_company_order_reference` ke PO target):
      * 122 SO intercompany masuk scope (96 existing + 26 baru).
      * 126 DN intercompany masuk scope (101 existing + 25 baru).
      * 26 dokumen di-skip terdokumentasi (13 SO non-intercompany / FRC seperti Wahid Hasyim, Jogokariyan, dsb + 13 DN terkait / Delanggu yang sudah dimigrasi sebelumnya).
  - **Penanganan Master & Remap Bentrok Kode**:
    - Menambahkan remap bentrok kode item `BB260060 -> BB260046` (*Olesan Pastry 250 g Botol* di LAMA vs master *Olesan Pastry* di BARU, stock_uom g, factor Botol 250.0).
    - Menyiapkan 82 customer internal outlet di BARU via child table `companies` dengan izin transaksi ke `PT. JUARA ROTI INDONESIA`.
    - Memastikan kelengkapan 263 PO outlet di BARU (termasuk menginjeksi 4 PO tanggal 7 Okt yang baru dibuat: `PO221.071026.001`, `PO223.071026.005`, `PO223.071026.006`, `POO80.071026.003`) sehingga seluruh 122 SO memiliki rujukan baris PO 100%.
  - **Resolusi Duplikat Transaksi Native (Anti-Duplikasi)**:
    - `DN-081026-024` (RSUD AJIBARANG BANYUMAS, Rp 1.240.000): Di site baru terdapat dokumen yang dibuat manual hari ini bernama `DN-JURI-261009002`. Draft baru dihapus dan `DN-JURI-261009002` di-rename ke `DN-081026-024` sehingga ID asli terjaga dan tidak terjadi over-allowance.
    - `SLS-091026-002` (RS ISLAM SURABAYA A. YANI, Rp 6.192.600): Di site baru terdapat dokumen yang dibuat manual hari ini bernama `SORD-JURI-261009001` yang telah didelivery oleh `DN-JURI-261009001`. Dokumen draft/tanpa-delivery dihapus, dan `SORD-JURI-261009001` di-rename ke `SLS-091026-002`, menjaga keterhubungan ke DN tanpa duplikat.
  - **Hasil & Verifikasi**:
    - 122 Sales Order termigrasi (122 Submitted, Rp 965.474.771, 0 selisih rupiah).
    - 126 Delivery Note termigrasi (123 Submitted, 3 Cancelled, Rp 988.939.091, 0 selisih rupiah).
    - Seluruh 11 poin pengecekan independen berstatus **LOLOS** (Jumlah, Nilai, Docstatus, Baris, dan Link relasi SO->PO dan DN->SO).
    - Uji rerun membuktikan idempoten sempurna: 122/122 SO `SKIP_EXISTS` dan 126/126 DN `SKIP_EXISTS` (0 duplikat).
    - Laporan audit lengkap diperbarui di `pos_sync/Laporan_Migrasi_SO_DN_Outlet_ke_JURI.xlsx`.

- **2026-10-09 (Migrasi Lengkap PO eResto 8-9 Oktober 2026 ke ERPNext Baru — SELESAI):**
  Atas instruksi user ("masukan juga yang suppliernya internal gudang, btw itu merupakan company PT. JUARA ROTI INDONESIA, jadi gudangnya itu jadi warehouse untuk company tersebut. trus klo ada yang ngePO gudang itu maka sebenernya nge PO PT. JUARA ROTI INDONESIA, trus nama gudangnya itu jadi source warehouse ketika company itu sales order dan delivery note. klo nama divisi yang ngePo itu adalah nama company di erpnext baru"):
  - **Identifikasi Data eResto**: 16 PO terdata di jendela 8–9 Okt (13 PO bertanggal transaksi 8–9 Okt + 3 PO diinput/dibuat di eResto pada 8 Okt).
  - **Dua Kelompok PO Berhasil Dimigrasikan (Total 12 PO / Rp 70.175.680,00)**:
    1. **PO Supplier Eksternal (2 PO / Rp 27.597.500,00)**:
       - `POGPT.081026.001`: Es Polar -> `PT. JUARA ROTI INDONESIA` (Gudang Produksi - JURI), Rp 97.500,00 (Submitted, `docstatus = 1`).
       - `POGPK.021026.001`: Vivek Arieya Kresindo -> `PT. JUARA ROTI INDONESIA` (Gudang Peralatan - JURI), 9 item peralatan, Net Total Rp 25.600.000,00 + Charge instalasi via template `Investasi Outlet - JURI` Rp 1.900.000,00 - Diskon Rp 2.950.000,00 = Grand Total Rp 27.500.000,00 (Draft, `docstatus = 0`, status eResto `pending`).
    2. **PO Supplier Internal Gudang -> Outlet PO ke PT. JURI (10 PO / Rp 42.578.180,00)**:
       - Supplier diubah menjadi `PT. JUARA ROTI INDONESIA` (JURI), Company adalah nama divisi pemesan (outlet), Target Warehouse `Stores - <ABBR>`, Source Warehouse (`set_from_warehouse`) adalah gudang JURI terkait (`Gudang Jakarta - JURI`, `Gudang Barang Jadi - JURI`, `Gudang Vendor - JURI`), Price List `Harga Outlet`, Akun HPP `4210.000 - HPP Pembelian - <ABBR>`.
       - Rincian 10 PO: `PO084.081026.001` (RSAI BANDUNG, Rp 570.000, ds=1), `PO115.081026.001` (RS AMC BANDUNG, Rp 228.000, ds=1), `PO159.081026.001` (RS IHC WONOLANGAN PROBOLINGGO, Rp 723.600, ds=1), `PO162.081026.001` (RSUD GRATI KABUPATEN PASURUAN, Rp 1.315.000, ds=1), `PO180.081026.001` (RS ISLAM AR-RASYID PALEMBANG, Rp 4.670.900, ds=1), `PO202.081026.001` (RSCM JAKARTA, Rp 1.419.700, ds=1), `PO204.081026.001` (RS UNIMEDIKA SETU BEKASI, Rp 502.500, ds=1), `PO229.081026.001` (RS RIDHOKA SALMA CIKARANG, Rp 90.000, ds=0), `POO91.081026.001` (RSUD DR MOHAMMAD ZYN SAMPANG, Rp 10.320.480, ds=1), `PO335.081026.001` (RSUD KRAMAT JATI, Rp 22.738.000, ds=1).
       - Company baru `RSUD KRAMAT JATI` (ABBR `RSUKJ`) dibuat di bawah `OUTLET`, didaftarkan ke Fiscal Year 2026, diizinkan di Supplier JURI, serta dibuat customer internal `CUST-260212`.
  - **Dokumen Dilewati (4 Dokumen)**:
    - 3 PO `POAGOU` (`051026.001`, `071026.001`, `081026.001`): permintaan asset non-stok (*Partisi Ruang Lipat*) tanpa SKU/inventory eResto dan tanpa Item Code ERPNext.
    - 1 PO `POGVR.081026.001`: transfer antar gudang internal JURI berstatus rejected di eResto.
  - **Idempotensi**: Seluruh 12 dokumen terdaftar dengan ID identik eResto. Rerun script = `12 SKIP_EXISTS` (0 duplikat).
  - **Laporan & Skrip**: `pos_sync/migrate_po_eresto_8_9_okt.py` dan laporan Excel `pos_sync/Laporan_Migrasi_PO_eResto_8_9_Okt2026.xlsx` (Validation: LOLOS).

- **2026-10-09 (Tarik PO eResto Gudang Jakarta 9 Okt 2026 → ERPNext Baru — SELESAI):**
  Atas instruksi user ("tarik data purchase order ke gudang jakarta di eresto ke erpnext, kalau di erpnext baru itu PT juara roti indonesia trus warehousenya ketika sales order pake gudang jakarta hari ini 9 oktober 2026"):
  - **Scope & Hasil**: 11 PO eResto supplier `Gudang Jakarta` tanggal 9 Okt / **Rp 108.445.265,00** termigrasi ke Cloud Baru dengan **ID identik eResto** (`PO101.091026.001` s/d `PO216.091026.001`), 2 Submitted (`PO138`, `PO216` — status eResto `processing`) + 9 Draft (status `pending`/`rejected`), konvensi sama dengan migrasi 8 Okt: Company = divisi outlet, Supplier = `PT. JUARA ROTI INDONESIA`, `set_warehouse` = `Stores - <ABBR>`, `set_from_warehouse` = `Gudang Jakarta - JURI` (dipakai sebagai source warehouse alur SO/DN JURI), Price List `Harga Outlet`, beban `4210.000 - HPP Pembelian - <ABBR>`.
  - **Perluasan mapping item (+6 SKU baru)**: `BB0257`→`PEL260071` (Gelas Cup 9 oz; UOM `Pack` eResto → `slop` cf=50, preseden PO120.051026.001), `BB0304`→`BB260037`, `BB0305`→`BB260038`, `BB0103`→`BB260044`, `BB0120`→`BB260019`, `BB0143`→`PEL260085`. 33 SKU total ter-map; resolusi UOM selalu dari master Item (tidak menebak), fallback artefak cf=1 → stock_uom dengan catatan di laporan.
  - **Jebakan baru terdokumentasi**: `frappe.client.rename_doc` wajib **form-encoded**; kalau session default `Content-Type: application/json` → HTTP 417 `Invalid request body` (rename gagal, dokumen tertinggal ID fallback `PO-<ABBR>-<yymmdd>###`). Fix: header form-urlencoded + mode self-heal pada jalur SKIP_EXISTS (rerun memperbaiki nama yang belum ter-rename).
  - **Verifikasi lintas-site**: 11/11 LOLOS (nilai, jumlah baris, docstatus vs status eResto, math baris qty×rate=amount & stock_qty=qty×cf), total Rp 108.445.265,00 klop ≤Rp1; rerun = 11 SKIP_EXISTS (0 duplikat). Laporan `pos_sync/Laporan_Migrasi_PO_Gudang_Jakarta_9Okt2026.xlsx` (sheet Rekap_Migrasi/Raw_eResto/Cross_Check/Validation/Catatan).
  - **Skrip**: `pos_sync/migrate_po_gudang_jakarta_9okt.py` (`--dry-run`/`--verify`/`--only`/`--date`; idempoten).
  - **Catatan temuan (di luar scope, tidak disentuh)**: (a) `PO084.081026.001` di BARU tercatat 3 Pack cf=50 @190.000 (edit manual 09:08:31) vs sumber eResto 5 Pack cf=150 @114.000 — total sama Rp570.000, menunggu keputusan user; (b) 8 PO Gudang Jakarta sebelum 9 Okt belum ada di BARU (`POO46.051026.001`, `POO96.051026.001`, `POO10.051026.001`, `PO169.051026.001`, `POO41.051026.001`, `PO091.051026.001`, `POO12.061026.001`, `PO339.071026.001`) — sudah diverifikasi tidak ada under ID lain (cari company+tanggal+total), tercatat di sheet Catatan; (c) data eResto hari berjalan masih mengalir (jumlah PO bertambah dari 6→11 selama sesi) — rerun script aman.

- **2026-10-09 (Revisi Item Master BHP260028 & Purchase Receipt PR-061026-017 — SELESAI):**
  Atas instruksi user ("item BHP260028 ingin dijadikan maintain stock... perlu batalin PR-061026-017 trus ganti item master baru baliki lagi PR-061026-017... saldo awal 30 Sep malam 43 Pcs ke gudang bahan baku PT. JURI"):
  - **Item Master (`BHP260028` Tisu Pabrik):** Diubah menjadi `is_stock_item = 1` via Server Script bypass validasi form `Item.cant_change()`. Child table `Item Default` untuk `PT. JUARA ROTI INDONESIA` diset `default_inventory_account = "1145.000 - Finished Good - JURI"`, cache dokumen dibersihkan via `doc.clear_cache()`.
  - **Opening Stock 30 Sep (`RECO-JURI-261009001`):** Dibuat dokumen Stock Reconciliation bertanggal 2026-09-30 23:59:00 untuk 43 Pcs `BHP260028` @ Rp 6.396,00 di `Gudang Bahan Baku - JURI`. SLE dan GL Entry (`1145.000` Debit Rp 275.028,00 / `1171.000` Credit Rp 275.028,00) tercatat dan tersubmit sempurna (`docstatus = 1`).
  - **Siklus PR-061026-017:**
    - Dokumen lama dibatalkan (`status = Cancelled`, SLE pembatalan tercatat).
    - Dokumen lama di-rename ke `PR-061026-017-OLD` agar identifier asli bebas.
    - Dibuat PR baru dari `PO-021026-005` via `make_purchase_receipt`, di-rename menjadi `PR-061026-017`, dan disubmit (`docstatus = 1`).
    - Menambah stok +192 Pcs ke `Gudang Bahan Baku - JURI`, PO terhubung kembali 100% received, dan GL Entry tercatat (`1145.000` Debit Rp 1.228.032,00 / `2115.000` Credit Rp 1.228.032,00).
  - **Hasil Akhir Bin:** Saldo akhir fisik `BHP260028` di `Gudang Bahan Baku - JURI` tercatat **235 Pcs** (43 saldo awal + 192 penerimaan) dengan total nilai persediaan Rp 1.503.060,00 @ Rp 6.396,00.

- **2026-10-08 (audit stock balance 30 Sep 23:00 LAMA vs BARU — SELESAI, menunggu keputusan angka):**
  Atas instruksi user ("cek pada stock balance di erpnext lama dan baru per
  30 september jam 23:00, cek apakah ada yang sama dan yang beda, kalau ada
  yang beda cari tau penyebabnya, laporin dulu ke saya kenapa beda").
  **Revisi scope 2026-10-09** ("kecualikan company selain PT. JUARA ROTI
  INDONESIA"): semua angka di bawah = hanya company PT. JUARA ROTI
  INDONESIA (gudang ROPI↔JURI); Stores - RPMD & company outlet lain
  dikecualikan (`COMPANY` konstanta di script; `--dump` memfilter company).
  - **Metode:** saldo(wh,item)@cutoff = `qty_after_transaction` baris SLE
    terakhir <= cutoff, is_cancelled=0, company=JURI, dua cutoff: 23:00:00
    literal dan EOD 23:59:59. 126.881 baris SLE LAMA + 288 baris BARU
    (semuanya RECO opening 30 Sep). **Catatan: `sum(actual_qty)` TIDAK
    dipakai** — baris ADJ legacy LAMA kadang act=0 dgn qat melompat; qat
    otoritatif.
  - **Hasil (418 posisi item×gudang, gudang berpasangan ROPI↔JURI):**
    potret 23:00: 214 sama / 204 beda; potret EOD: **232 sama persis /
    186 beda**. 25 posisi "beda di 23:00 tapi sama di EOD" krn dokumen
    opening susulan/koreksi BARU berposting backdate 23:30-23:35
    (RECO 261007001/2/3/4/5/7, 261008001/2).
  - **Penyebab beda (semua terklasifikasi, sheet per kategori):**
    32 TIDAK_DIHITUNG_OPNAME (BARU tdk simpan saldo; LAMA masih punya —
    mt. Margarine Dough 1.5jt, Dough PJ* sisa di GBJ, Tutup Paper Cup,
    dst.), 66 BELUM_DIINJEKSI (semua di gudang GA 32/Outlet 5/Peralatan
    11/Vendor 5/R&D 13 — opening-nya di BARU diposting 2 Okt atau belum),
    16 BUKU_LAMA_VS_FISIK (opname fisik eResto vs buku LAMA drift sblm
    migrasi; terbesar Patisy 600.400 vs 504.400, Plastik Wayang UOM
    Pcs→Pack 166.000 vs 4!), 14 KOREKSI_DISENGAJA (RECO-JURI-261008002
    WIP ×7, 261007006 Cold Storage ×6, 261007007 BB26008), 5 CEK_KHUSUS
    (UOM BB260021; kode bentrok BB260060; PEL260075 konversi 10x;
    PEL260087 GBJ/JKT; PEL260019 mapping), 7 WAKTU_OPNAME (opname
    pagi/siang vs buku malam: PR-300926-013/19-25 sore hari), 2
    ITEM_BARU (BB260061 Kopi Hitam 4.930 + BB260062 Susu Bubuk 56.000
    — item baru hasil opname GBJ, tidak ada di LAMA), 2
    POSISI_LAMA_JAM_LAIN, 42 GUDANG_TANPA_PASANGAN (Mini Outlet 29,
    Testing Manufacture 12, WIP Testing 1 belum ada di BARU).
    (PJO2602/4/5 & RP001/2/3/CR001/GM001 bundle — dulu khsusus di RPMD,
    kini di luar scope.)
  - **Keputusan yang diminta ke user (BELUM dikerjakan apapun):**
    (a) 16 BUKU_LAMA_VS_FISIK — angka mana yang mengikat (opname fisik
    eResto atau buku LAMA)? (b) PEL260087: RECO BARU menetapkan
    201.000/34.000, buku LAMA EOD 238.100/27.850. (c) BB260021 UOM
    Pcs(LAMA) vs Pack(BARU) + item bentrok kode BB260057-60 (LAMA:
    Botol/Gula Cair/Olesan; BARU: Bubuk Hepi). (d) gudang LAMA tanpa
    pasangan (Mini Outlet dll) apakah perlu dibuat di BARU.
  - **Artefak:** `pos_sync/compare_stock_sep30.py` (`--dump/--compare/
    --report`; cache `pos_sync/stock_sep30_dump/`), laporan
    `pos_sync/Laporan_Stock_Sep30_LAMA_vs_BARU.xlsx` (14 sheet; kategori
    tiap baris + catatan evidence). Verifikasi: totals per kategori
    dihitung ulang, spot-check manual BB260004/16/17/20/25, PEL260018/30/
    54/87, BB260009/34-37 — semua klop dgn rantai SLE LAMA.

- **2026-10-08 (sinkronisasi & migrasi penuh WO, Form Order, dan Serah Terima 6-8 Okt — SELESAI):**
  Atas instruksi user ("menarik wo dari tanggal 6-8 oktober, trus masukin ke site baru. tapi pastikan ga duplikat!. klo duplikat skip tapi misal ada update an maka boleh menimpa, pertahankan id dan data2nya ya. cek production plan, workorder trus seluruh inputan proses di workorder pada production app, trus pada stock entry form order, trus serah terima barang jadi di warehouse app").
  - **Zero Duplicate & In-place Sync**: Dokumen yang sudah ada di-update/ditimpa jika terdapat perubahan data tanpa membuat duplikat, mempertahankan nomor ID asli (`MFG-WO-2026-xxxxx`).
  - **Production Plan (PP261006001, PP261007001, PP261008001)**: Status dan total produced qty disinkronkan 100% klop dengan site lama:
    * `PP261006001`: In Process (29.664 / 29.578 Pcs)
    * `PP261007001`: Completed (24.384 / 24.118 Pcs)
    * `PP261008001`: In Process (6.053 / 29.578 Pcs)
  - **186 Work Order (6-8 Okt)**: 186/186 WO cocok 100% dengan site lama:
    * 62 WO 8 Okt di-submit dan disinkronkan seluruh field prosesnya.
    * 23 WO 7 Okt (sebelumnya In Process) di-update menjadi Completed dengan produced_qty dan waktu packing sesuai site lama.
    * Seluruh 5 tahapan di `production_app` (Persiapan, Material, Pre-Packing, Post-Packing, Finish) terisi penuh.
    * Seluruh child table `required_items[].transferred_qty = required_qty` disinkronkan sehingga status Material tampil "Lengkap / Cukup" (0 kekurangan).
  - **Form Order (`production_app` & `warehouse_app`)**:
    * 1 Form Order 8 Okt `MAT-MR-2026-01016` dibuat dan diaktifkan (`custom_is_form_order = 1`).
    * Stock Entry pengiriman Form Order `SE-MTF-261008001` (ref `MAT-STE-2026-09669`, 20 item stock) disubmit.
    * Seluruh 9 Form Order di `production_app` tampil dengan status **"terkirim"** (100%).
  - **Serah Terima Barang Jadi (`warehouse_app` & `production_app`)**:
    * 28 Material Request serah terima (`MAT-MR-2026-01017` s/d `01046` & `01043`) dibuat, direname ke ID asli, dan disubmit.
    * 28 Stock Entry Material Transfer CS -> GBJ (`SE-MTF-261008002` s/d `029`) disubmit dengan rujukan MR asli.
    * Papan Serah Terima Gudang (`warehouse_app`) dan status serah terima WO (`custom_handover_status = "Terkirim"`) 100% cocok dengan site lama.
  - Script: `pos_sync/sync_wos_6_8_okt.py`.

- **2026-10-08 (bersih-bersih duplikat PO PT. JUARA ROTI INDONESIA — SELESAI):**
  Atas instruksi user ("untuk purchase invoice tuh yang site lama cuma test aja,
  trus yang site baru ini beneran ada. trus eksekusi bersihnya silahkan").
  - **Konfirmasi user:** PI site LAMA = trial/test saja; site BARU = data
    sebenarnya. Karena itu sisi-duplikat yang dibuang mengikuti aturan
    "pertahankan rantai yang tertaut PI di BARU".
  - **Script** `pos_sync/bersih_po_juri.py` (default dry-run; `--execute`).
    Laporan `pos_sync/Laporan_Bersih_PO_JURI.xlsx` (Aksi, Verifikasi,
    Rantai_Dipertahankan). Env: `/tmp/eresto_prod.env` (site BARU saja).
  - **Guard pra-eksekusi per dokumen:** dipastikan tidak ada PR/PI submitted
    yang merujuk target di luar pasangan cancel; Payment Entry dicek; rerun
    aman (draft 404 / PO ds=2 di-skip, bukan error).
  - **Hasil eksekusi (0 gagal):**
    - **26 draft eResto-ID dihapus** (duplikat PO native submitted).
    - **12 dokumen di-cancel**: 4 PO eResto submitted 7 Okt
      (`POCK2.071026.001..004`, kembaran native PO-071026-011..014 dipakai);
      3 PO native + 3 PR native dari 3 pasangan stok dobel
      (`PO-061026-005`/`PR-061026-011`, `PO-061026-006`/`PR-061026-012`,
      `PO-061026-007`/`PR-061026-014`); 2 PO native tanpa-rantai
      (`PO-021026-020`, `PO-021026-022` — duplikat native-native yang
      ditemukan saat verifikasi akhir; sisi ber-PR `PO-061026-003`/
      `PO-061026-001` dipertahankan).
  - **Verifikasi live:** draft eResto-ID tersisa 0; eResto-ID submitted = 5
    (`POCK2.250926.001`, `POCK2.250926.003`, `POCK2.280926.001`,
    `POCK2.300926.002`, `POGBJ.290526.001`); PR submitted 74→71; PO JURI
    124→98 (88 submitted + 10 cancelled). Rantai PI tetap utuh: keep-side PR
    jadi `Completed` / `per_billed 100%` (PI 261008007/008/012 masih nyambung,
    child-row po_detail/pr_detail dicek ada di dokumen). GL cancelled
    ter-reversal (`is_cancelled=1`), bukan hilang.
  - **Koreksi stok terbukti benar:** Bin Gudang Jakarta turun tepat
    BB260031 −204.000 g, PEL260075 −1.000, PEL260011 −5. 3 Repost Item
    Valuation otomatis dibuat sistem → selesai (Completed), valuasi Bin
    dihitung ulang (BB260031 stock_value 44.666.592→22.945.556 dst).
  - **Sisa terdokumentasi:** item 'Toko Bahan Kue vs Toko Santi' & Ihya
    harga 22.400 vs 24.800 (native keeper yang dipakai, mengikuti laporan
    banding); 182 PO window belum masuk BARU (item lama, belum di-scope).

- **2026-10-08 (audit banding PO PT. JUARA ROTI INDONESIA: site LAMA vs BARU — SELESAI):**
  Atas instruksi user ("cek di erpnext lama dulu trus bandingin dengan yang baru.
  fokus di company PT. JUARA ROTI INDONESIA. yang kamu input yang draft itu
  kebanyakan dari eresto langsung kan, jadi PO pabrik/PT udah diinput langsung
  dari erpnext, jadi idnya pake erpnext yang asli bukan yang dari eresto.
  cocokin dulu sih tanggalnya dan itemnya trus suppliernya").
  - **Scope:** semua PO `company = PT. JUARA ROTI INDONESIA` di kedua site
    (LAMA 807 total / 280 di jendela 1 Sep–9 Okt; BARU 124).
    Script `pos_sync/compare_po_juri_lama_baru.py` (`--refresh`; cache
    `po_juri_dump/`), laporan `pos_sync/Laporan_Banding_PO_PT_JURI.xlsx`.
  - **Pola ID terbukti:** LAMA = 34 eResto-ID + 246 native (`PO-<DDMMYY>-<NNN>`);
    BARU = 34 eResto-ID (26 **Draft** + 8 Submitted) + 89 native; 89/89 native
    BARU ada di LAMA.
  - **Temuan utama:** **26/26 draft eResto-ID punya kembaran PO native
    (Submitted) di BARU** — item+qty cocok 100%, tanggal sama/±1 hari,
    supplier sama, total sama atau ×1.11 (PPN). Kembaran native dibuat lebih
    dulu di LAMA (2 Okt dsb) lalu dimigrasi; draft eResto dibuat 6–7 Okt
    18:47–18:48 oleh `ropierpnext@gmail.com`. → **draft = duplikat, bukan PO baru.**
  - **3 pasangan stok dobel** (PO+PR dua-duanya submitted, di BARU & LAMA):
    `POCK2.250926.001`/`PR-011026-021` ↔ `PO-061026-005`/`PR-061026-011`
    (BB260031 17 ctn); `POCK2.250926.003`/`PR-011026-020` ↔
    `PO-061026-007`/`PR-061026-014` (PEL260075 100 Pack);
    `POCK2.280926.001`/`PR-011026-022` ↔ `PO-061026-006`/`PR-061026-012`
    (PEL260011 5 Pcs). Sheet `Double_Receipt`.
  - **Anomali terdokumentasi (sheet `Rekomendasi_Draft`):** supplier draft
    'Toko Bahan Kue' vs native 'Toko Santi' (2 PO, Rp110rb & Rp275rb);
    Ihya Wijaya harga draft 22.400/kg vs native 24.800/kg (Rp6,72 jt vs
    Rp7,44 jt); Es Polar UOM draft zak(12kg) vs native kg; 1 draft
    tanggalnya 2 Okt vs native 25 Sep (item sama); `POCK2.021026.003` punya
    2 kandidat native (PO-021026-022 tanpa PR vs PO-061026-001 dgn PR).
  - **1 PO Mei** `POGBJ.290526.001` (Alkindo, Rp120 jt) tidak punya kembaran
    native — memang PO asli Mei (sudah ada PR-061026-015 + PI).
  - 182 PO LAMA (window) belum ada di BARU (157 native + 25 eResto-ID Sep)
    — di luar scope audit ini, bahan keputusan migrasi lanjutan.

- **2026-10-08 (migrasi faktur pembelian eResto Okt — divisi sentral — SELESAI):**
  Atas instruksi user ("yang diambil divisi Gudang Barang Jadi - PH Klaten,
  Gudang Produksi Klaten, Gudang Jakarta saja, trus kecualikan supplier
  [gudang internal]. cek dulu di erpnext lama apakah ada invoice serupa cek
  berdasarkan id atau daftar item name juga cek qty dan unitnya dan harganya,
  kalau udh ada maka migrasikan ke erpnext baru, gunakan id asli eresto atau
  dari erpnext lama. kecualikan item deactivate").
  - **Scope:** dari 141 faktur eResto Okt (tarikan `fetch_po_invoiced_okt.py`),
    filter divisi sentral (GBJ/GPK/GJKT) + supplier eksternal + PO pre-Okt →
    **7 faktur / Rp104.117.742 / 5 supplier**.
  - **Cek lama:** pembelian supplier ini TIDAK dicatat sebagai Purchase Invoice
    di site lama — semuanya **Purchase Receipt** (nomor PO eResto di baris item
    `purchase_order`). Matching per faktur: nama item + qty + unit + harga +
    total. Semua ketemu pasangannya; 3 faktur rate-bedanya wajar (mis. Mitra
    270.000 vs faktur 299.243,23 — PI pakai harga faktur).
  - **Hasil:** 7/7 faktur target punya PI di site baru, total **klop ≤Rp1**
    vs faktur eResto. 2 PI sudah ada sebelumnya (Sinnar `261008004`, Alkindo
    `261008001`); 5 PI baru dibuat: `261008007` (Ayla), `261008008`
    (Tokopedia), `261008009` (Mitra), `261008010` (Surya), `261008012`
    (Sinar) — semua PPN 11% (kecuali Tokopedia, tanpa pajak seperti PR-nya),
    `bill_no` = nomor INV eResto, link native ke PO/PR.
  - **PO+PR Sinar** (`POCK2.300926.002` + `PR-081026-005`) belum ada di baru
    → dimigrasi dari lama dengan ID identik (rename_doc); PO kini
    billed 100% / Completed. Sisa 4 PO target lain sudah ada.
  - **Repair:** PI Sinar pertama (`261008011`) terbuat tanpa `po_detail`
    → PO tetap 0% billed; di-cancel lalu di-recreate `261008012` dengan link
    penuh → PO 100% billed. Script di-fix (`cfg.get("po_detail") or
    tgt.get("po_detail")`). `261008011` tercatat Cancelled (pola sama dgn
    PI batal lain di site).
  - **Item nonaktif:** `BB0174 'TIDAK AKTIF Olesan Pastry'` (di faktur Sinnar
    yang PI-nya sudah ada) dipetakan ke item aktif `BB260046`; tidak ada item
    nonaktif di 5 faktur baru (sheet `Skipped` kosong).
  - **Catatan GBBK** (divisi Gudang Bahan Baku — tidak diminta user):
    4 faktur pre-Okt; `261008002` Paid; `261008005`/`261008006` **Cancelled
    (perlu keputusan user)**; `INVGBBK.081026.001` (Heri Wahyu, Rp3,57 jt)
    belum ada PI — kandidat. Sheet `GBBK_Catatan`.
  - Script `pos_sync/migrate_pi_central_okt.py` (`--dry-run/--only`;
    idempoten via `bill_no`+docstatus<2). Laporan
    `pos_sync/Laporan_Migrasi_PI_Central_Okt2026.xlsx` (Rekap_Faktur,
    Cek_Lama_Line, Migrasi_PO_PR, GBBK_Catatan, Skipped, Validation LOLOS).
  - Rerun = 7 SKIP_EXISTS (idempoten, tidak menduplikasi).

- **2026-10-08 (tarik PO eResto yang difaktur Okt 2026 — SELESAI):**
  Atas instruksi user ("tarik po dari eresto yang diinvoice per oktober 2026,
  po sebelum oktober tapi dinvoice oktober").
  - **Endpoint baru terbukti:** `/v2/purchase_invoices` (sebelumnya belum
    terdokumentasi) — list faktur + filter `transaction_date[geq/leq]` ISO,
    embed `purchase_id`/`purchase.purchase_number`/`purchase_invoice_items`.
    Jebakan: `purchase` embedded TIDAK memuat tanggal PO → tanggal PO diambil
    dari `/v2/purchases/{id}/detail`.
  - **Hasil:** 141 faktur Okt 1–8 (Rp1.066.626.017) → 139 PO unik; 1 faktur
    quick purchase tanpa PO (`IRPO92.081026.001`, sheet Skipped). Dari 139 PO:
    **66 PO sebelum Okt difaktur Okt** (Rp679.740.086; 65 PO Sep + 1 PO
    `POGBJ.290526.001` 29 Mei) + 73 PO lahir Okt (referensi). Faktur Okt atas
    66 PO target = Rp603.092.307; 892 baris item.
  - Script `pos_sync/fetch_po_invoiced_okt.py`
    (`--date-from/--date-to/--refresh`; cache `pos_okt_dump/`), laporan
    `pos_sync/Laporan_PO_Diinvoice_Okt2026.xlsx` (Raw_Faktur_Okt,
    Raw_PO_Sebelum_Okt, Raw_Items, Raw_PO_Okt, Skipped, Validation).
    **Tarik saja** — belum ada POST/migrasi; keputusan lanjutan menunggu user.
  - `KNOWLEDGE.md` §4 + `docs/01-eresto-api.md` diperbarui (endpoint baru).

- **2026-10-08 (persiapan publikasi repo GitHub + pembersihan kredensial — SELESAI):**
  Atas instruksi user ("boleh lakukan commit dan push. env dan kredensial
  jangan diikutkan").
  - **Scrub kredensial:** 19 script (`pos_sync/*.py` + 4 di root) yang masih
    memuat API key Frappe hardcoded (cloud baru, cloud lama, dev lokal 8082)
    diubah membaca dari env (`os.environ.get("ERPNEXT_API_KEY", "")` /
    `ERPNEXT_OLD_CLOUD_API_KEY` / `ERPNEXT_OLD_API_KEY`); 3 baris kunci di
    `PROJECT_STATE.md` diganti `[API-KEY-FROM-ENV]`. Verifikasi: 0 hex-pair
    tersisa di seluruh repo teks, 57 xlsx dipindai bersih, 21 script
    `py_compile` LOLOS, scan JWT/Bearer/eResto-token bersih.
  - **`.gitignore`** dibuat: `.venv/`, `*.env`, `.DS_Store`, `__pycache__/`,
    `.zcode/`, cache/dump besar (`pos_sync/prod_src/`, `*_dump/`,
    `wo_dump*/`, `oct7_dump/`, `wip_audit/`, `pf_dump/`, `window/`,
    `.cache_details*`), dan **`Backup SIte Production/`** (terbukti memuat
    api_key + api_secret — wajib tidak dipush).
  - **`README.md`** ditambahkan (orientasi repo, tiga sistem, dua rantai
    produk, cara jalan, pola verifikasi) sebagai pintu masuk sebelum
    `KNOWLEDGE.md` / `AGENTS.md` / `PROJECT_STATE.md`.
  - Belum ada git history sebelumnya, jadi tidak ada kunci yang pernah
    ter-push; rotasi tetap disarankan karena nilainya pernah plaintext di disk.

- **2026-10-08 (KNOWLEDGE.md — basis pengetahuan untuk AI pengguna lain — SELESAI):**
  Atas instruksi user ("membuat dokumen untuk pengetahuan AI lain... tinggal
  push ke github, pengguna lain pake AI langsung paham soal eResto, ERPNext
  baru dan lama").
  - `KNOWLEDGE.md` (root) dibuat: peta tiga sistem (eResto = sumber read-only
  sampai cutover, ERPNext Baru = target, ERPNext Lama = sumber historis),
  daftar URL lengkap termasuk seluruh Manager v2 hash route dari user
  (`purchasing/*`, `inventories/inventory_reports/*`, `inventory_sales/*`)
  + `sales_report/orders/orders` yang sudah dipakai proyek; 10 endpoint
  API eResto + kontrak JSON; aturan bisnis (SKU map, void/refund,
  outlet=company, Price Group/Shift Group, rantai dough→matang→bundle,
  idempotensi); 17 jebakan Frappe/ERPNext terbukti; cara jalan + env
  (nama saja, tanpa nilai); indeks docs/01–11; glosarium.
  - Skill `.agents/skills/eresto-erpnext/SKILL.md` ditambahkan sebagai
  router tipis (aturan keras + pointer) agar AI tool lain auto-discover
  setelah clone; pointer juga dipasang di `AGENTS.md` (Project state + Docs).
  - Tanpa kredensial di semua file baru.

- **2026-10-08 (injeksi stok company TRAINING via Material Receipt Delanggu — SELESAI):**
  Atas instruksi user ("memasukan stock di eprnext baru pada company training. pake stock reconcilation di pku delanggu, tapi ini material receipt aja!").
  - 1 Stock Entry berjenis Material Receipt `SE-MR-261008001` dibuat dan disubmit (`docstatus = 1`) untuk Company `TRAINING` ke warehouse `Stores - TRNG`.
  - Seluruh 30 item persediaan fisik dari seluruh Stock Reconciliation RS PKU MUHAMMADIYAH DELANGGU (`RECO-RPMD-261006001`, `002`, `003`, `261008001`) dimasukkan lengkap dengan quantity fisik dan valuation rate persis (total Rp 6.277.422,89).
  - 30 SLE berhasil diposting, 0 error, saldo fisik di `Stores - TRNG` kini terisi lengkap untuk seluruh bahan baku, adonan, produk jadi, dan kemasan. Skrip: `pos_sync/create_training_material_receipt.py`.

- **2026-10-08 (revisi akun PI-JURI-261008001 & PAY-JURI-261008001 ke default company — SELESAI):**
  Atas instruksi user ("merevisi account pada purchase invoice ini PI-JURI-261008001 dan paymentnya, pake default dari company yang terbaru ya!. ini di erpnext baru").
  - **Identifikasi Masalah**: Sebelumnya `PI-JURI-261008001` memakai `credit_to` akun pajak (`2141.000 - Hutang Pajak - JURI`), dan `PAY-JURI-261008001` memakai `paid_from` akun DP (`2121.001 - Dp Penjualan - JURI`) serta `paid_to` akun pajak (`2141.000 - Hutang Pajak - JURI`).
  - **Eksekusi Koreksi**: Dokumen dibatalkan (`docstatus = 2`), ledger entries dibersihkan dengan aman (`delete_linked_ledger_entries = 1`), dan dibuat ulang dengan ID persis via `rename_doc` menggunakan default akun resmi `PT. JUARA ROTI INDONESIA`.
  - **Hasil Revisi**:
    - `PI-JURI-261008001` (`Submitted`, Status: `Paid`, Outstanding: `0.0`): `credit_to` = `2111.001 - Hutang Dagang Dalam Negeri - JURI`, `expense_account` = `2115.000 - Stock Diterima Tapi Tidak Ditagih - JURI`, PPN = `1152.001 - PPN Masukan - JURI`.
    - `PAY-JURI-261008001` (`Submitted`): `paid_from` = `1121.009 - Rekening Bank Out - BCA 0948585262 - JURI`, `paid_to` = `2111.001 - Hutang Dagang Dalam Negeri - JURI`, child reference account = `2111.001 - Hutang Dagang Dalam Negeri - JURI`.
  - **Verifikasi**: GL entries kedua dokumen 100% klop dan seimbang; billed_amt PO `POGBJ.290526.001` terhubung akurat. Property Setter sementara sudah dibersihkan.

- **2026-10-08 (migrasi Production Plan & Work Order 8 Okt 2026 — SELESAI):**
  Atas instruksi user ("menarik production plan 8oktober 2026 disite lama, trus kan konek ke workordernya juga").
  - **Production Plan `PP261008001`**: Ditarik dari site lama dan dibuat di site baru dengan nama ID identik `PP261008001`, status `Submitted` (`docstatus = 1`), 62 baris `po_items` (idx 1..62), total planned qty 29.578 Pcs.
  - **62 Work Order (`MFG-WO-2026-04238` s/d `MFG-WO-2026-04299`)**: Seluruh 62 WO dimigrasikan dengan ID persis via `rename_doc`. Status berstatus `Draft` (`docstatus = 0`) sesuai dengan kondisi aslinya di site lama (karena WO 8 Okt baru di-generate pada pagi hari dan belum diproses/disubmit).
  - **Relasi 100% Klop**: Setiap WO terhubung langsung ke `PP261008001` (`production_plan = 'PP261008001'`) dan child row `po_items`-nya (`production_plan_item = row_name`).
  - **Tampil di `production_app`**: Seluruh 62 WO aktif dan langsung muncul di lane **Persiapan** (`stage: persiapan`), siap untuk diinput persiapan adonan (suhu, penimbang, kru, dll.) oleh operator.
  - **Verifikasi**: 62/62 WO cocok 100% (0 selisih item/qty/BOM/docstatus, 0 gagal, 0 duplikat). Skrip: `pos_sync/migrate_wo_08okt.py`.

- **2026-10-08 (penuntasan WO 1–7 Okt & Zero Negative Stock — SELESAI, docs/10 §12):**
  Atas instruksi user ("eksekusi... migrasi WO tanggal 1-7 Oktober aman tanpa ada yang minus,
  seluruh proses di WO juga diisi: Persiapan, Material, Pre-Packing, Post-Packing, Finish").
  Skrip eksekusi `pos_sync/execute_fix_wip_and_wos.py`; laporan Excel
  `pos_sync/Laporan_Migrasi_WO_1_7_Okt2026_Final.xlsx`:
  - **Zero Negative Stock**: Seluruh 13 Bin negatif di sistem berhasil dibersihkan via 3 RECO
    baru (`RECO-JURI-261008001` Gudang Bahan Baku 5 item; `RECO-JURI-261008002` WIP 7 item;
    `RECO-RPMD-261008001` Stores-RPMD PG001). Cek live: **0 Bin negatif di seluruh warehouse
    JURI & RPMD** (Gudang Bahan Baku 0, WIP 0, Gudang Produksi 0, Cold Storage 0, Stores RPMD 0).
  - **Sinkronisasi 5 Tahapan 23 WO 6 Okt (`PP261006001`)**: 23 WO `MFG-WO-2026-04119..04141`
    disinkronkan field-by-field dari site lama via `frappe.client.set_value` + Property Setter
    `allow_on_submit` sementara (telah dikembalikan ke 0).
    Tahap 1 Persiapan (adonan, jam, suhu, penimbang, leader, kru), Tahap 2 Material (transfer 100%),
    Tahap 3 Pre-Packing (confirmed=1, good/reject/trial/sisa, jam pembekuan),
    Tahap 4 Post-Packing (confirmed=1, good/reject/trial/sisa, jam packing, QC packing),
    Tahap 5 Finish (produced_qty, process_loss_qty, status Completed, actual start/end).
  - **Paritas Akhir 306 Work Order (1–7 Okt)**: 306/306 WO (100% Ada), **306/306 WO (100% LOLOS /
    0 Selisih)** dengan tahapan di site lama (283 Selesai, 23 In Process batch 7 Okt).
  - **Material Transfer Child Rows & Form Order (2026-10-08)**:
    (1) Pada Plan `PP261007001` (62 WO 7 Okt), seluruh child table `required_items.transferred_qty`
    disinkronkan = `required_qty` (540 baris bahan). Di UI `production_workspace`, panel **Material**
    kini 100% berstatus **"Material lengkap — Semua material telah ditransfer"** (chip hijau "Cukup",
    0 kekurangan bahan pada 306/306 WO).
    (2) Seluruh 8 Material Request Form Order 1–7 Okt (`MAT-MR-2026-00786..00972`) diaktifkan
    `custom_is_form_order = 1` dan direlink penuh ke Stock Entry pengirimannya (`SE-MTF-...`). Di UI
    `production_workspace#/form-order`, seluruh 8 Form Order tampil berstatus **"Terkirim"** lengkap
    dengan rujukan Stock Entry pengiriman, 100% cocok dengan site lama. Skrip: `pos_sync/fix_material_transfer_and_form_orders.py`.

- **2026-10-08 (migrasi SO + DN Outlet → PT. JURI 1–7 Okt — SELESAI):**
  Lanjutan rantai balik PO outlet: instruksi user "lakukan sales order,
  delivery note; pakai data asli; tiap PO ada koneksi ke SO dan DN juga
  ada koneksi ke SO", lalu "rentang 1–7 Oktober; DN boleh menarik SO yang
  lebih tua (mis. DN 1 Okt atas SO 30 Sep); **Delanggu skip**".
  Sumber tetap site LAMA; PO-nya sudah ada di target.
  - **Scope (jangkar DN):** DN `posting_date` 1–7 Okt + SO-nya (window SO
    1–7 Okt ∪ SO yang ditarik DN, walau SO lebih tua) − Delanggu.
    Hasil: **96 SO + 101 DN**; 23 dokumen di-skip (11 SO tanpa
    `inter_company_order_reference` = bukan intercompany, mis. FRC
    Wahid Hasyim/Jogokariyan/Cibitung dll; 1 DN Delanggu; 11 DN yang
    menarik SO di luar scope). Sisa SO jangkar yang tidak punya DN
    (SLS-051026-021/022/071026-015) tetap ikut karena ada PO-nya.
  - **Prep (idempoten):** 73 customer internal target disiapkan —
    72 `represents_company` + `Allowed To Transact With` JURI diperbaiki,
    1 diaktifkan, 1 customer baru (`RS RIDHOKA SALMA CIKARANG` →
    `CUST-260211`). **Jebakan:** `validate_inter_company_party` untuk SO
    butuh customer internal dengan `represents_company` = **company outlet**
    (PO.company), bukan JURI — salah arah = `Invalid Customer for Inter
    Company Transaction`. Ditambah valuation fallback: 88 item diisi
    `Item.valuation_rate` dari `incoming_rate` baris DN **sumber**
    (nilai akuntansi asli, bukan tebakan) supaya DN bisa submit.
  - **Jebakan eksekusi:** (1) `map_row_common` sempat tidak menulis balik
    `item_code` hasil remap → DN gagal
    `Item Code must be equal to 'BB26009'`; (2) HTTP 500 sporadis site
    (worker 4 → turunkan 2/1, rerun menyelesaikan); (3) idempotensi
    early-return dulu melaporkan "OK" padahal dokumen sisa **draft**
    (POST sukses, submit gagal di tengah) → ditambah **self-heal**
    `_heal_existing` yang men-submit/cancel dokumen existing sesuai
    docstatus sumber (status `DIPERBAIKI-SUBMIT`).
  - **Hasil:** 96 SO Submitted + 101 DN (98 Submitted, 3 Cancelled),
    total Rp 789.845.452 (SO) / Rp 828.760.352 (DN). Link native 100%:
    SO → PO (`inter_company_order_reference`, baris `purchase_order` +
    `purchase_order_item`), DN → SO (`against_sales_order` + `so_detail`),
    gudang `- JURI`, biaya `Main - JURI`.
  - **Verifikasi:** `--verify` 11 cek LOLOS (jumlah/nilai/docstatus/baris/
    link SO & DN; 0 Failed) + cross-check independen tarik-ulang kedua
    site 9/9 LOLOS (0 hilang, 0 beda nilai, 0 beda docstatus, rantai
    DN→SO→PO sampel 0 masalah) + self-test mapper
    `pos_sync/test_migrate_outlet_so_dn.py` 8/8.
  - Laporan: `pos_sync/Laporan_Migrasi_SO_DN_Outlet_ke_JURI.xlsx`
    (Rekap 197 baris, Skipped 23, Validation LOLOS, Failed kosong).

- **2026-10-08 (migrasi PO Outlet → PT. JURI 25 Sep–7 Okt — SELESAI):**
  Atas instruksi user ("tarik purchase order dari outlet ke PT. JUARA ROTI
  INDONESIA, kecualikan company PT. JURI, rentang 25 Sep–7 Okt, sesuaikan
  itemnya, pertahankan ID"). Scope = seluruh PO di site lama dengan
  `supplier = SUP260008 (PT. Juara Roti Indonesia)` dan
  `company != PT. JUARA ROTI INDONESIA`, tanggal 25 Sep–7 Okt:
  **252 PO / 114 company / 3.290 baris / Rp 1.763.981.574**, semua ke
  `ropierpnext.frappe.cloud` dengan ID identik (rename_doc) + docstatus
  persis (142 Submitted, 110 Draft). Script baru
  `pos_sync/migrate_outlet_po_to_juri.py` (`--dump/--refresh/--prep/--migrate/
  --verify/--dry-run/--only/--limit`).
  - **Prep master di site baru** (idempoten): 2 company baru dibuat anak
    OUTLET — `RSI FATIMAH BANYUWANGI` (RFB) & `RS RIDHOKA SALMA CIKARANG`
    (RRSC); 'Allowed To Transact With' supplier JURI dilengkapi +113 company
    (total 123, wajib agar submit lolos `validate_inter_company_party`);
    UOM master dilengkapi (PEL260072 Pack=10, PEL260056/058 Pcs=1).
  - **Jebakan yang ditemukan & ditangani:** (1) *FiscalYearError* — 2 company
    baru belum terdaftar di FY `2026`; FY `Training` punya rentang sama →
    Frappe menolak company yang tumpang tindih, script mendaftarkan ke FY
    yang mencakup tanggal PO saja; (2) **bentrok kode item `BB260059`** —
    di lama = 'Gula Cair (250 g)' (stock_uom g, Botol=250), di baru =
    'Bubuk Hepi Drink Kopi Karamel 30 g' (Sachet) → diremap ke `BB26009`
    ('Gula Cair (250 g)', stock_uom Botol) konsisten dgn `catchup_oct7.py`;
    (3) `Kg`→`kg` + factor diselaraskan ke master baru (mis. BB260041/042/
    043/044/047); (4) akun `Cost of Goods Sold - RFB` →
    `4210.000 - HPP Pembelian - RFB` (RFB baru pakai CoA OUTLET);
    (5) 1 baris `PEL260007` (Balon Kuning, item dihapus di baru atas ACC
    user) pada draft `PO185.051026.001` dilewati & terdokumentasi di sheet
    `Skipped`; (6) `rename_doc` sempat gagal diam pada 3 PO → dibuat
    self-healing repair di `--migrate` (rerun memperbaiki nama fallback →
    ID lama); (7) filter `name in [252]` kena limit request line Frappe →
    verifikasi query per potongan 40.
  - **Verifikasi:** `--verify` 6/6 LOLOS (jumlah, nilai, docstatus, baris,
    gudang, total) + cross-check independen tarik-ulang kedua site LOLOS
    (jumlah/nilai/docstatus/company/baris/duplikat/gudang; 0 hilang, 0 ekstra,
    0 duplikat, 0 sisa Transit). Round-trip nilai: 1.764.139.574 − 158.000
    (baris skip) = 1.763.981.574 persis. Rerun --migrate = 252 SKIP_EXISTS
    (idempoten).
  - **Revisi gudang 2026-10-08 (instruksi user):** gudang PO di target =
    `Stores - <ABBR>` per company, bukan `Goods In Transit - <ABBR>`.
    Diterapkan di `build_payload` (migrasi berikutnya sudah langsung benar)
    + fase baru `--rewarehouse` untuk 252 PO yang sudah masuk: ubah
    `set_warehouse` header + `warehouse` tiap baris in-place via Property
    Setter `allow_on_submit=1` sementara (pola `catchup_oct7.py`), lalu
    dipulihkan ke 0. Hasil 252/252 DIUBAH, 0 gagal; docstatus/total/baris
    tidak berubah; POO85 (Delanggu) kini klop dgn PR `PR-071026-013`
    (sudah `Stores - RPMD`).
  - Catatan: `POO85.021026.001` (Delanggu) sudah ada dari sesi intercompany
    → di-skip otomatis saat migrate, tapi tetap ikut `--rewarehouse`.
    Tidak ada SO/PR ikut terbuat (0 side-effect) — rantai SO-DN-PR bukan
    scope (tetap dikerjakan lane intercompany).
  - Laporan: `pos_sync/Laporan_Migrasi_PO_Outlet_ke_JURI.xlsx`
    (Rekap_PO 252 baris + kolom `gudang_target`/`gudang_cocok`,
    Skipped, Validation LOLOS, Failed kosong).

- **2026-10-07 (audit migrasi WO/SE/MR + telur cair — belum dieksekusi):** Audit
  langsung API lama vs baru (docs/10 §8), menjawab instruksi "tarik WO + telur
  cair + SE/MR, MTFM/MFG dikecualikan, cek PO↔MR":
  - **Telur Cair (BB260055)** = hasil Repack dari Telur Utuh (BB260027):
    56 SE repack di lama, baru 6 masuk (1–6 Okt) → **50 belum** (Agu–Sep + 1 ×
    7 Okt `MAT-STE-2026-09605`); 2 repack lain 7 Okt belum (gula 09527,
    margarin 09624). Repack **tidak punya MR** di lama — MR terkait telur hanya
    Purchase MR + feed. ⚠ BB260055 absen di 8 RECO opening → saldo
    `Gudang Produksi - JURI` minus (−12.490) — kandidat akar valuation error
    BB260055 7 Okt pagi.
  - **WO:** lama 4.127 vs baru 244 → **3.883 belum** (Jul 1.333, Agu 1.102,
    Sep 1.386, Okt 62); 8 stale di baru (04130–34, 04139–41; Completed+handover
    di lama pagi ini).
  - **SE standalone (exclude MTFM/MFG):** belum **911** dari 1.052 (MT 649,
    MI 137, Repack 61, Receipt 60, MFG 4); delta Okt = 35. Semua SE terikat WO
    = persis MTFM+MFG (7.788) → otomatis di luar scope.
  - **MR:** belum **913** dari 998 (baru 85); handover Okt 113 → 28 belum
    (00973–01012, termasuk 7 pagi); non-handover Okt 72 (Purchase 57 + MT 15).
  - **PO↔MR:** lama 238 PO ← 239 MR Purchase; di baru **0 PO punya link MR**;
    155 PO tidak ada di baru, 83 tanpa link. (PO/PR window Okt sudah dimigrasi
    sesi paralel; link MR tetap kosong.) Contoh telur: `PO-010926-010/011/012`
    (← `MAT-MR-2026-00087`) masih 404.
  - Keputusan user diminta (scope WO Jul–Sep, repack historis, MR, PO) —
    laporan lengkap di chat + docs/10 §8.

- **2026-10-07 (tindak lanjut audit — scope dipersempit 1–7 Okt, docs/10 §9):**
  - **Opening telur**: RECO lama `ADJ260930005` (30 Sep, Gudang Produksi)
    memuat BB260055=32.460 @28,80 + BHP260022=53 @59.000 — keduanya absen di
    `RECO-JURI-261006003` site baru → fix via RECO baru (belum eksekusi).
    BHP260024=0; BHP260028 non-stock. WIP tidak punya RECO di lama (0 baris) →
    15 bin WIP negatif karena opening WIP memang tak pernah dibuat.
  - **WO 1–7 Okt**: plan PP261001001/002/005/006 sudah termigrasi penuh;
    **PP261007001 + 62 WO belum** (urutan ikut baris po_items idx 1–62);
    8 stale (04130–34, 04139–41) perlu refresh + handover.
  - **Delta 1–7 Okt (exclude MTFM/MFG)**: MR 123 (51 handover + 57 Purchase +
    8 feed + 5 MT bulk + 2 lain); SE 35 (29 MT-MR + 3 Repack [incl. telur
    09605] + 2 MI + 1 feed 09505). SE MTFM/MFG tidak direplay (62 TFM +
    39 MFG plan 7 Okt dikecualikan) → produced_qty diset db_set terkontrol.
  - **PO↔MR**: 63 PO 1–7 Okt semua ada di baru tapi 57 tanpa link MR
    (field read_only); 57 MR Purchase-nya masuk daftar yang belum dimigrasi.
    Opsi perbaikan link menunggu keputusan user. **Belum ada eksekusi.**

- **2026-10-07 (EKSEKUSI catch-up 1–7 Okt — SELESAI, docs/10 §10):** ACC user
  ("silahkan fix, WIP boleh dengan RECO sendiri, link PO perlu, ACC eksekusi").
  Skrip `pos_sync/catchup_oct7.py`; laporan `Laporan_Catchup_7Okt2026.xlsx`:
  - **7 RECO opening baru** (backdate 30 Sep): telur BB260055 32.460
    (+akar valuation error pagi), WIP 25 item ±Rp22,36 jt (dokumen sendiri),
    Kertas Alas, PEL260087 (GBJ+JKT), FG Cold Storage (kompensasi MFG
    dikecualikan), gula BB26008. WIP negatif 15 → 7 item.
  - **PP261007001 + 62 WO urut baris plan idx 1–62**; 8 stale WO di-refresh;
    paritas 70/70. Nilai pasca-submit via Property Setter sementara.
  - **MR 186** (85 ADA + 101 baru + 00784); 23 skip terdokumentasi (22 handover
    WO September di luar scope + 1 MR cancelled). Status Purchase MR
    direplikasi eksplisit; verifikasi 186/186 match — jebakan: `before_save`
    tidak jalan di jalur update-after-submit (memory tersimpan).
  - **SE 34/35** (skip 09468 non-stock): incl. repack telur 09605, gula 09527,
    margarin 09624, feed 09505, bulk Krim Kopi 09651; link MR+row terpasang;
    hook production_app otomatis `Diminta Gudang` → `Terkirim`.
  - **PO↔MR link 56/57** via child-row PUT + setter sementara (1 skip:
    PO-021026-003 → MR cancelled). Semua setter sementara dipulihkan ke 0.
  - Residu 13 Bin negatif (7 WIP dari replay docs/09 + Bahan Baku mirror
    negatif lama + PG001) — dicatat, bukan bug fase ini.

- **2026-10-07 (audit WIP batch 30 Sep — jawaban "cek pemahaman", docs/10 §11):**
  Baca-saja (`pos_sync/analyze_wip_sep30*.py` → `wip_audit/*.json`), belum eksekusi:
  - **Batch 30 Sep = plan `PP260930001`** → 64 WO `03867–03930`. TFM masuk WIP
    **M30 = 1.967.276,92**; finish same-day 41 WO (**M41 = 723.572,00**);
    finish **H+1 (1 Okt) 23 WO (M23 = 1.243.704,92)** — M41+M23 = M30, 25/25
    item balance. 23 WO H+1 = persis 23 WO yang MR handover-nya gagal (00788–00814).
  - **Site baru**: TFM/MFG 30 Sep tidak direplay (0/41); **23 MFG support 1 Okt
    sudah direplay** (23/23, tanpa link WO) dan konsumsinya **= M23, 25/25 item**;
    23 SE handover MT ada 23/23 (tanpa link MR). Identitas
    `RECO-B + inTFM + outRegen + outSupp == Bin` terverifikasi 25/25 item.
  - **Cek pemahaman user**: (1) benar WO 30 Sep tak masuk; (2) benar sebagian
    WIP tak perlu RECO tambahan — pengurangan H+1 batch 30 Sep SUDAH terjadi
    via 23 MFG support; **jangan kurangi M23 dua kali** (6 item langsung minus
    kalau dipaksa); (3) angka WIP produksi 30 Sep utk kurangi WIP 1 Okt = M23.
  - **7 WIP minus** (BB260002/11/15/16/19/22/29) bukan dari batch 30 Sep
    (M23 ketujuhnya 0) — dari replika MFG `gen_se` × `max(produced_qty,qty)` >
    TFM × qty WO (outRegen > inTFM; mis. BB260011: 3.100+527.000−539.710 =
    −9.610). Opsi koreksi (RECO terpisah 7 item / biarkan / TFM support)
    menunggu keputusan user.

- **2026-10-07 (migrasi PO & PR 1–7 Okt JURI penuh & pajak PPN 11% — SELESAI):** Migrasi seluruh sisa Purchase Order
  (36 PO baru) dan Purchase Receipt (46 PR baru) per 1–7 Oktober 2026 dari ERPNext Lama (`rotiropi.j.frappe.cloud`)
  ke ERPNext Cloud Baru (`ropierpnext.frappe.cloud`):
  - Total PO di Cloud Baru: **97 PO** (63 PO periode 1–7 Okt + 34 PO historis rujukan penerimaan).
  - Total PR di Cloud Baru: **73 PR** (seluruh 73 PR periode 1–7 Okt berstatus Submitted, direlink penuh ke item PO pasangannya).
  - **Sinkronisasi Purchase Taxes & Charges (`pos_sync/sync_purchase_taxes.py`)**:
    Seluruh 25 PO dan 20 PR yang memiliki PPN (11% Exclude `Purchase Tax - JURI` maupun 11% Include `Purchase Tax (Termasuk Pajak) - JURI`)
    telah disinkronkan child table `taxes`, akun `1152.001 - PPN Masukan - JURI`, dan `total_taxes_and_charges`.
    Seluruh selisih pajak 11% hilang total (`Diff: 0.0` pada 97/97 PO dan 73/73 PR).
  - Perbaikan otomatis: `item_defaults` akun persediaan JURI untuk item `BB260057-60` dilengkapi (`1143.000 - Raw Material - JURI`)
    sehingga seluruh submit PR 100% mulus (termasuk `PR-061026-024`).
  - Verifikasi: 97/97 PO terdaftar, 73/73 PR terdaftar & submitted, 0 gagal, 0 selisih. Laporan diperbarui di
    `pos_sync/Laporan_Migrasi_PO_PR_1_7_Okt2026.xlsx` (Validation: LOLOS).

- **2026-10-07 (migrasi master Asset — SELESAI):** Migrasi seluruh 42 dokumen master Asset dari
  ERPNext Lama (`rotiropi.j.frappe.cloud`) ke ERPNext Cloud Baru (`ropierpnext.frappe.cloud`):
  - Setup pendukung di Cloud Baru: pembuatan `Location` (`Head Office JURI`), `Employee` (`HR-EMP-00006` Zunas),
    dan 3 `Custom Field` Asset (`custom_for_device`, `custom_serial_no`, `custom_user`).
  - Eksekusi via `pos_sync/migrate_assets.py`: 42 Asset (`ACC-ASS-2026-00001` s/d `00042`) berhasil dibuat
    dengan ID bawaan identik, serial number, user, dan akun penyusutan lengkap.
  - Verifikasi: 42/42 LOLOS (100% klop, 0 selisih).
  - Item non-aktif tetap dikecualikan dari migrasi sesuai arahan user.

- **2026-10-07 (migrasi master Item & Supplier pelengkap — SELESAI):** Audit perbandingan master Item
  (377 lama vs 325 baru) dan Supplier (253 lama vs 251 baru) berbasis semantik nama (`item_name` & `supplier_name`)
  dan kode di ERPNext Lama (`rotiropi.j.frappe.cloud`) vs Cloud Baru (`ropierpnext.frappe.cloud`):
  - **Supplier**:
    - 251 supplier lama cocok 100% dengan target (target menggunakan nama perusahaan sebagai ID).
    - 2 supplier baru dibuat per 7 Okt di sistem lama: `Shopee - Toko ATK 123` (`SUP260252`) dan
      `Shopee - Barre Official` (`SUP260253`) dimigrasikan ke Cloud Baru. Total Supplier kini **251 unik / 100% klop**.
  - **Item**:
    - Ditemukan 5 item dengan kode berbeda namun nama identik (sudah ada di target, dicegah duplikasi):
      `ATK260054` -> `PAKET26-002`, `GM002` -> `GM005`, `ITEM00001` -> `PAKET26-004`, `ITEM00002`/`PAKET26-001` -> `PAKET26-003`.
    - Ditemukan 17 item ber-kode identik dengan sedikit penyesuaian nama di target.
    - 3 item operasional aktif yang belum terdaftar di Cloud Baru berhasil dimigrasikan (`pos_sync/migrate_missing_items.py`):
      `PEL260002` (Aluminium Foil), `BHP260014` (Hair Nett), `ATK260048` (Stiker Label 103).
      (Item balon kuning/putih/pink dihapus kembali sesuai instruksi user).
    - 63 item lama yang tidak dimigrasikan terklasifikasi bersih: 3 balon (`PEL260007/96/98`) +
      17 item non-aktif/deactivated (dough lama `PJ260001-007`, paket hemat lama, item tes) +
      39 varian pakaian pabrik (di Cloud Baru sudah digantikan master terpadu `SG26*` / `PEL260019/68/89`) +
      4 padanan langsung (`BHP260023` Lakban, `BB260004` Air Galon).

- **2026-10-07 (intercompany PO-SO-DN-PR Delanggu 1–7 Okt — SELESAI):** Pembentukan & sinkronisasi rantai
  transaksi intercompany lengkap antara `RS PKU MUHAMMADIYAH DELANGGU` dan `PT. JUARA ROTI INDONESIA`
  pada ERPNext Lama (`rotiropi.j.frappe.cloud`) dan ERPNext Cloud Baru (`ropierpnext.frappe.cloud`):
  - Penelusuran rantai transaksi 1–7 Oktober 2026:
    - Purchase Order: `POO85.021026.001` (2026-10-02, Rp 1.438.500, Delanggu).
    - Sales Order: `SLS-051026-006` (2026-10-02, Rp 1.438.500, JURI, ref PO: `POO85.021026.001`).
    - Delivery Note: `DN-051026-008` (2026-10-05, Rp 1.438.500, JURI, ref SO: `SLS-051026-006`).
    - Purchase Receipt: Sebelumnya belum dibuat di ERPNext Lama (status PO masih menggantung `To Receive and Bill`),
      namun bukti penerimaan fisik resmi sudah tercatat di eResto (`PCO85.051026.001` per 05-10-2026).
  - Eksekusi pembuatan Purchase Receipt di ERPNext Lama:
    - Dokumen `PR-071026-013` dibuat via `pos_next.api.purchase_receipts` terhubung ke `DN-051026-008` dan `POO85.021026.001`,
      gudang `Stores - RPMD`, posting_date 2026-10-05 jam 10:55:25, disubmit (`To Bill`). Status PO terupdate `To Bill` (100% received).
  - Replikasi & sinkronisasi rantai lengkap ke ERPNext Cloud Baru (`pos_sync/sync_delanggu_intercompany.py`):
    - Konfigurasi `Supplier PT. JUARA ROTI INDONESIA` di Cloud Baru diaktifkan sebagai internal supplier (`represents_company: PT. JUARA ROTI INDONESIA`).
    - PO `POO85.021026.001` disubmit (Rp 1.438.500).
    - SO `SLS-051026-006` disubmit dengan `inter_company_order_reference: POO85.021026.001`.
    - DN `DN-051026-008` disubmit dari `Gudang Barang Jadi - JURI` against SO (per_delivered 100%).
    - PR `PR-071026-013` disubmit ke `Stores - RPMD` dengan `inter_company_reference: DN-051026-008` & `purchase_order: POO85.021026.001` (per_received 100%).
    - Saldo fisik di `Stores - RPMD` bertambah sesuai 5 item masuk (Dough Coklat 25, Keju 15, Tiramisu 1, Margarine 1, Sedotan 3). Seluruh 4 dokumen berstatus Submitted (`To Bill`).

- **2026-10-07 (migrasi & rekonsiliasi PO & PR 1–7 Okt JURI — SELESAI):** Rekonsiliasi data
  ERPNext lama vs baru untuk `PT. JUARA ROTI INDONESIA` (periode 1–7 Okt 2026) dan
  migrasi seluruh sisa Purchase Order & Purchase Receipt ke Cloud (`ropierpnext.frappe.cloud`):
  - Penarikan ERPNext lama: 53 PO (6 per 1 Okt, 47 per 2 Okt; 26 Submitted, 26 Draft, 1 Cancelled)
    + 27 PR (22 per 1 Okt, 5 per 2 Okt; seluruhnya Submitted).
  - Pemeriksaan Cloud awal: baru memuat 23 PO (1 Okt) dan 22 PR (1 Okt). Sisa 48 PO (47 PO 2 Okt +
    1 PO `PO-300926-003` rujukan `PR-021026-004`) dan 5 PR belum termigrasi.
  - Eksekusi via `pos_sync/migrate_po_pr_1_7_okt.py`:
    - 48 PO diinjeksi dengan ID bawaan identik via `frappe.client.rename_doc`, supplier dimapping,
      gudang `- JURI`, marker idempotensi `ERESTO <name>`, docstatus persis (Submitted / Draft /
      Cancelled untuk `PO-021026-003`). Total PO Cloud kini **71 PO** (53 PO 1–7 Okt + 18 PO historis Sep).
    - 5 PR diinjeksi dengan ID bawaan identik (`PR-021026-002/004/005/006/007`), disubmit,
      direlink ke item PO pasangannya di Cloud (status PO terupdate `To Bill` & per_received bertambah).
      Total PR Cloud kini **27 PR**.
  - Verifikasi: 0 duplikat (71 PO unik, 27 PR unik), 100% ID identik, 100% docstatus klop,
    seluruh 27 PR relink OK. Laporan audit: `pos_sync/Laporan_Migrasi_PO_PR_1_7_Okt2026.xlsx`
    (sheet `Rekap_PO`, `Rekap_PR`, `Validation` LOLOS).

- **2026-10-07 (migrasi print format — SELESAI):** Header global + konten per
  format dipasang di `ropierpnext.frappe.cloud` (+ lokal) — `docs/11`
  (status akhir), `pos_sync/migrate_print_formats.py` + `pf_src/letterhead.html`.
  - Keputusan user: **hanya 10 format yang jadi default di site lama** dibawa;
    POS Next Receipt / EOD tidak disentuh (versi app lebih baru, aman).
  - **Kunci desain:** dokumen existing mem-pin `letter_head = "Company
    Letterhead - Grey"` eksplisit (PO/PR/SE/MR/POS Invoice; 38k+ lokal,
    ratusan cloud) → bukan bikin LH baru, tapi **konten LH itu yang diganti**
    jadi header global (logo company + judul + meta kondisional per DocType,
    fallback generik). Header langsung tampil di semua dokumen, nol update
    dokumen, nama historis aman. `is_default` tetap; LH lain di-unset.
  - 7 format di-split (PO/PR/PI/SO/DN/MR/STE: blok header + 15 rule CSS-nya
    dibuang, body memanggil `{{ letter_head }}`; sisa body byte-identik
    render lama), 3 verbatim (Pick List — header per halaman; Batch QR label;
    POS Invoice struk). 10 setter `default_print_format` cloud dipasang.
  - Verifikasi: render parity **10/10 OK** lokal & cloud; PDF dokumen nyata
    **6/6 OK** lokal, **5/5 OK** cloud (PI/SO/DN/Pick List/Batch skip: belum
    ada dokumen). Laporan `pos_sync/pf_reports/Migrasi_Print_Format_*.xlsx`.
    Rollback: `--revert --stage cloud`.
  - Jebakan dev lokal dicatat di docs/11 §5 (host_name + /etc/hosts container
    untuk wkhtmltopdf; aset hanya via container frontend).

- **2026-10-07 (rencana migrasi print format):** Rencana **header global + konten per
  format** untuk print format site lama → baru — `docs/11-migrasi-print-format.md`
  (belum dieksekusi; menunggu 6 keputusan user).
  - Dump: site lama 65 format (**21 custom**, 10 jadi default via Property Setter);
    site baru hanya 3 custom — POS Next Receipt/EOD versi app **lebih baru**, jangan
    ditimpa; default lain masih placeholder `...with Item Image`.
  - Akar masalah: semua format A4 lama menggabung blok "HEADER + TITLE + META" +
    CSS-nya di tiap file (diduplikasi dengan prefix beda-beda).
  - Mekanik terbukti (uji live + bedah source Frappe v16): Letter Head dirender sebagai
    Jinja dengan `doc.as_dict()` + `frappe.*` — letter head lama `Company Testing`
    (berisi `frappe.get_doc` + percabangan) sukses render; format custom hanya
    menampilkan LH bila memanggil `{{ letter_head }}`.
  - Rencana: 1 Letter Head global "Header Global Ropi" (logo+company+judul+meta
    kondisional per DocType + fallback generik) + 12 body format; Pick List / Batch QR
    / POS Invoice tetap self-contained; script `pos_sync/migrate_print_formats.py`
    (`--dump|--build|--push|--verify|--revert`), staging lokal dulu, PDF uji + laporan
    `Migrasi_Print_Format.xlsx`.

- **2026-10-07 (audit migrasi WO lanjutan):** Audit kebutuhan migrasi WO
  JURI terhadap site lama (masih produksi) + bedah source
  production_app/warehouse_app → rencana di
  `docs/10-migrasi-wo-lanjutan.md`:
  - Temuan: replay 244 WO OK, tapi serah terima baru 85/217 — 125 MR milik
    WO September (di luar window) + 7 MR pagi ini (dibuat 08:17-08:21,
    setelah dump); 4 MR bulk Krim Kopi + 7 MR feed Bahan Baku + 1 feed
    hari ini tidak dimigrasi (SE-nya sudah ada tanpa link); 7 WO selesai
    pagi ini + 04130 + PP261007001/62 WO hari ini belum ada di baru.
  - Akar error "lot tersedia" di screenshot: Krim Kopi tidak pernah pakai
    serah terima per-WO di site lama (bulk MR harian) + lot board = stok
    live (drop saat stok ≤0) → klik per-WO gagal juga di site lama.
  - Rencana: catch-up batch + sinkron delta harian idempoten (PP/WO/MR/SE),
    ID lama dipertahankan (rename_doc), link `material_request` +
    `material_request_item` wajib saat post SE (read_only → tak bisa
    dipatch setelah submit). Verifikasi via handover_board parity + Bin.
  - Menunggu keputusan user: scope WO September, SE support tanpa link,
    rutin delta harian, dan SOP Krim Kopi (bulk vs per-WO).

- **2026-10-07 (FIX guard multi-level BOM — DI-COMMIT+PUSH; E2E browser LULUS):**
  Lanjutan diagnosis pagi ini; koreksi akar: WO `WO-RPMD-261007001/002`
  dibuat oleh **pos_next `start_production`** (SPA kasir "Mulai Produksi"),
  bukan wizard Tambah Plan — bukti: `posa_pos_profile/posa_operator/
  posa_recipe` + `skip_transfer=1` terisi di dokumen; Version doc menunjukkan
  draft→submit satu transaksi (pola service). Jalur pos_next tidak pernah
  menyetel `use_multi_level_bom` → default ERPNext 1 → 18 baris
  `required_items` ledakan resep dough.
  - **Fix (source `production_app`)**: doc_events `Work Order.before_validate`
    → `enforce_single_level_bom_for_outlet`; item grup `Produk Jadi Outlet`
    (+ sub-grup, nested set) dipaksa mlb=0 dan `required_items` di-rebuild
    level tunggal. `before_validate` WAJIB — Production Plan native
    meng-insert WO dengan `ignore_validate=1` (hanya before_validate tetap
    jalan); item pabrik tidak disentuh.
  - **Bukti**: suite baru `tests/test_outlet_single_level_bom.py` 4/4 OK;
    live 8081 item asli PJO2601 + BOM berjenjang (rollback, residu 0) →
    `mlb=0, required_items=[PJ260013 ×12], se_manufacture consume=[PJ260013],
    WO Completed`; regresi warehouse_defaults 17/17; kegagalan modul lain
    terbukti pre-existing via A/B hooks HEAD. **E2E browser built-in (7 Okt)
    alur kasir penuh LULUS**: buka shift → Produksi → qty 3 → Mulai →
    `WO-RPMD-261007001` mlb=0 + 2 baris (bukan 18; A/B data membuktikan
    explosion = 18 termasuk BB260055) → Selesai → `SE-MFG-261007001` hanya
    konsumsi dough 3.0 + krim 0.12 → WO Completed, BB260055 tak tersentuh.
    (Finish pertama tertahan guard negatif-stok pre-existing situs dev
    PJO2601 −48 sisa migrasi, bukan bug guard; pulih `allow_negative_stock=0`
    terverifikasi.)
  - **Status: 2 WO cloud masih utuh Not Started.** Menunggu keputusan user:
    deploy app ke cloud → cancel+hapus 2 WO → kasir ulang lewat SPA.

- **2026-10-07 (diagnosis error production):** Error *"Valuation Rate for
  Item BB260055 is required … Stock Entry SE-MFG-261007001"* saat kasir
  (`kasir1_dlg@mail.com`, RS PKU Delanggu) menekan Selesai di production_app.
  - Akar masalah (diagnosis awal; dikoreksi di entri di atas): WO baru
    `WO-RPMD-261007001/002` terisi `use_multi_level_bom = 1` (default
    ERPNext; field tidak allow_on_submit). SE Manufacture pun meledakkan
    resep dough (`BOM-PJ260013-001`: 11 bahan termasuk Telur Cair 225 g) dan
    mencoba mengonsumsinya dari `Stores - RPMD` — Telur Cair di gudang itu
    0 qty/0 nilai dan master valuation_rate = 0 → throw. SE create+submit
    atomik di app → rollback penuh, tidak ada draft yatim.
  - Migrasi kemarin aman karena `inject_delanggu_work_order_production.py`
    set `use_multi_level_bom: 0` eksplisit. Prompt handoff:
    `PROMPT_FIX_WO_MULTIBOM.md`.
- **2026-10-07:** Penghapusan transaksi `PINV-RPMD-261007002` di
  `ropierpnext.frappe.cloud` atas instruksi user (POS Invoice Rp 10.000,
  BC002, kasir1_dlg@mail.com, 7 Okt 07:46, belum terkonsolidasi closing):
  - Alur: cancel → hapus POS Print Log `ao2a9ifeit` → 14 GL Entry dipurge
    via loop API. Payment Ledger Entry (4 baris) tidak bisa lewat API
    (DocPerm read-only → 403), jadi rute bersih: `delete_linked_ledger_entries
    = 1` sementara di Accounts Settings → DELETE invoice (on_trash membersihkan
    PLE/SLE/GL atomik) → setting dipulihkan ke 0.
  - Verifikasi: GET invoice 404, GL/SLE/PLE = 0, Bin `Stores - RPMD` 4 item
    (BB260032/BB260039/PEL260071/PEL260085) tidak berubah; tercatat di
    Deleted Document `6uobf3f55q`. Prosedur disimpan ke memory.

- **2026-10-06 (sesi 6 lanjutan — replay WO penuh):** Replay 244 WO pabrik JURI 1–6 Okt 2026 ke `ropierpnext.frappe.cloud` menurut alur riil production_app + warehouse_app (`pos_sync/migrate_wo_full_okt.py`, docs/09-migrasi-wo-juri-replay.md):
  - **Pelajari alur app dulu** (sumber: `/Users/rotiropi/erpnext-new/apps/production_app` & `warehouse_app`): plan → WO → tahap (Persiapan/Material/Pre-Packing/Post-Packing/Finish) → serah terima MR+SE; `derive_stage` = selesai saat produced+loss ≥ qty (turunan); box 1–3 dipensiunkan (FU96) → tidak ditulis, diarsipkan di Excel.
  - **4 Production Plan** (`PP261001001/002/005/006`, ID lama) + **244 WO** dari plan (ID lama, custom field lengkap via merge Custom Field ke meta — jebakan baru: `fetch_meta` tidak memuat Custom Field sehingga `custom_*` terbuang diam-diam). 221 Completed + 23 In Process (6 Okt berjalan) persis sumber; Σ produced 81.620 = 81.620.
  - **85 Material Request** serah terima (ID lama) + **85 SE** serah terima; hook production_app otomatis mengisi `Diminta Gudang` → `Terkirim` (terbukti live, tanpa set manual).
  - **629 SE** direplay kronologis dengan tanggal historis (244 TFM + 244 Manufacture + 122 MT + 8 MI + 6 Repack + 5 Receipt); 2 SE lama tidak direplay (1 batal + 1 semua item non-stock) — tercatat.
  - **Verifikasi 244/244 LOLOS, 0 selisih** (`Laporan_Migrasi_WO_1_6_Okt2026.xlsx`: Hasil_WO, Arsip_Box_Lama, Production_Plan, SE_Mapping, MR_Mapping). Spot-check Bin: selisih residual berasal dari opening (opname eResto) + PR 2–6 Okt yang belum dimigrasi (lane pembelian), bukan bug replay.
  - Jebakan tercatat di docs/09: UOM SE lama pakai konversi (`qty`≠stock), `Kg`→`kg`, `Gudang RnD`→`Gudang R&D`, item non-stock beda antar-site, valuation rate dari dokumen lama saat stok sumber kosong.

- **2026-10-06 (sesi 5 lanjutan 21):** Injeksi 3 Transaksi Terakhir Delanggu 6 Oktober 2026 ke Open Shift (Shift 2):
  - Pemeriksaan menyeluruh 11 Sales Invoice di ERPNext lama (`https://rotiropi.j.frappe.cloud`):
    - 8 invoice Shift 1 (09:31–10:37, omzet Rp 171.000) sudah terinjeksi di `POPEN-RPMD-261006006`.
    - 3 invoice Shift 2 (15:15–17:11, omzet Rp 90.000) adalah transaksi kasir sore hari berjalan:
      1. `SINV-RPMD26591` (15:15:45, Rp 20.000: 2x RP002 Ropi Coklat)
      2. `SINV-RPMD26592` (16:51:39, Rp 30.000: 1x RP003 Ropi Keju, 2x RP002 Ropi Coklat)
      3. `SINV-RPMD26593` (17:11:54, Rp 40.000: 2x RP003 Ropi Keju, 1x RP002 Ropi Coklat, 1x RP001 Ropi Butter)
  - Penyelarasan & Injeksi ke Shift yang masih Open (`POPEN-RPMD-261006008`):
    - Membersihkan dokumen invoice uji coba lokal `PINV-RPMD-261006133` (beserta print log `7oh1e15npe`) agar tidak terjadi pencatatan ganda atas penjualan RP002.
    - Mengaktifkan `allow_change_posting_date = 1` pada POS Settings profile `SHIFT 2- RS PKU MUHAMMADIYAH DELANGGU`.
    - Menginjeksi ke-3 transaksi sore via `submit_backdate_invoice` di bawah shift `POPEN-RPMD-261006008`:
      - `PINV-RPMD-261006135` (`SINV-RPMD26591`, Rp 20.000, Submitted, RP002 Ropi Coklat)
      - `PINV-RPMD-261006136` (`SINV-RPMD26592`, Rp 30.000, Submitted, RP003 Ropi Keju + RP002 Ropi Coklat)
      - `PINV-RPMD-261006137` (`SINV-RPMD26593`, Rp 40.000, Submitted, RP003 Ropi Keju + RP002 Ropi Coklat + RP001 Ropi Butter)
    - Memperbarui label item_name pada invoice 135, 136, 137 agar persis mengacu ke master (RP001 = Ropi Butter, RP002 = Ropi Coklat, RP003 = Ropi Keju).
  - Hasil Audit & Verifikasi:
    - Status Shift 2: `POPEN-RPMD-261006008` tetap **Open** (`status: Open`, `docstatus: 1`).
    - Total transaksi 6 Oktober di New ERP: **11 / 11 invoice (100% klop dengan Old ERP, 0 selisih, 0 duplikat)**.
    - Total omzet 6 Oktober di New ERP: **Rp 261.000,00** (Shift 1 Rp 171.000 + Shift 2 Rp 90.000).
    - Saldo fisik produk jadi matang di `Stores - RPMD`:
      - `PJO2601` (Ropi Coklat Matang): **+2.0 Pcs**
      - `PJO2602` (Ropi Keju Matang): **+18.0 Pcs**
      - `PJO2603` (Ropi Butter Matang): **+6.0 Pcs**
      - `PJO2604` (Gempi Matang): **+3.0 Pcs**
      - `PJO2605` (Croissant Matang): **+7.0 Pcs**
      *(Catatan master: Varian Ropi aktif hanya ada 3: Keju, Coklat, Butter. Ropi Moka dan Ropi Durian TIDAK ADA).*
    - Laporan Excel detail tersimpan di `pos_sync/Injeksi_Delanggu_6_Okt_Old_ERP.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 20):** Penghapusan Transaksi PINV-RPMD-261006132 & PINV-RPMD-261006134:
  - Merespons instruksi user untuk menghapus kedua dokumen transaksi tersebut tanpa menginput data baru.
  - Menghapus dokumen penaut `POS Print Log` terkait: `5oaauelc0c` (link ke 132) dan `ebttka6j15` (link ke 134).
  - Mengaktifkan sementara `delete_linked_ledger_entries = 1` pada `Accounts Settings`.
  - Menghapus permanen dokumen `PINV-RPMD-261006132` dan `PINV-RPMD-261006134` dari Cloud (status terverifikasi HTTP 404 Not Found).
  - Memulihkan kembali `delete_linked_ledger_entries = 0`.
  - Sistem dalam status standby (pause/tidak ada input transaksi baru).

- **2026-10-06 (sesi 5 lanjutan 19):** Inkorporasi Uang Bayar (Paid Amount) & Kembalian (Change Amount) Delanggu 1–6 Oktober 2026 dari ERPNext Lama:
  - Analisis mendalam data kasir di ERPNext lama (`https://rotiropi.j.frappe.cloud`):
    - Ditemukan total 114 Sales Invoice Delanggu (periode 1–6 Oktober 2026).
    - Sebanyak **40 transaksi kasir** memiliki uang bayar lebih dan uang kembalian (`change_amount > 0`), mulai dari kembalian Rp 1.000 s/d Rp 90.000 dengan total kembalian Rp 1.104.000,00 (seluruhnya transaksi Cash).
    - Pada migrasi awal dari eResto (1–5 Okt) dan skrip injeksi awal (6 Okt), nominal uang bayar kasir sempat diatur sama dengan grand total (`change_amount = 0`), sehingga nominal kembalian riil belum tercatat di POS Invoice.
  - Implementasi & Pembaruan di ERPNext Cloud (`ropierpnext.frappe.cloud`):
    - Memasang `Property Setter` (`allow_on_submit = 1`) pada field `paid_amount`, `base_paid_amount`, `change_amount`, `base_change_amount` di `POS Invoice`, serta `amount` dan `base_amount` pada child table `Sales Invoice Payment`.
    - Menghubungkan secara deterministik ke-40 invoice berkembalian dari Old ERP ke invoice pasangannya di New ERP (termasuk 8 invoice POS Package teralokasi).
    - Memperbarui nominal uang bayar kasir (`paid_amount`), child payment row `amount`, dan nominal kembalian (`change_amount` & `base_change_amount`) pada seluruh 40 POS Invoice di Cloud.
    - Menyelaraskan transaksi kasir langsung 6 Oktober (`PINV-RPMD-261006132` bayar 100k kembalian 80k, serta `PINV-RPMD-261006133` sinkron dengan `SINV-RPMD26591`).
  - Hasil Audit & Verifikasi:
    - Total transaksi berkembalian di New ERP: **41 transaksi** (40 transaksi historis 1–6 Okt + 1 transaksi baru hari berjalan kasir), total nominal kembalian **Rp 1.184.000,00**.
    - Rekonsiliasi Matematika: `paid_amount - grand_total == change_amount` lolos 100% (0 error).
    - Rekonsiliasi Child Table `payments`: 100% konsisten antara child row Cash dengan `paid_amount` (0 mismatch).
    - Integritas Kas & Closing Shift: Formula net cash expected (`sum(payments) - sum(change_amount)`) tetap seimbang sempurna dengan Grand Total omzet riil.
    - Laporan Excel detail tersimpan di `pos_sync/Update_Kembalian_Delanggu_Report.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 18):** Penggantian Data Delanggu 6 Oktober 2026 dari ERPNext Lama & Sinkronisasi Produksi:
  - Konfirmasi operasional: Per 6 Oktober 2026 outlet Delanggu sudah tidak lagi menggunakan eResto dan beralih langsung ke ERPNext.
  - Penarikan & Injeksi Penjualan 6 Oktober 2026 dari Old ERPNext (`https://rotiropi.j.frappe.cloud`):
    - Ditemukan 8 Sales Invoice kasir (`SINV-RPMD26583` s/d `26590`, total omzet Rp 171.000,00: Cash Rp 151.000, QRIS Rp 20.000).
    - Seluruh 8 transaksi diinjeksi ke New ERPNext Cloud (`PINV-RPMD-261006124` s/d `131`) di bawah shift `POPEN-RPMD-261006006`.
    - Transaksi paket `SINV-RPMD26589` (Hemat 3 New) otomatis dikuotasikan dengan alokasi proporsional resmi (Parent Rp 0, `CP001` Rp 14.400, `RP003` Rp 9.600).
    - Shift 6 Oktober dibuka kembali sesuai permintaan user: `POPEN-RPMD-261006006` berstatus **Open** (siap menerima transaksi tambahan kasir hari ini), dan dokumen closing sementara telah dihapus bersih.
  - Sinkronisasi Produksi Work Order 6 Oktober 2026:
    - Entri masak `MAT-STE-2026-09392` (Ropi Keju 12 Pcs @ 09:44:13) dimigrasikan via alur resmi Work Order `WO-RPMD-261006023` (Completed) -> `SE-MFG-261006043` -> `PPLOG-2610-00041`.
    - Saldo Roti Keju Matang `PJO2602` di `Stores - RPMD` langsung surplus positif (**+11.0 Pcs**).
  - Hasil audit menyeluruh:
    - Total POS Invoice New ERPNext: **114 / 114 Submitted** (`docstatus: 1`), 0 Cancelled, 0 Duplikat.
    - Total Work Order: **21 / 21 Completed**, 21 Stock Entry Manufacture Submitted.
    - Seluruh saldo Bin roti matang (`PJO2601` s/d `2605`), bahan bubuk, dough, dan kemasan di `Stores - RPMD` bersaldo positif.
    - Laporan Excel detail tersimpan di `pos_sync/Injeksi_Delanggu_6_Okt_Old_ERP.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 17):** Penarikan eResto & Rekonsiliasi 1-to-1 Delanggu (1 s/d 6 Oktober 2026):
  - Penarikan langsung seluruh order eResto API v3 untuk outlet `RS PKU MUHAMMADIYAH DELANGGU` (`bb271ab7-b25c-4b08-b05a-b0f8980bff34`):
    - Total order terdeteksi: 107 order.
    - Order valid berkuitansi: 106 order.
    - Order void / tanpa pembayaran: 1 order (`ORO85.061026.000001` per 6 Okt jam 11:53, void 2 item, total Rp 0 -> otomatis dilewati sesuai aturan audit).
  - Pencocokan 1-to-1 dengan ERPNext Cloud (`ropierpnext.frappe.cloud`):
    - 106 / 106 order valid (100.0%) sudah tercatat sempurna di ERPNext sebagai POS Invoice submitted.
    - 0 order tertinggal, 0 selisih nominal (omzet Rp 2.114.000,00 persis sama).
    - 0 duplikasi transaksi (idempotensi terjaga via remarks `ERESTO <order_no>`).
  - Laporan rekonsiliasi detail tersimpan di `pos_sync/Rekonsiliasi_eResto_ERPNext_Delanggu_1_sd_6_Okt.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 16):** Re-injeksi 17 POS Invoice Paket Delanggu dengan Alokasi Proporsional (POS Package Allocation ON):
  - Konfirmasi toggle `enable_pos_package_allocation = 1` aktif di `POS Next Global Settings` Frappe Cloud (`ropierpnext.frappe.cloud`).
  - Pembersihan 17 POS Invoice paket legacy (yang sebelumnya hanya memuat kode parent paket tanpa rincian komponen).
  - Alur eksekusi per shift historis (1, 2, 3, 5 Oktober 2026):
    - Pembukaan kembali shift (`reopen_shift`) dan penghapusan bersih dokumen closing shift lama.
    - Pembatalan (`cancel`) dan penghapusan permanen 17 POS Invoice paket lama dengan `delete_linked_ledger_entries = 1`.
    - Kuotasi dinamis via `pos_next.api.packages.quote_package` untuk 17 transaksi sesuai pilihan varian roti eResto (`promotion_bonuses`):
      - Baris Parent paket (`pos_package_role: "Package"`, rate Rp 0, qty 1, snapshot JSON kuotasi server).
      - Baris Komponen (`pos_package_role: "Package Item"`, rate alokasi proporsional berdasarkan selling price list).
      - Penguraian Product Bundle native komponen (`RP00*`, `CP001`, `JT001`, `BC002`, `CK001`) memotong stok fisik matang (`PJO*`), bubuk minuman, cup gelas, dan kemasan secara otomatis.
    - Injeksi & submit ulang 17 invoice via `pos_next.api.backdate_invoices.submit_backdate_invoice` (`PINV-RPMD-261006107` s/d `PINV-RPMD-261006123`).
    - Penutupan shift kembali via `get_closing_shift_data` dan submit 4 POS Closing Shift resmi (`POCLO-RPMD-261006005` s/d `008`).
  - Hasil verifikasi integritas sistem (100% LOLOS):
    - Total transaksi POS Invoice: 106 / 106 Submitted (`docstatus: 1`), 0 Cancelled, 0 Hilang.
    - Total penjualan shift konsisten sempurna dengan eResto:
      - 1 Okt: Rp 442.000,00 | 2 Okt: Rp 508.000,00 | 3 Okt: Rp 719.000,00 | 5 Okt: Rp 445.000,00 (Total: Rp 2.114.000,00).
    - Seluruh saldo Bin roti matang (`PJO2601` s/d `2605`), bahan baku bubuk, dan dough di `Stores - RPMD` tetap positif dan balance.
    - Laporan Excel detail tersimpan di `pos_sync/Reinject_POS_Package_Report.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 15):** Pembersihan Master Item Duplikat Paket Goodiebag 20 & Persiapan Update POS Package:
  - Penghapusan master item duplikat `PAKET010926-006` (Paket Goodiebag 20 Roti) di ERPNext Cloud `ropierpnext.frappe.cloud` (0 transaksi, 0 POS Invoice, 0 POS Package, terbukti duplikat dari `PAKET26-002` Paket Box Ropi Isi 20 / `PR00038`).
  - Pembersihan baris 33 duplikat di workbench mapping `experiments/Template_Mapping_SKU.xlsx` sehingga referensi `PR00038` bersih menunjuk `PAKET26-002`.
  - Analisis update PR #5 repo `Muhayustrid/POSNext` (alokasi proporsional harga paket via toggle `enable_pos_package_allocation`, carrier qty-1, validasi nama kembar, logo struk, dan print EOD).
  - Kepastian teknis: POS Package tidak perlu dihapus sebelum update production; migrasi aman dan revisi paket bisa dilakukan langsung setelah update.

- **2026-10-06 (sesi 5 lanjutan 14):** Revisi Stock Reconciliation Opening Stock RS PKU MUHAMMADIYAH DELANGGU:
  - Pembatalan & penghapusan bersih dokumen synthetic opening lama `RECO-RPMD-261005001`.
  - Injeksi dokumen Stock Reconciliation opening baru `RECO-RPMD-261006001` per 30 September 2026 jam 18:00:00 berdasarkan 36 baris fisik Stock Opname eResto:
    - 2 item tidak aktif dilewati (`BB0106` Olesan Pineapple, `BB0108` Olesan Strawberry).
    - 7 item dengan saldo 0 dilewati (`BB0311`, `BB0310`, `RR0002`, `RR0001`, `BB0308`, `BB0107`, `BB0145`).
    - 27 item aktif dipetakan dengan konversi UOM dan valuation rate presisi:
      - Roti matang: Roti Croissant (`PJO2605`: 2 Pcs @ Rp 7.833,00), Roti Gempi (`PJO2604`: 2 Pcs @ Rp 5.690,68), Ropi Keju (`PJO2602`: 9 Pcs @ Rp 3.850,00).
      - Dough (Pack -> Pcs): Butter (17 Pack = 204 Pcs), Coklat (7 Pack = 84 Pcs), Croissant (27 Pack = 162 Pcs), Gempi (18 Pack = 54 Pcs), Keju (7 Pack = 84 Pcs).
      - Bubuk & curah (Pack/kg -> g): Jasmine Green Tea (1.095 g), Coffee Classic (252 g), Coffee Latte (2.735 g), Dark Cocoa Drink (1.350 g), Olesan Choco Crunchy (1.520 g), Olesan Dark Choco (2.060 g), Olesan Tiramisu (230 g).
      - Kemasan & pelengkap: Paper Bag (`PEL260076`: 510 Pcs), Box Gempi (`PEL260069`: 71 Pcs), Gelas 14 Oz (`PEL260070`: 943 Pcs), Gelas 9 Oz (`PEL260071`: 380 Pcs), Goodie Bag (`PEL260072`: 73 Pcs), Kardus 20 Roti (`PEL260074`: 28 Pcs), Plastik Alas Gempi (`PEL260077`: 38 Pcs), Gula Stik (`BB260039`: 389 Pcs), Gula Cair Sachet (`BB260038`: 84 Sachet), Kopi Hitam @6gr (`BB260061`: 40 Pcs), Krim Kopi (`PJ260016`: 16 Pcs), Air Mineral (`PJ260009`: 6 Botol).
    - Total nilai persediaan fisik pembuka: Rp 6.119.343,23.
    - Dilengkapi populasi dual-field (`warehouse_app` standar + custom UOM/Rate).
  - Hasil verifikasi: Dokumen tersubmit `RECO-RPMD-261006001` (docstatus: 1), 27 SLE aktif, seluruh Bin di `Stores - RPMD` (matang, dough, kemasan) bernilai positif dan balance dengan downstream transaksi (106 POS Invoice + 20 Work Order). Journal Entry `ACC-JV-2026-00001` tetap 100% utuh. Laporan Excel: `pos_sync/Injeksi_Reco_Delanggu.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 13):** Pembersihan Duplikat Master Item Hemat & Aktivasi POS Package Delanggu:
  - Penghapusan item duplikat legacy `ITEM00001` dan `PAKET26-001` (tanpa foto/tanpa transaksi) sehingga di master Item tersisa 4 paket hemat resmi berurutan (`PAKET26-003` s/d `PAKET26-006`).
  - Penambahan mapping outlet `RS PKU MUHAMMADIYAH DELANGGU` ke dalam child table `outlets` pada seluruh 6 dokumen POS Package (`HEMAT 1 NEW` s/d `HEMAT 4 NEW`, `Paket Box Ropi Isi 20`, `Paket Goodiebag 6 ROPI`) agar paket dinamis aktif dan muncul dengan badge PACKAGE di layar kasir POS Next.
  - Pembersihan 21 Stock Entry dan 20 POS Production Log yang sebelumnya dibatalkan.

- **2026-10-06 (sesi 5 lanjutan 12):** Migrasi Produksi Delanggu via Native Work Order + POS Production Recipe ke ERPNext Cloud (`https://ropierpnext.frappe.cloud`):
  - Sumber: `https://rotiropi.j.frappe.cloud` (`[API-KEY-FROM-ENV]`), filter company `RS PKU MUHAMMADIYAH DELANGGU`.
  - Ruang lingkup: 20 entri Manufacture pada jendela transaksi aktif 1–5 Oktober 2026.
  - Revisi Arsitektur Resmi POSNext (Work Order + make_stock_entry):
    - 20 Stock Entry independen sebelumnya dibatalkan (`docstatus: 2`) dan diganti dengan alur resmi Work Order.
    - Work Order dibuat & disubmit per batch (`use_multi_level_bom: 0`, `skip_transfer: 1`, `wip_warehouse: Stores - RPMD`, `planned_start_date: historical`).
    - Stock Entry Manufacture digenerate secara native lewat API `erpnext.manufacturing.doctype.work_order.work_order.make_stock_entry` dan disubmit dengan cap tanggal & jam asli eResto.
    - Work Order otomatis berstatus `Completed` (20/20 Completed, produced_qty = target qty).
    - POS Production Log (`PPLOG-2610-00021` s/d `00040`) tercatat di POS Next dengan relasi ganda ke Work Order dan Stock Entry.
  - Transformasi Resep (Sesuai BOM POS Production Recipe Baru):
    - Output produk: Roti Matang (`PJO*`): `RP001` -> `PJO2603` (Ropi Butter Matang, 60 Pcs), `RP002` -> `PJO2601` (Ropi Coklat Matang, 72 Pcs), `RP003` -> `PJO2602` (Ropi Keju Matang, 36 Pcs), `CR001` -> `PJO2605` (Croissant Matang, 12 Pcs), `GM001` -> `PJO2604` (Gempi Matang, 3 Pcs).
    - Bahan baku kemasan (`PEL260076` Paper Bag & `PEL260069` Box Gempi) dikeluarkan sepenuhnya dari resep produksi, terpotong otomatis saat penjualan POS Invoice (Product Bundle).
    - Konsumsi bahan baku: Dough (`PJ260010` s/d `14`), Krim Kopi (`PJ260016`), Gula Cair (`BB260038`), Olesan Pastry (`BB260046`), dan Plastik Alas Gempi (`PEL260077`).
  - Hasil injeksi (100% LOLOS, 0 gagal):
    - Work Order: **20 / 20 Completed** (`WO-RPMD-261006003` s/d `WO-RPMD-261006022`).
    - Stock Entry: **20 / 20 Submitted** (`SE-MFG-261006023` s/d `SE-MFG-261006042`).
    - POS Production Log: **20 / 20 Submitted** (`PPLOG-2610-00021` s/d `PPLOG-2610-00040`).
    - Saldo fisik matang & dough di `Stores - RPMD` balance dan tercatat di buku besar manufaktur.
    - Integritas pembukuan: Journal Entry pembuka `ACC-JV-2026-00001` dan 9 Stock Reconciliation tetap utuh dan aman.
  - Skrip: `pos_sync/inject_delanggu_work_order_production.py`. Laporan Excel: `pos_sync/Injeksi_Work_Order_Delanggu.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 11):** Injeksi POS Invoice eResto untuk outlet RS PKU MUHAMMADIYAH DELANGGU ke ERPNext Cloud (`https://ropierpnext.frappe.cloud`):
  - Sumber: eResto API v3 orders outlet Delanggu (`bb271ab7-b25c-4b08-b05a-b0f8980bff34`), rentang 1–5 Okt 2026.
  - Total order eResto: 106 order (1 Okt: 23, 2 Okt: 26, 3 Okt: 34, 4 Okt: 0 [tutup], 5 Okt: 23).
  - Penyeragaman nama dan kode Paket Hemat:
    - Master Item diseragamkan tanpa kata "Paket": `PAKET26-004` -> `Hemat 1 NEW`, `PAKET26-005` -> `Hemat 2 New`, `PAKET26-003` -> `Hemat 3 New`, `PAKET26-006` -> `Hemat 4 New`.
    - Kode item pada seluruh baris transaksi POS Invoice Delanggu diselaraskan 100% dengan parent item POS Package: Hemat 1 memakai `PAKET26-004` (menggantikan anomali legacy `ITEM00001`), dan Hemat 3 memakai `PAKET26-003` (menggantikan `PAKET26-001`).
    - Kamus `experiments/sku_to_item_code.csv` diselaraskan ke `PAKET26-004` dan `PAKET26-003`. Skrip: `pos_sync/harmonize_hemat_names.py`.
  - Konfigurasi master & POSNext di Cloud:
    - Update `payments` pada POS Profile `SHIFT 1 - RS PKU MUHAMMADIYAH DELANGGU` agar lengkap 4 metode bayar (Cash, Debit Card, Credit Card, QRIS) dan set `cost_center = "Main - RPMD"`.
    - Setup `valuation_rate` resmi pada 14 komponen bundle (powders, kemasan, matang).
    - Setup temporary schedule bypass (`pos_schedule_enforce_closing = 0`) selama proses backdate HO, lalu dipulihkan kembali ke 1.
  - Hasil injeksi (100% LOLOS, 0 gagal, 0 skip):
    - POS Invoice submitted: **106 / 106 invoice** (`PINV-RPMD-261006001` s/d `PINV-RPMD-261006106`).
    - POS Opening Shift: 4 dokumen (`POPEN-RPMD-261006002` s/d `POPEN-RPMD-261006005`).
    - POS Closing Shift: 4 dokumen (`POCLO-RPMD-261006001` s/d `POCLO-RPMD-261006004`).
    - Omzet terinjeksi: **Rp 2.114.000,00** = Σ eResto (selisih Rp 0,00 persis).
    - Stock Ledger: 246 pergerakan stok tercatat di `Stores - RPMD`.
    - Integritas pembukuan: Journal Entry pembuka `ACC-JV-2026-00001` dan 9 Stock Reconciliation tetap utuh dan aman.
  - Laporan Excel verifikasi: `pos_sync/Injeksi_POS_Invoice_Delanggu.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 10):** Migrasi Gambar Item dari Site Lama ke Site Baru (`https://ropierpnext.frappe.cloud`):
  - Sumber: `https://rotiropi.j.frappe.cloud` (API Key `[API-KEY-FROM-ENV]`).
  - Target: `https://ropierpnext.frappe.cloud` (API Key `[API-KEY-FROM-ENV]`).
  - 31 item dengan gambar di site lama diproses (29 item kode identik, `GM002` dipetakan ke `GM005` Gempi Choco Crunchy).
  - Gambar didownload dari site lama (baik `/files/` public maupun `/private/files/` private), diupload ke site baru via `/api/method/upload_file` sebagai public file (`is_private=0`) agar thumbnail/foto tampil mulus di Desk & POS UI.
  - Field `image` pada Item Master diset via `frappe.client.set_value` dan seluruh 30 item di site baru terverifikasi menampilkan gambar dengan URL publik valid (HTTP 200 OK).
  - Skrip eksekutor: `pos_sync/transfer_item_images.py`.
  - Laporan Excel verifikasi: `pos_sync/Transfer_Item_Images_Report.xlsx` (31 baris, 100% LOLOS).
  - Dokumen pembukuan & transaksi (Journal Entry `ACC-JV-2026-00001` dan 9 Stock Reconciliation) tetap 100% aman dan utuh.

- **2026-10-06 (sesi 5 lanjutan 9):** Injeksi Stock Reconciliation 30 September 2026 jam 11:24
  untuk Gudang Bahan Baku - JURI (`RECO-JURI-261006008`) dari data opname bahan baku eResto:
  - 34 baris opname diproses:
    - 5 item stok 0 dilewati (`BB0037` Filling Mocca, `BB0038` Filling Tiramisu, `BB0041` Filling Vanila,
      `BB0187` Kertas Alas Produksi, `BB0005` Salt Butter).
    - 1 item non-stock dilewati (`BB0193` Tisu Produksi).
    - 7 item belum terdaftar di master ERPNext dilewati (`BB0045` Filling Sarikaya, `BB0013` Pasta Milk,
      `BB0017` Pasta Pandan, `BB0189` Silver Foil, `BB0319` Teh Enak, `BB0317` Teh Gopek, `BB0318` Teh Jawa).
    - 21 item stock valid dipetakan dan dikonversi UOM-nya secara presisi:
      - Curah gram: Filling Coklat (730 kg), Filling Keju (240 kg), Garam (210 kg), Butterblend (75 kg),
        Pasta Coffee Caramel (216 kg), Susu Gempi (25 kg), Tepung Dough (74 zak = 1.850.000 g),
        Tepung Krim (79 zak = 1.975.000 g), Susu Dough (10 zak = 250.000 g), Gula Pasir (4 zak = 200.000 g),
        Gula Halus (53 ctn = 530.000 g), Filling Butter (21 ctn = 252.000 g), Margarine Dough (94 ctn = 1.410.000 g),
        Margarine Krim (41 ctn = 615.000 g).
      - Satuan ml: Air Galon (33 Galon = 627.000 ml).
      - Pcs/Pack: Plastik Krim (30.000 Pcs), Plastik Paking Dough (195 kg = 31.200 Pcs), Karet Gelang (88 Pack = 92.400 Pcs),
        Plastik Sampah (548 kg), Plastik Wayang (8 Pack), Sarung Tangan Plastik (33 Pack).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006008`, status: Submitted).
  - Verifikasi: 21 baris SLE tercatat, 21 Bin aktif di Gudang Bahan Baku - JURI dengan total
    nilai persediaan Rp 237.989.055,03. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Bahan_Baku.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 8):** Injeksi Stock Reconciliation 2 Oktober 2026 jam 10:00
  untuk Gudang Office / GA - JURI (`RECO-JURI-261006007`) dari data SAGOFF.021026.001:
  - 6 baris opname diproses:
    - 2 item baru dibuat di master: `SG260013` (Seragam Celana Pabrik) & `SG260014` (Seragam Baju Pabrik)
      agar merefleksikan SKU eResto secara utuh tanpa pemisahan warna artifisial.
    - 1 item stok 0 dilewati (`BB0249` Kertas Continous Form, 0 Box).
    - 5 item stock valid dipetakan: `BB0210` Sepatu Produksi (8 Pcs) -> `SG260005` (Rp 106.995,20),
      `BB0212` Tinta Hitam Printer (6 Pcs) -> `BHP260008` (Rp 92.343,08),
      `BB0214` Seragam Celana Pabrik (28 Pcs) -> `SG260013` (Rp 69.635,26),
      `BB0215` Seragam Baju Pabrik (89 Pcs) -> `SG260014` (Rp 102.665,30),
      `BB0253` Kertas A4 (37 Pack) -> `ATK260039` (Rp 38.831,92).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006007`, status: Submitted).
  - Target warehouse: `Gudang GA - JURI` (warehouse resmi untuk General Affairs / Office di struktur produksi).
  - Verifikasi: 5 baris SLE tercatat, 5 Bin aktif di Gudang GA - JURI dengan total
    nilai persediaan Rp 13.933.800,10. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Office.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 7):** Injeksi Stock Reconciliation 2 Oktober 2026 jam 09:00
  untuk Gudang Vendor - JURI (`RECO-JURI-261006006`) dari data opname vendor:
  - 3 item peralatan dipetakan 1:1 ke kode master `PER26*` (stock_uom: Unit):
    - `BB0237` Freezer 600L (7 Unit @ Rp 5.450.000,00) -> `PER260008` (Total: Rp 38.150.000,00).
    - `BB0289` Oven Listrik 3 Phase (13 Unit @ Rp 5.705.907,94) -> `PER260016` (Total: Rp 74.176.803,22).
    - `BB0124` Proofer (20 Unit @ Rp 4.500.000,00) -> `PER260017` (Total: Rp 90.000.000,00).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006006`, status: Submitted).
  - Verifikasi: 3 baris SLE tercatat, 3 Bin aktif di Gudang Vendor - JURI (total 40 Unit fisik)
    dengan total nilai persediaan Rp 202.326.803,22. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Vendor.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 6):** Injeksi Stock Reconciliation 2 Oktober 2026 jam 14:00
  untuk Gudang Peralatan - JURI (`RECO-JURI-261006005`) dari data opname peralatan:
  - 9 item peralatan dipetakan 1:1 ke kode master `PER26*` (stock_uom: Unit):
    - `BB0111` Oven 1 Deck 2 Tray (Gas) (2 Unit) -> `PER260014` (Rate: Rp 0,00, allow_zero_rate=1).
    - `BB0124` Proofer (7 Unit) -> `PER260017` (Rate: Rp 4.500.000,00).
    - `BB0237` Freezer 600L (3 Unit) -> `PER260008` (Rate: Rp 5.115.199,79).
    - `BB0277` Meja Loyang Stainless (3 Unit) -> `PER260011` (Rate: Rp 2.000.000,00).
    - `BB0278` Meja Rak Oven (1 Unit) -> `PER260012` (Rate: Rp 2.000.000,00).
    - `BB0288` Freezer 750L (2 Unit) -> `PER260009` (Rate: Rp 6.126.126,20).
    - `BB0289` Oven Listrik 3 Phase (3 Unit) -> `PER260016` (Rate: Rp 5.705.907,94).
    - `BB0290` Panel 1 Phase (2 Unit) -> `PER260003` (Rate: Rp 1.344.400,00).
    - `BB0291` Panel 3 Phase (21 Unit) -> `PER260004` (Rate: Rp 1.683.652,89).
  - Melengkapi Item Default akun persediaan (`1145.000 - Finished Good - JURI`) untuk seluruh 9 item `PER26*`.
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006005`, status: Submitted).
  - Verifikasi: 9 baris SLE tercatat, 9 Bin aktif di Gudang Peralatan - JURI dengan total
    nilai persediaan Rp 122.261.086,28. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Peralatan.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 5):** Injeksi Stock Reconciliation 30 September 2026 jam 23:00
  untuk Gudang Jakarta - JURI (`RECO-JURI-261006004`) dari data eResto SACK2.011026.001:
  - 123 baris opname diproses: 32 item stok 0 dilewati, 9 item belum ada di master ERPNext
    dilewati (Wijen Hitam/Putih, Balon Kuning/Pink/Putih, Botol Bistro 600/800, Corong, Daun Teh Enak).
  - 82 item stock valid berhasil dipetakan dan dikonversi UOM-nya secara presisi:
    - Dough (Butter 1.123 Pack, Coklat 1.418 Pack, Gempi 1.149 Pack, Keju 923 Pack, Croissant 346 Pack, Krim Kopi 2.330 Pcs).
    - Bubuk minuman (Lemonade, Milo, Teh Tarik, Coffeemate, Selezione, Coffee Classic, Latte, Cocoa).
    - Perlengkapan & ATK (Paper bag, Gelas, Kardus, Loyang, Kuas, Lakban, Kaos Polo, dll).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006004`, status: Submitted).
  - Verifikasi: 82 baris SLE tercatat, 82 Bin aktif di Gudang Jakarta - JURI dengan total
    nilai persediaan Rp 241.237.197,60. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Jakarta.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 4):** Injeksi Stock Reconciliation 30 September 2026 jam 22:23
  untuk Gudang Produksi - JURI (`RECO-JURI-261006003`) dari data eResto SAGPT.300926.004:
  - 29 baris opname diproses: 1 item baru dibuat di ERPNext (`BB260021` Plastik Wayang, Pack),
    1 item non-stock dilewati (`BHP260028` Tisu Pabrik / Produksi), 1 item stok 0 dilewati
    (`BB0138` Plastik Sampah).
  - 27 item stock dipetakan dan dikonversi UOM-nya (ctn/kg/zak/Galon/Pail/Pack -> stock_uom).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006003`, status: Submitted).
  - Verifikasi: 27 baris SLE tercatat, 27 Bin aktif di Gudang Produksi - JURI dengan total
    nilai persediaan Rp 93.886.227,72. Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh.
    Laporan Excel: `pos_sync/Injeksi_Reco_Gudang_Produksi.xlsx`.

- **2026-10-06 (sesi 5 lanjutan 3):** Injeksi Stock Reconciliation 1 Oktober 2026 jam 18:00
  untuk Gudang Barang Jadi - JURI (`RECO-JURI-261006002`) dari data SO Dough eResto:
  - 6 item dough & krim dipetakan: `BB0046` Dough Butter (1.436 Pack) -> `PJ260012` (17.232 Pcs @ Rp779,79),
    `BB0049` Dough Keju (1.331 Pack) -> `PJ260014` (15.972 Pcs @ Rp902,26),
    `BB0168` Dough Croissant (467 Pack) -> `PJ260010` (2.802 Pcs @ Rp2.675,26),
    `BB0085` Krim Kopi (1.644 Pcs) -> `PJ260016` (1.644 Pcs @ Rp14.170,91),
    `BB0261` Dough Gempi (759 Pack) -> `PJ260011` (2.277 Pcs @ Rp2.480,24),
    `BB0047` Dough Coklat (1.852 Pack) -> `PJ260013` (22.224 Pcs @ Rp803,55).
  - Mengisi field standar akuntansi dan field kustom UI (`custom_uom`, `custom_qty_after`,
    `custom_conversion_factor`, `custom_valuation_rate_per_uom`).
  - Dokumen berhasil disubmit (`RECO-JURI-261006002`, status: Submitted).
  - Total nilai stok bertambah Rp 82.146.894,24. Bin saldo fisik 6 item 100% aktif dan sesuai.
  - Laporan Excel diperbarui: `pos_sync/Injeksi_Reco_Barang_Jadi.xlsx` (sheet `Reco_GBJ_01Okt_18-00`).

- **2026-10-05 (sesi 5 lanjutan 2):** Mapping dan injeksi Stock Reconciliation
  Gudang Barang Jadi - JURI dari data Stock Opname eResto per 30 September 2026 jam 11:00:
  - 125 baris opname mentah diproses: deduplikasi SKU `BB0090` (7 Pcs), skip 8 item
    stok 0, skip 6 item belum terdaftar di master (sesuai persetujuan user).
  - 110 item dipetakan dan diinjeksi via API ke `ropierpnext.frappe.cloud` dalam
    dokumen `RECO-JURI-261006001` (lengkap dengan field kustom UI).
  - 16 item berhasil dikonversi UOM dan valuation rate-nya (kg->g, pack->g,
    pack->pcs) secara presisi; 3 item bahan baku baru (`BB260060`, `BB260061`,
    `BB260062`) dilengkapi akun persediaan default-nya (`1143.000 - Raw Material - JURI`).
  - Dokumen disubmit dengan `set_posting_time = 1`, `posting_date = 2026-09-30`,
    `posting_time = 11:00:00`.
  - Verifikasi: 110 SLE tercatat, Bin aktif di Gudang Barang Jadi - JURI.
    Journal Entry `ACC-JV-2026-00001` tetap 100% aman dan utuh. Laporan Excel:
    `pos_sync/Injeksi_Reco_Barang_Jadi.xlsx` (sheet `Reco_GBJ_30Sep_11-00`).

- **2026-10-05 (sesi 5 lanjutan):** Penghapusan 3 dokumen Stock Reconciliation
  yang baru diinput salah (`RECO-JURI-261005001`, `RECO-JURI-261005002`,
  `RECO-JURI-261005003`) di ropierpnext.frappe.cloud. Dibatalkan dan dihapus
  bersih via API dengan `delete_linked_ledger_entries = 1` dan `allow_negative_stock = 1`.
  Hasil verifikasi akhir:
  - Stock Reconciliation = 0.
  - Stock Ledger Entry = 0.
  - Bin (actual_qty != 0) = 0.
  - Journal Entry `ACC-JV-2026-00001` (17 GL Entries) tetap utuh dan aman.
  - Pengaturan sistem dipulihkan ke default (`delete_linked_ledger_entries = 0`,
    `allow_negative_stock = 0`).

- **2026-10-05 (sesi 5):** Pembersihan total transaksi di ropierpnext.frappe.cloud
  sesuai instruksi user, menyisakan HANYA Journal Entry pembuka.
  Pembersihan: seluruh transaksi non-JE (Delivery Note 46, Purchase Receipt 27,
  Stock Entry 308, Work Order 120, Sales Order 17, Purchase Order 86, Stock
  Reconciliation 8, POS Closing Shift 4, POS Invoice 18, POS Opening Shift 4,
  POS Print Log 15) dibatalkan dan dihapus bersih via API menggunakan
  `delete_linked_ledger_entries = 1` dan `allow_negative_stock = 1`.
  Hasil verifikasi akhir di ropierpnext.frappe.cloud:
  - Seluruh tabel transaksi operasional (SO, DN, SI, PINV, PO, PR, PI, SE, WO, RECO) = 0.
  - Stock Ledger Entry = 0 baris.
  - Seluruh Bin (actual_qty) = 0.
  - Journal Entry pembuka `ACC-JV-2026-00001` (RPMD Rp 117.123.668) 100% aman dan utuh
    bersama tepat 17 baris GL Entry-nya. Cadangan tersimpan di `audit_logs/backup_ACC-JV-2026-00001.json`.
  - Semua pengaturan keamanan dan akuntansi dipulihkan normal ke 0.

- **2026-10-05 (sesi 4):** POS Invoice per transaksi 1–5 Okt diinjeksi ke site
  LOKAL (docs/08, `pos_sync/inject_pos_invoice.py`) — 38.852 order eResto →
  **38.168 invoice + 553 outlet-hari**, 0 gagal; tiap outlet-hari = POS
  Opening Shift + invoice (lane backdate HO, `posting_date`/`posting_time` =
  waktu eResto) + POS Closing Shift. Tiga fase: 29.919 (mapping awal) →
  32.315 (24 SKU ACC) → 38.168 (`--refresh-list` 20:47; data 5 Okt mengalir,
  +5.973 order). Verifikasi final (dicek ulang dari DB): posting_date =
  tanggal eResto (38.168 dicek, 0 beda), omzet Rp992.613.000 = Σ eResto
  (selisih 0), closing selisih 0 (553/553), GL balance 0 (sample 30).
  Skip 684 order dilaporkan (void 401, SKU butuh item baru 222, outlet baru
  RIDHOKA 47, total beda 10, total nol 4; omzet skip Rp11.641.000).
  Diskon eksplisit + `discount_confirmation_code` `Z86BKK3D` (gate SEC-04).
  Jebakan: satu user satu shift terbuka; `allow_change_posting_date`;
  valuation rate wajib saat stok 0 → `set_item_valuation.py` (SLE site lama;
  2 item asumsi dicatat); race tabSeries → retry serial; `reopen_shift` utk
  shift pilot TJBK (invoice pilot lama dibatalkan, order diinjeksi ulang).
  Flag `allow_change_posting_date` + `allow_negative_stock` sudah
  dipulihkan ke 0. FRC 554 invoice (Rp18.351.000) ikut terinjeksi di lokal —
  keputusan FRC (docs/02) belum diterapkan ke lane ini.

- **2026-10-05:** Tarikan detail SKU penuh 1–4 Okt (atas permintaan user:
  rekap lama header-only) — `pos-fetch/fetch_details_bulk.py` (cache resume
  `.cache_details/`): 27.368 detail, 0 gagal, 39.533 baris item, 70 SKU
  (26 termap Rp666.331.000, 44 unmapped Rp51.064.000; top: PG004/PG003/PG002
  Gempi, PR00072–75 Hemat, CKN02/TJ01). Rekonsiliasi header-vs-item:
  27.359 COCOK, 9 SELISIH (diskon header, mis. RS Karunia Kasih 1 order
  selisih 870rb), 0 TANPA ITEM. Output:
  `pos-fetch/Penjualan_2026-10-01_sd_2026-10-04_detail_SKU.xlsx`
  (Rekap_Harian, Rekap_SKU, Order_Items, Rekonsiliasi, Validation, Failed).

- **2026-10-05 (sesi 3):** Injeksi ke PRODUCTION `ropierpnext.frappe.cloud`
  tuntas (docs/07). Master: 8 company anak `OUTLET` (6 FRC + RSUP Palembang
  + Jambi Sarulangun) + customer internal + allow JURI; 9 supplier; 8 item;
  BOM-PJ260016-001; FY 2026 + MoP + `overproduction 0→50`. Fix prod:
  159 item_defaults JURI + RPMD/RQLY (item-wise inventory account aktif),
  11 item disamakan non-stock, cache Item di-touch (get_cached_doc TTL 1 jam
  tak dibersihkan oleh insert child). Opening dihitung:
  `opening = bin_lokal − ΣSLE(dokumen diinjeksi)` → 8 RECO 30 Sep.
  Dokumen: WO 120 (98+22) / PO 86 (42/43/1) / SO 17 (16/1) / PR 27 /
  SE 308 / DN 46 — semua tercap waktu submit (validasi ERPNext per titik
  waktu); Bin paritas **697 pasangan, 0 selisih**; produced_qty 26.628 =
  26.628. Idempoten penuh via marker `ERESTO` + `prod_src/state.json`.
  Jebakan terdokumentasi di docs/07 (set_value `name` bukan `docname`;
  MoP akun salah otomatis; customer Harapan indah beda kapitalisasi;
  SLE is_cancelled). Laporan `pos_sync/Injeksi_Prod.xlsx`.

- **2026-10-05 (sesi 2):** Migrasi dituntaskan — 103 SE non-WO jendela ikut
  dimigrasi (sumber inflow stok gudang barang jadi), opening stock direplikasi
  dari site lama via Stock Reconciliation (titik = saldo lama − neto jendela),
  DN **46/46 submitted**, SE 308 (13 Repack/Manufacture bundel di-skip sesuai
  model bundel non-stock baru), WO 98 Completed + 22 In Process persis sumber,
  manufacture stock-item 45.777 = 45.777, paritas saldo 388/461 pasangan
  (73 sisanya terklasifikasi: non-stock model baru / gerakan 3–4 Okt luar
  jendela / item master dihapus). Keterbatasan: 14 PR + SE + 1 DN pakai tanggal
  posting hari migrasi. Detail: docs/06 bagian "Penyelesaian penuh".

- **2026-10-05:** Migrasi site-lama→baru 1–2 Okt (docs/06, kode `pos_sync/`) —
  120 WO + 218 SE + 86 PO + 27 PR + 17 SO + 46 DN masuk site baru, qty per
  item 0 selisih semua DocType (verifikasi `Migrasi_Okt2026.xlsx` LOLOS).
  Master: 2 item + 9 supplier + 2 customer + BOM Krim Kopi dibuat; seed awal
  4 bahan + top-up susulan (backdate 30 Sep); 35 DN jadi draft (shortfall
  stok outlet, disetujui user); 1 PO cancelled + 1 SO draft dicerminkan;
  workflow site baru dinonaktifkan user sebelum migrasi. Pelajaran:
  rename_doc form-encoded; seed backdate menimpa Bin (perbaiki via
  Stock Reconciliation); submit SE transfer-dulu-manufacture-kemudian;
  PO/SO/DN kunci idempotency di `title` (tak punya remarks).

- **2026-10-04:** Injeksi agregat POS 1–4 Okt (Phase 1 docs/03) —
  `experiments/inject_sales_aggregate.py`: 418 JE `ERESTO-<branch>-<date>`
  submitted (135+135+134+14 outlet-hari), Rp717.395.000, GL balance 0,
  selisih 0 vs eResto; rerun idempoten (418 sudah-ada, 0 duplikat).
  Rekap eResto di-fetch ulang (27.053 → 27.366 order). Output:
  `experiments/Inject_Agregat_2026-10-01_sd_2026-10-04.xlsx`.
  Batasan: posting_date = tanggal eResto per JE sudah benar (JE bebas
  tanggal, tidak seperti POS Invoice); tanpa gerakan stok.

- **2026-10-04:** Dibuat `PROMPT_SESI_BERIKUTNYA.md` — handoff sesi
  (status, bukti pilot, keputusan mapping stok, klarifikasi user,
  pertanyaan terbuka) siap ditempel di sesi baru.

- **2026-10-04:** Dokumen tetap `docs/05-alur-dough-ke-bundle.md` —
  rantai dough→matang→bundle untuk semua keluarga (tabel per produk),
  resep yield terukur (Ropi 12, Gempi 3, Croissant 6 per pack dough),
  jejak API (`/v2/productions`, `/v2/stock_cards`), implikasi migrasi.
  Bug bundle `GM001` (berisi dirinya sendiri) diperbaiki → `PJO2604`+box.
  Dubai Dough Salt Butter dikonfirmasi dijual sebagai dough (tanpa
  matang/bundle) — pengecualian terdokumentasi.

- **2026-10-04:** Mapping stok SO September — 47 SKU: 39 target + 8 skip
  (`Template_Mapping_Stok.xlsx`, `stok_sku_to_item.csv`). Keputusan user:
  RR* barang jadi → PJO* matang; BB0085 → PJ260016; bubuk tanpa padanan
  dibuat item baru BB260057-62 (`create_stok_items.py`, termasuk fix
  naming series `BB26-.###` via rename_doc).

- **2026-10-04:** Stok opname outlet: `fetch_so_monthly.py` menarik 93 SA
  `SO Monthly September` (91 outlet) + baris item via
  `/v2/stock_adjustment_items` (endpoint baru terverifikasi; detail SA
  hanya jurnal) → `Stock_SO_Monthly_September.xlsx` (2.782 baris,
  checksum 93/93). `Auto stock balancing` diskip.

- **2026-10-04:** Pilot 1 order eResto→ERPNext OK — `OR045.031026.000001`
  → `PINV-TJBK-261004001` (submit, GL balance, 5 SLE) →
  `POCLO-TJBK-261004001` (diff 0); skrip `experiments/pilot_post_one.py`;
  temuan bundle + posting_date didokumentasikan di docs/02.

- **2026-10-04:** Dokumen `docs/04-posnext-cara-kerja-penjualan.md` —
  cara kerja opening/invoice/closing POSNext dari bedah kode app
  `pos_next` (endpoint, hook, validasi, offline, EOD, implikasi migrasi).

- **2026-10-04:** POS setup lokal rampung — 16 Price Group (harga per tier dari
  sampling), 322 POS Profile (SHIFT 1 + SHIFT 2, 4 metode bayar), 2 Shift Group;
  company RSUP Palembang + 7 FRC aktif dibuat; 6 profil duplikat dihapus; docs +
  AGENTS + laporan `POS_Setup_Report.xlsx` diperbarui.
