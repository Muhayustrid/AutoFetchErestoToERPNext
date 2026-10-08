# ERPNext mapping — eResto vs new site

Source of truth for SKU mapping: `experiments/sku_to_item_code.csv`
(51 entries, columns `sku_eresto, item_code_erpnext,
item_name_erpnext, item_group, sumber`). Workbench with human edits:
`experiments/Template_Mapping_SKU.xlsx` (column E is the edited one).
Item master: `experiments/Item.xlsx` (308 rows).

## SKU → Item Code rules

- Key on `product_sku`, never on name. Zero duplicate SKU names
  across 3 outlet-days of fetch data.
- `sumber` values: `cocok` (name-identical, 9), `tebakan` (needs
  confirm, 11), `gabung-frc` (franchise code merged, 3),
  `keputusan-user` (4: AIR01+AIR02→AM001, PR00039→PAKET010926-005,
  PKG001→PEL260083), plus hasil ACC user 2026-10-05: `acc-user` (18),
  `acc-user-promo-hemat` (3), `bukti-harga+acc` (3).
- Same product, different SKU per outlet type: `PR001/PR002/PR003`
  (owned) and `P0004/P0001/P0002` (franchise, "Roti Ropi ...",
  same Rp12k price) all map to `RP001/RP002/RP003`.
  Cancel the merge if the products differ.
- Do not use ERPNext codes across systems: eResto `PG001` is
  "Roti Gempi Original" but ERPNext `PG001` is "Goodie Bag 6 Roti".
- `PJ260009` (Air Mineral Outlet 600ml) is retired for sales;
  AIR01+AIR02 both map to `AM001` (Crystalin 600 ml).
- `PG001` (Goodie Bag) has no sales SKU; `PR00039` goes to
  `PAKET010926-005`, not `PG001`.
- `PJO2601–2605` ("... Matang") have no eResto POS counterpart.
  SKIP in POS mapping; they belong to production mapping.
- Daftar unmapped per 2026-10-05: 43 SKU di
  `pos_sync/Mapping_SKU_vs_Item_Lokal.xlsx` (sheet `SKU_Belum_Termap`).
  24 sudah di-ACC 2026-10-05 (bagian di bawah); sisa 19 SKU butuh
  item baru (`CM01/MC01/MC02`, `CP02`, `P0005`, `CM02`, `CR03`,
  `AIR03`, `PR00045`, `P0015`, `SK002`, `P0014`, `GD001`, `SU001`,
  `CM06`, `MC06`, `P0016`, `MC05`, `SK001`).
  Decide per SKU: create Item, map to nearest, or skip.
- New outlets will surface new SKUs (Tradisional `TR01–TR04`,
  `CK002`, more Paket). The CSV grows; it is never final.

## ACC user 2026-10-05 — 24 SKU varian (item sudah ada)

`sku_to_item_code.csv` awal dibangun dari sampel 3 outlet-hari, sehingga
SKU yang hanya muncul di outlet tipe lain (FRC vs reguler) jatuh ke
`SKU_UNMAPPED`. User meninjau `pos_sync/Mapping_SKU_vs_Item_Lokal.xlsx`
(sheet `Item_vs_SKU` + `SKU_Belum_Termap`) dan meng-ACC 24 SKU di mana
item-nya ternyata sudah ada. Semua sudah tertulis di
`sku_to_item_code.csv` (sumber `acc-user` / `acc-user-promo-hemat` /
`bukti-harga+acc`) dan `Template_Mapping_SKU.xlsx` (Status
`ACC 2026-10-05`). Dampak dry-run injeksi 1–5 Okt: rencana invoice
29.919 → 32.315, skip order 2.960 → 564.

### A. Varian kode outlet lain (18 SKU)

| SKU eResto | Nama di eResto | Item Code | Item Name (ERPNext) | Catatan |
|---|---|---|---|---|
| PG004 | Roti Gempi Tiramisu | GM004 | Gempi Tiramisu | varian FRC dari P0017 |
| PG003 | Roti Gempi Dark Choco | GM003 | Gempi Dark Choco | varian FRC dari P0012 |
| PG002 | Roti Gempi Choco Crunchy | GM005 | Gempi Choco Crunchy | varian FRC dari P0011 (eResto typo "Cruncy") |
| P0013 | Gempi Original | GM001 | Gempi Original | melengkapi PG001 eResto |
| CKN02 | Chocolate Hot | CK002 | Chocolate Hot | pasangan CKN01 (Ice) |
| CK01 | Es Coklat | CK001 | Chocolate Ice | — |
| TJ01 | Ice Tea | JT001 | Jasmine Tea Ice | dikonfirmasi user: Ice Tea = Jasmine Tea |
| TJ02 | Hot Tea | JT002 | Jasmine Tea Hot | dikonfirmasi user: Hot Tea = Jasmine Tea |
| TR03 | Kunir Asem | TR003 | Kunir Asem | — |
| TR01 | Beras Kencur | TR001 | Beras Kencur | — |
| CR01 | Croissant Original | CR001 | Croissant | stok fisik di PJO2605 |
| BC02 | Es Kopi Hitam | BC001 | Americano Ice | user: beda produk dari Americano Ice, tetap digabung |
| PR00075 | Hemat 1 | ITEM00001 | Hemat 1 NEW | keluarga paket hemat |
| PR00073 | Hemat 3 | PAKET26-001 | Hemat 3 New | keluarga paket hemat |
| PR00074 | Hemat 4 | PAKET26-006 | Paket Hemat 4 New | keluarga paket hemat |
| PR00072 | Hemat 2 | PAKET26-005 | Paket Hemat 2 New | keluarga paket hemat |
| PR00038 | Box Ropi isi 20 pcs | PAKET26-002 | Paket Box Ropi Isi 20 | — |
| PKG01 | Goodie Bag | PEL260072 | Goodie Bag | item dibuat sesi sebelumnya |

### B. Keluarga Promo Hemat (3 SKU — dikonfirmasi user)

| SKU eResto | Nama di eResto | Item Code | Item Name (ERPNext) | Catatan |
|---|---|---|---|---|
| PR00034 | Promo Hemat 4 | PAKET26-006 | Paket Hemat 4 New | = Hemat 4 |
| PR00037 | Promo Hemat 1 | ITEM00001 | Hemat 1 NEW | = Hemat 1 |
| PR00033 | Promo Hemat 3 | PAKET26-001 | Hemat 3 New | = Hemat 3 |

### C. Kandidat "pilih varian" — bukti harga + konfirmasi user (3 SKU)

| SKU eResto | Nama di eResto | Item Code | Item Name (ERPNext) | Catatan |
|---|---|---|---|---|
| BC01 | Black Coffee | BC002 | Black Coffee Hot | dikonfirmasi user 2026-10-05 |
| CK02 | Coklat Panas | CK002 | Chocolate Hot | dikonfirmasi user 2026-10-05 |
| CP01 | Cappucino | CP001 | Cappucino Ice | dikonfirmasi user 2026-10-05 |

Konfirmasi user 2026-10-05: TJ01/TJ02 memang Jasmine Tea (es & hot),
ketiga pilihan varian di tabel C sudah benar, dan BC02 "Es Kopi Hitam"
tetap digabung ke BC001 "Americano Ice" meski user menilai keduanya
sebenarnya dua produk berbeda.

Sisa belum diputuskan: 19 SKU butuh item baru (205 order masih
`SKU_UNMAPPED` di rencana injeksi 1–5 Okt).

## Outlet mapping (to decide)

Per outlet: ERPNext Customer (walk-in default), Warehouse
(`Gudang Outlet {name} - ROPI` or existing), Cost Center
(`Cabang {branch} {name}`), POS Profile (`POS-{branch}`),
Mode of Payment accounts (cash register + e-wallet clearing).
Branch numbers observed: `045` Kebumen, `097` Bangka Tengah (FRC),
`120` Majenang, `O77`, `O92`, `O47`, `O54`, `O96`, `202`, `208`.
Franchise flag: outlet name contains `(FRC)` (7 outlets, Rp18M
of Rp709M in sample). `dokumen/Mode of Payment.xlsx` (161 rows) and
`dokumen/Fiscal Year.xlsx` (160 companies incl. RS entities) are the
import templates; each outlet-company pair needs its accounts.

## Outlet FRC dikecualikan (keputusan user 2026-10-05)

Outlet franchise (`(FRC)` di nama) **tidak ikut injeksi**: bukan
pendapatan grup — skema beli-putus/konsinyasi belum diputuskan
(lihat Known issues "skema stok franchise").
Filter: skip outlet yang namanya mengandung `(FRC)`.
Dampak injeksi agregat 1–4 Okt: 27 outlet-hari FRC ikut terposting
(7 outlet: Bangka Tengah 097, Jambi Sarulangun 139,
Mitra Swalayan Gombong 110, Plaza Haji alQosbah 169,
RS Medina Garut O46, RSU San Medica O96, Sungai Penuh O57 —
584 order, Rp19.969.000 / 2,8% dari Rp717.395.000) → **27 JE
`ERESTO-*` FRC harus dibatalkan (cancel) dari ERPNext lokal**,
rerun `inject_sales_aggregate.py` berikutnya otomatis skip FRC.

Status 2026-10-05 (malam): di lane **POS Invoice lokal** (docs/08) outlet
FRC masih terposting — 554 invoice / Rp18.351.000; 27 JE agregat FRC
di atas masih submitted (belum dibatalkan). Perlu keputusan user apakah
keduanya ikut dibatalkan / dikecualikan.

## Payment → Mode of Payment

Measured mix: cash 70.7%, ewallet/QRIS 29.1%, debit 0.2%,
credit ~0. Aggregate posts split cash vs ewallet per outlet-day
into register vs clearing accounts.

## Void and refund rules

- Skip rows with `void=True`, `paid_quantity=0`, or header
  `total=0`. Keep `void_note` for audit.
- eResto refund = auto-void (`void_note` like "salah input
  (Auto void from refund)"), payment fields go null/empty.
  No negative-amount Sales Return needed for these.
- 1.1% of orders fully void (301/27,053), always full-order,
  never partial. Total of void orders is already 0, so skipping
  does not change revenue.
- Anomaly: 3 zero-total orders without void flag (RSUD DR. R.
  SOETIJONO BLORA). Confirmed complimentary/OC, not refunds:
  they have no record in `/v2/refunds`. Exclude from revenue;
  decide complimentary Item treatment before posting.
- Refund source: `/v2/refunds` joined on `order_no`
  (see `docs/01-eresto-api.md`). Pull per `created_at` window;
  note the window can include orders outside the sales window.

## POS setup baru (2026-10-04, lokal)

State: 322 POS Profile (161 `SHIFT 1` + 161 `SHIFT 2`), 16 Price
Group, 19 Price List, 2 Shift Group (`ALL TIME` 161 members,
`SHIFT 2` 161 members, jadwal 05:00-14:00).
Ringkasan: `experiments/POS_Setup_Report.xlsx`.

- Company baru (RSUP Palembang + 7 FRC aktif) = anak `OUTLET REGULER`,
  CoA via Existing Company -> OUTLET REGULER. Customer internal dengan
  `represents_company` = company. Supplier `PT. JUARA ROTI INDONESIA`
  boleh transaksi dengan semua company itu (child `companies`).
- Nama perusahaan FRC ditulis persis seperti eResto, termasuk `(FRC)`.
- POSNext: **Price Group** memiliki satu Price List `PG-<nama>`,
  Item Price (unscoped), dan mengklaim **semua** POS Profile milik
  company di child `outlets`. Jangan buat Price List/Item Price manual
  untuk tier POSNext - ownership field `custom_pos_next_price_group`
  akan menolak (`Price List already exists and is not linked`).
  Urutan: prep -> pg -> prof -> claim -> group.
- Harga per tier disample dari transaksi eResto
  (`experiments/fetch_tier_prices.py` -> `tier_prices.json`):
  rate = harga `paid_quantity > 0`, non-void, modus per SKU. Konversi
  SKU->Item Code via `sku_to_item_code.csv`; SKU unmapped dibiarkan
  (64 baris di `Unmapped_SKU`, perlu keputusan user).
- POS Profile `SHIFT 1 - <company>`: `Stores - <abbr>`,
  item group Products, print `POS Next Receipt`, schedule 0:00-23:59.
  **Metode bayar semua profil**: Cash (default, allow returns),
  Debit Card, Credit Card, QRIS - pola SHIFT 1 Delanggu
  (`experiments/update_pos_payments.py`, idempoten). Tiap company
  butuh baris Mode of Payment Account untuk ke-4 metode itu (sudah
  lengkap; ERPNext menolak simpan profil tanpa akun).
  Membership Shift Group hanya lewat tabel Members (`ALL TIME`);
  menyimpan grup = sync jadwal ke member, dan meng-unlink yang tidak
  ada di daftar (stage `group` mengirim daftar kumulatif).
- `SHIFT 2 - <company>` dibuat untuk semua company (clone penuh dari
  SHIFT 1, `experiments/create_shift2.py`), masuk Shift Group
  `SHIFT 2` (05:00-14:00, dari profil Delanggu). Outlet tiap Price
  Group di-refresh agar mencatat kedua shift.
- 6 company varian ejaan (RS Kartika Asih, Medirossa - Cikarang,
  Mardatilah Pemalang, Rahman Rahim x2, RSI Muh. Kendal) sudah
  **dihapus profilnya** 2026-10-04 (`delete_duplicate_profiles.py`):
  keluar dari grup dulu, lalu delete; company-nya dibiarkan (data
  backup, nol riwayat transaksi). Sisa 1 profil tanpa PG: RSUD Taman
  Husada Bontang (tidak ada di eResto sama sekali).
- Company grup (JURI GROUP, OUTLET, PT. JUARA ROTI INDONESIA,
  TRAINING) tidak dibuatkan profil POS.

### Script alur POS setup

- `experiments/build_pos_matrix.py` -> `Company_POS_Setup.xlsx`
  (company -> tier -> price list).
- `experiments/fetch_tier_prices.py` -> `tier_prices.json`
  (sample harga per tier dari eResto).
- `experiments/apply_pos_bulk.py` -> apply ke ERPNext, idempoten,
  stage: prep/pg/prof/claim/group/verify (`--only`, `--tier`).
- `experiments/update_pos_payments.py` -> Cash+Debit+Credit+QRIS
  ke semua POS Profile.
- `experiments/delete_duplicate_profiles.py` -> hapus profil duplikat
  (pre-check link + transaksi, keluarkan dari grup, delete).
- `experiments/create_shift2.py` -> clone SHIFT 2 semua company +
  masuk grup SHIFT 2 + refresh outlet Price Group.
- `experiments/build_pos_report.py` -> `POS_Setup_Report.xlsx`.

## Pilot 1 order eResto -> POS Invoice (2026-10-04, lokal, TERBUKTI)

Skrip: `experiments/pilot_post_one.py` (idempoten, stop bila invoice
`remarks = ERESTO <order_no>` sudah ada). Order:
`OR045.031026.000001` (Toserba Jadi Baru Kebumen, 2026-10-03):
`PR001 x1 + CPN01 x2 = Rp36.000`, cash-only.

- Item jual (Ropi/Croissant/Gempi) adalah **Product Bundle** non-stok
  yang meledak jadi komponen stok (`Product Bundle` per item, mis.
  `RP001 -> PJO2603 x1 + PEL260076 x1`,
  `CP002 -> BB260031 x45 + PEL260071 x1 + PEL260085 x1`).
  `submit_invoice` menolak bila komponen kurang
  (`_validate_stock_on_invoice`, profil block karena Bin kosong).
  Solusi pilot lokal: `Stock Entry` tipe Material Receipt
  (`SE-MR-261004001`) mengisi komponen, karena alur produksi
  (PJO Matang, BB dough) belum masuk ERPNext.
- Payload = pola frontend (`update_invoice` lalu `submit_invoice`
  dengan dokumen draft penuh): items bawa `rate` = harga eResto
  (harus sama persis dengan Item Price — site ini
  `allow_user_to_edit_rate = 0`). `remarks = ERESTO <order_no>`
  sebagai kunci idempotency per-transaksi.
- User API (`ropierpnext@gmail.com`, System Manager dsb.) lolos
  `_check_profile_access` tanpa harus jadi POS Profile User
  (cabang `has_permission(doctype, "write")`); tetapi endpoint
  `create_opening_shift` TIDAK punya cabang itu — user API sempat
  ditambahkan ke `applicable_for_users` profil sekali.
- Hasil: `PINV-TJBK-261004001` submit (grand 36.000, Paid),
  6 GL balance (Kas Kasir Dr / Penjualan Cr + HPP Dr /
  Persediaan Cr), 5 SLE komponen bundle keluar,
  `POCLO-TJBK-261004001` closing (Cash expected 36.000,
  actual 36.000, diff 0), opening jadi Closed.
- Kolom `pos_closing_entry` tidak ada di site ini (kode guard
  `has_column`) — closing tetap valid tanpa stamp ke invoice.
- Batasan pilot: `posting_date` = hari POST (2026-10-04), bukan
  tanggal eResto (2026-10-03). Backdate butuh jalur HO
  (`reopen_shift` + `submit_backdate_invoice`, role System/POSNext/
  Sales/Accounts Manager + setting profil
  `allow_change_posting_date`) — belum dicoba.

## Mapping stok outlet — SO Monthly September (2026-10-04)

Sumber: 93 SA `SO Monthly September` (`experiments/fetch_so_monthly.py`,
`Stock_SO_Monthly_September.xlsx`, `stock_so_monthly.json`; 2.782 baris,
91 outlet). Workbench: `experiments/Template_Mapping_Stok.xlsx` +
`stok_sku_to_item.csv` (`build_stok_mapping.py`). 47 SKU unik:
39 punya target, 8 skip.

- **RR* barang jadi -> PJO* matang** (keputusan user): RR0001 Ropi
  Butter -> PJO2603, RR0002 -> PJO2601, RR0003 -> PJO2602, RR0008
  Roti Croissant -> PJO2605, RR0009 Roti Gempi -> PJO2604. Ini yang
  menampung saldo stok (RP00x/CR001/GM001 tetap item jual bundle
  non-stok). RR0004 Ropi Tiramisu -> skip (tidak ada padanan).
- **BB0046 Dough Butter -> PJ260012** Dough Ropi Butter (pabrik),
  pola sama untuk BB0047 -> PJ260013, BB0049 -> PJ260014,
  BB0168 -> PJ260010, BB0261 -> PJ260011. PJO2603 = hasil produksi
  dari dough tsb. Konversi Pack -> Pcs diasumsikan 1:1 (perlu
  konfirmasi saat seeding).
- **BB0085 Krim Kopi -> PJ260016** (bukan PJ260008 700gr).
- **Bubuk tanpa padanan -> 6 item baru** `BB260057-62`
  (`create_stok_items.py`): Bubuk Hepi Drink Moccacino/Cappucino/
  Kopi Karamel/Chocolate (Sachet), Kopi Hitam @6gr (Pcs),
  Susu Bubuk Campuran Minuman (g).
- **Konversi satuan** (stock_uom ERPNext): kg -> g x1000
  (BB0102/03/110, BB0145); Pack -> g sesuai gramasi (BB0329 x750,
  BB0340 x500, BB0341 x120, BB0342 x1000, BB0345 x450,
  BB0346/47 x960, BB0349 x640); Pack dough -> Pcs 1:1; sachet 1:1.
- **Skip dulu**: Olesan Blueberry BB0101, Olesan Sarikaya BB0107,
  RR0004, RR0010 Teh Enak Seduh, Dough Srikaya/Tiramisu/Vanilla
  (BB0052/53/54), item TIDAK AKTIF (BB0106/BB0108).
- **Terbuka**: BB0066 Goodie Bag -> PG001 "Goodie Bag 6 Roti"
  (status TEBAKAN, perlu konfirmasi user).
- Jebakan teknis: Item doctype site ini ber-naming series
  `BB26-.###` yang menimpa `item_code` saat create; item harus
  di-`frappe.client.rename_doc` setelah dibuat agar kode konsisten.
  Sudah ditangani di `create_stok_items.py`.
