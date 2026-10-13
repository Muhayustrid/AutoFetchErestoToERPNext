# Master Mapping — eResto ↔ ERPNext BARU (SATU SUMBER KEBENARAN)

> **Dokumen ini adalah sumber mapping TUNGGAL.** Semua ITEM_MAP di skrip lane
> (`pos_sync/migrate_*.py`) dan CSV lama (`experiments/sku_to_item_code.csv`,
> `experiments/stok_sku_to_item.csv`) adalah TURUNAN dari tabel di bawah.
> Saat menambah mapping baru: **tulis di sini dulu**, lalu sinkronkan ITEM_MAP
> skrip yang butuh. Skrip tetap punya salinan agar rerun idempoten tanpa baca
> file lain — tapi kebenaran = dokumen ini.

Cara baca tabel:
- **SKU** = `product_sku` eResto (kunci mapping, JANGAN pernah by nama).
- **Item Code** = master ERPNext site BARU (`ropierpnext.frappe.cloud`);
  seluruh 166 kode diverifikasi ada di BARU per 2026-10-13 (0 broken link).
- **Sumber** = bukti mapping:
  - `skrip-lane` = sudah dipakai & terposting di lane migrasi PO/SO
    (bukti transaksi; keputusan user 13 Okt ditandai `†`).
  - `csv:cocok` = nama item identik.
  - `csv:acc-user` / `csv:acc-user-promo-hemat` = ACC user 2026-10-05.
  - `csv:bukti-harga+acc` = bukti harga + konfirmasi user.
  - `csv:keputusan-user` = keputusan langsung user.
  - `csv:gabung-frc` = merge varian franchise (batal bila produk beda).
  - `csv:tebakan` = padanan otomatis, belum dikonfirmasi user (pakai hati-hati).
  - `csv-stok` = mapping lane stok/SO Monthly September.

## Aturan yang tidak boleh dilanggar

1. **Key = `product_sku`**, bukan nama produk.
2. **Item Code harus ada di site BARU** — cek `/api/resource/Item/<code>`
   sebelum POST; tidak ada = SKIP + catat, jangan tebak.
3. **Satu SKU = satu Item** di tabel ini. Kalau dua sumber beda = KONFLIK,
   stop dan minta keputusan user (jangan pilih diam-diam).
4. **Olesan Pastry (keputusan 2026-10-12)**: PO > 2026-10-08 → `BB26012`;
   PO ≤ 2026-10-08 → `BB260046`. Berlaku utk SKU `BB0174` & `BB0352`
   (helper `prod_common.olesan_pastry_item`).
5. **Goodie Bag = `PEL260072`** (`PG001` legacy sudah di-merge & dihapus —
   jangan pakai lagi). eResto `PG001` adalah "Roti Gempi Original" → `GM001`,
   beda arti dgn `PG001` ERPNext lama.
6. **Varian nota (BCN/CKN/CPN/TJN) & varian FRC** memakai item sama dgn
   varian reguler sesuai tabel (keputusan gabung).
7. Mapping baru hasil keputusan user ditandai `†` + tanggal di tabel.

## Tabel mapping (166 SKU, terurut SKU)

| SKU | Nama eResto | Item Code | Sumber |
|---|---|---|---|

| AIR01 | Air Mineral 600ml | AM001 | csv:keputusan-user |
| AIR02 | Air Mineral 600ml (FRC) | AM001 | csv:keputusan-user |
| BB0006 | Apron | PEL260006 | skrip-lane |
| BB0042 | Crispy Ball 500 gram | BB260048 | skrip-lane |
| BB0046 | Dough Butter | PJ260012 | csv-stok |
| BB0047 | Dough Coklat | PJ260013 | csv-stok |
| BB0049 | Dough Keju | PJ260014 | csv-stok |
| BB0055 | Es Kristal (12 kg) | BB260006 | skrip-lane |
| BB0066 | Goodie Bag | PEL260072 | csv-stok |
| BB0068 | Kuas Oles Loyang 1,5' | PEL260021 | skrip-lane (keputusan user 13 Okt)† |
| BB0071 | Gula Stik | BB260039 | csv-stok |
| BB0074 | Kanebo | PEL260018 | skrip-lane (keputusan user 13 Okt)† |
| BB0076 | Kaos Panjang | PEL260068 | skrip-lane |
| BB0078 | Kaos Polo | PEL260019 | skrip-lane |
| BB0080 | Kardus Ropi Kapasitas 20 roti (25 pcs/pack) | PEL260074 | csv-stok |
| BB0081 | Keju Chedar | BB260040 | skrip-lane |
| BB0082 | Lakban Besar | BHP260023 | skrip-lane (keputusan user 13 Okt)† |
| BB0085 | Krim Kopi | PJ260016 | csv-stok |
| BB0087 | Lakban Kecil | BHP260020 | skrip-lane (keputusan user 13 Okt)† |
| BB0090 | Kuas Oles Loyang 2' | PEL260022 | skrip-lane (keputusan user 13 Okt)† |
| BB0096 | Meises Coklat 1kg | BB260041 | skrip-lane (keputusan user 13 Okt)† |
| BB0100 | Minyak Oles 1 Kg | BB260042 | skrip-lane |
| BB0102 | Olesan Choco Crunchy (1 Kg) | BB260043 | csv-stok |
| BB0103 | Olesan Dark Choco (1 Kg) | BB260044 | csv-stok |
| BB0105 | Olesan Margarine | BB260045 | skrip-lane |
| BB0110 | Olesan Tiramisu (1 Kg) | BB260047 | csv-stok |
| BB0112 | Paper Bag Kapasitas 1 Roti | PEL260076 | csv-stok |
| BB0117 | Plastik Alas Gempi | PEL260077 | csv-stok |
| BB0118 | Plastik Kresek Ukuran 17 | PEL260081 | skrip-lane |
| BB0119 | Plastik Kresek Ukuran 24 | PEL260080 | skrip-lane |
| BB0120 | Plastik Krim | BB260019 | skrip-lane |
| BB0122 | Plastik Seal Roti | PEL260083 | skrip-lane |
| BB0124 | Proofer | PER260017 | skrip-lane |
| BB0126 | Ragi Basah | BB260023 | skrip-lane |
| BB0131 | Sarung Tangan Oven | PEL260038 | skrip-lane (keputusan user 13 Okt)† |
| BB0132 | Sarung Tangan Plastik | BHP260027 | skrip-lane |
| BB0134 | Sedotan Teh | PEL260084 | skrip-lane |
| BB0136 | Sendok Es Batu | PEL260041 | skrip-lane (keputusan user 13 Okt)† |
| BB0141 | Solet Gempi | PEL260043 | skrip-lane (keputusan user 13 Okt)† |
| BB0143 | Stirrer | PEL260085 | skrip-lane (keputusan user 13 Okt)† |
| BB0145 | Susu Bubuk untuk Campuran Minuman (1 Kg) | BB260062 | csv-stok |
| BB0153 | Telur Utuh | BB260027 | skrip-lane |
| BB0158 | Tepung Krim | BB260029 | skrip-lane |
| BB0159 | Timbangan | PEL260050 | skrip-lane |
| BB0160 | Topi | PEL260052 | skrip-lane |
| BB0163 | Improver | BB260013 | skrip-lane |
| BB0168 | Dough Croissant | PJ260010 | csv-stok |
| BB0171 | Box Gempi (Isi 100 pcs) | PEL260069 | csv-stok |
| BB0174 | TIDAK AKTIF Olesan Pastry -> Olesan Pastry (lihat aturan tanggal) | BB260046 | skrip-lane |
| BB0183 | 'Memory Card'        -> MMC CCTV (128 GB) | PEL260058 | skrip-lane |
| BB0185 | Botol Spray | PEL260010 | skrip-lane |
| BB0191 | Kertas Thermal | PEL260075 | skrip-lane |
| BB0199 | 'USB Adapter' | PEL260060 | skrip-lane |
| BB0217 | 'CCTV Outlet' | PEL260056 | skrip-lane |
| BB0220 | Sapu Outlet | PEL260037 | skrip-lane (keputusan user 13 Okt)† |
| BB0226 | Buku Tulis | ATK260044 | skrip-lane (keputusan user 13 Okt)† |
| BB0228 | Keset | PEL260020 | skrip-lane (keputusan user 13 Okt)† |
| BB0229 | Lap Microfiber | PEL260025 | skrip-lane (keputusan user 13 Okt)† |
| BB0230 | Sticker Label Tom & Jerry | ATK260038 | skrip-lane (keputusan user 13 Okt)† |
| BB0231 | Spidol | ATK260043 | skrip-lane (keputusan user 13 Okt)† |
| BB0234 | Penggaris Merah | ATK260027 | skrip-lane (keputusan user 13 Okt)† |
| BB0237 | Freezer | PER260008 | skrip-lane |
| BB0238 | 'Alat Kasir'         -> Mesin Kasir POS | PEL260057 | skrip-lane |
| BB0257 | Gelas Cup 9 Oz (Isi 50 pcs) | PEL260071 | csv-stok |
| BB0260 | Bill Holder | PEL260009 | skrip-lane (keputusan user 13 Okt)† |
| BB0261 | Dough Gempi | PJ260011 | csv-stok |
| BB0262 | 'Orbit Outlet'       -> Modem WiFi Outlet | PEL260059 | skrip-lane |
| BB0263 | Pulpen Outlet | ATK260041 | skrip-lane (keputusan user 13 Okt)† |
| BB0264 | Isi Staples | ATK260046 | skrip-lane (keputusan user 13 Okt)† |
| BB0267 | Tinta Isi Ulang Outlet | BHP260033 | skrip-lane (keputusan user 13 Okt)† |
| BB0268 | Dispenser Sabun Cair | PEL260014 | skrip-lane (keputusan user 13 Okt)† |
| BB0270 | Kuas Silikon | PEL260023 | skrip-lane |
| BB0272 | Spons Cuci Outlet | PEL260045 | skrip-lane (keputusan user 13 Okt)† |
| BB0273 | Sabun Lantai Outlet | BHP260035 | skrip-lane (keputusan user 13 Okt)† |
| BB0274 | Sabun Cuci Outlet | BHP260034 | skrip-lane (keputusan user 13 Okt)† |
| BB0277 | Meja Loyang Stainless | PER260011 | skrip-lane |
| BB0278 | Meja Rak Oven | PER260012 | skrip-lane |
| BB0279 | Meja Booth Outlet | PEL260064 | skrip-lane |
| BB0280 | Etalase Outlet | PER260006 | skrip-lane |
| BB0283 | Papan Menu Oultet | PEL260030 | skrip-lane (keputusan user 13 Okt)† |
| BB0284 | Poster Dinding | PEL260061 | skrip-lane |
| BB0285 | Neon Box Bulat Outlet | PER260013 | skrip-lane |
| BB0289 | Oven 1 Deck 2 Tray | PER260016 | skrip-lane |
| BB0291 | Panel 3 Phase | PER260004 | skrip-lane |
| BB0293 | Stand Booth Outlet | PEL260062 | skrip-lane |
| BB0294 | Huruf Dan Logo Timbul Ropi | PER260010 | skrip-lane |
| BB0296 | Plastik Cup Isi 1 | PEL260078 | skrip-lane |
| BB0297 | Plastik Cup Isi 2 | PEL260079 | skrip-lane |
| BB0298 | Gelas 14 Oz (Isi 150 pcs) | PEL260070 | csv-stok |
| BB0301 | Bubuk Beras Kencur | BB260034 | csv-stok |
| BB0304 | Bubuk Susu Jahe | BB260037 | skrip-lane |
| BB0305 | Gula Cair Sachet (Isi 100 Sachet) | BB260038 | csv-stok |
| BB0307 | Mika Display | PEL260028 | skrip-lane (keputusan user 13 Okt)† |
| BB0308 | Bubuk Hepi Drink Moccacino (30 Gr) | BB260057 | csv-stok |
| BB0309 | Bubuk Hepi Drink Cappucino (30 Gr) | BB260058 | csv-stok |
| BB0310 | Bubuk Hepi Drink Kopi Karamel (30 Gr) | BB260059 | csv-stok |
| BB0311 | Bubuk Hepi Drink Chocolate | BB260060 | csv-stok |
| BB0312 | Air Mineral Outlet 600 ml | PJ260009 | csv-stok |
| BB0322 | Kopi Hitam @6gr (Isi 20 Sachet) | BB260061 | csv-stok |
| BB0323 | Meja Minum Outlet | PEL260065 | skrip-lane |
| BB0328 | Jilbab Outlet | SG260012 | skrip-lane |
| BB0329 | Jasmine Green Tea 750g | BB260030 | csv-stok |
| BB0340 | Coffee Latte 500g | BB260031 | csv-stok |
| BB0341 | Coffee Classic 120g | BB260032 | csv-stok |
| BB0342 | Dark Cocoa Drink 1Kg | BB260033 | csv-stok |
| BB0345 | Coffeemate 450g | BB260050 | csv-stok |
| BB0346 | Milo Activ 960g | BB260052 | csv-stok |
| BB0347 | Teh Tarik 960g | BB260054 | csv-stok |
| BB0349 | Lemonade 640g | BB260051 | csv-stok |
| BB0351 | Kemoceng | PEL260095 | skrip-lane (keputusan user 13 Okt)† |
| BB0352 | Olesan Pastry 250g | BB260046 | skrip-lane |
| BB0353 | Gula Cair 250g | BB26009 | skrip-lane |
| BC01 | Black Coffee | BC002 | csv:bukti-harga+acc |
| BC02 | Es Kopi Hitam | BC001 | csv:acc-user |
| BCN01 | Black Coffee Nota | BC002 | csv:cocok |
| BCN02 | Americano Ice Nota | BC001 | csv:tebakan |
| CK01 | Es Coklat | CK001 | csv:acc-user |
| CK02 | Coklat Panas | CK002 | csv:bukti-harga+acc |
| CKN01 | Chocolate Ice Nota | CK001 | csv:cocok |
| CKN02 | Chocolate Hot Nota | CK002 | csv:acc-user |
| CP01 | Cappucino | CP001 | csv:bukti-harga+acc |
| CPN01 | Cappucino Hot Nota | CP002 | csv:cocok |
| CPN02 | Cappucino Ice Nota | CP001 | csv:cocok |
| CR01 | Croissant Original | CR001 | csv:acc-user |
| CR02 | Croissant (nota) | CR001 | csv:tebakan |
| P0001 | Roti Ropi Butter (FRC) | RP002 | csv:gabung-frc |
| P0002 | Roti Ropi Keju (FRC) | RP003 | csv:gabung-frc |
| P0004 | Roti Ropi Coklat (FRC) | RP001 | csv:gabung-frc |
| P0010 | Extra Keju | ADD26-001 | csv:tebakan |
| P0011 | Gempi Choco Crunchy (FRC) | GM005 | csv:tebakan |
| P0012 | Gempi Dark Choco (FRC) | GM003 | csv:tebakan |
| P0013 | Gempi Original | GM001 | csv:acc-user |
| P0017 | Gempi Tiramisu (FRC) | GM004 | csv:tebakan |
| PG001 | Roti Gempi Original (FRC) | GM001 | csv:tebakan |
| PG002 | Roti Gempi Choco Crunchy (FRC) | GM005 | csv:acc-user |
| PG003 | Roti Gempi Dark Choco (FRC) | GM003 | csv:acc-user |
| PG004 | Roti Gempi Tiramisu (FRC) | GM004 | csv:acc-user |
| PKG001 | Plastik Seal Roti | PEL260083 | csv:keputusan-user |
| PKG01 | Goodie Bag | PEL260072 | csv:acc-user |
| PR00033 | Promo Hemat 3 | PAKET26-003 | csv:acc-user-promo-hemat |
| PR00034 | Promo Hemat 4 | PAKET26-006 | csv:acc-user-promo-hemat |
| PR00037 | Promo Hemat 1 | PAKET26-004 | csv:acc-user-promo-hemat |
| PR00038 | Box Ropi isi 20 pcs | PAKET26-002 | csv:acc-user |
| PR00039 | Paket Goodiebag 6 Roti | PAKET010926-005 | csv:keputusan-user |
| PR00072 | Hemat 2 | PAKET26-005 | csv:acc-user |
| PR00073 | Hemat 3 | PAKET26-003 | csv:acc-user |
| PR00074 | Hemat 4 | PAKET26-006 | csv:acc-user |
| PR00075 | Hemat 1 | PAKET26-004 | csv:acc-user |
| PR001 | Ropi Butter | RP001 | csv:cocok |
| PR00140 | Hemat 3 (nota) | PAKET26-003 | csv:tebakan |
| PR00141 | Hemat 4 (nota) | PAKET26-006 | csv:tebakan |
| PR00142 | Hemat 1 (nota) | PAKET26-004 | csv:tebakan |
| PR00143 | Hemat 2 (nota) | PAKET26-005 | csv:tebakan |
| PR002 | Ropi Coklat | RP002 | csv:cocok |
| PR003 | Ropi Keju | RP003 | csv:cocok |
| RR0001 | Ropi Butter (stok outlet) | PJO2603 | csv-stok |
| RR0002 | Ropi Coklat (stok outlet) | PJO2601 | csv-stok |
| RR0003 | Ropi Keju (stok outlet) | PJO2602 | csv-stok |
| RR0008 | Roti Croissant (stok outlet) | PJO2605 | csv-stok |
| RR0009 | Roti Gempi (stok outlet) | PJO2604 | csv-stok |
| TJ01 | Hot Tea | JT001 | csv:acc-user |
| TJ02 | Ice Tea | JT002 | csv:acc-user |
| TJN01 | Ice Tea Nota | JT001 | csv:cocok |
| TJN02 | Hot Tea Nota | JT002 | csv:cocok |
| TR01 | Beras Kencur | TR001 | csv:acc-user |
| TR03 | Kunir Asem | TR003 | csv:acc-user |

## SKU yang SENGAJA TIDAK dimapping (skip, jangan ditebak)

| SKU | Nama eResto | Alasan |
|---|---|---|
| BB0052 | Dough Srikaya | tidak ada padanan, stok 0 |
| BB0053 | Dough Tiramisu | tidak ada padanan |
| BB0054 | Dough Vanilla | tidak ada padanan |
| BB0101 | Olesan Blueberry | tidak ada padanan |
| BB0106 | — | item tidak aktif |
| BB0107 | Olesan Sarikaya | tidak ada padanan |
| BB0108 | — | item tidak aktif |
| BB0043 | Daun Teh Enak Kata Orang | belum ada padanan di BARU; hanya muncul di PO FRC Pasaman |
| RR0004 | Ropi Tiramisu | tidak ada padanan |
| RR0010 | Teh Enak Seduh | tidak ada padanan |

SKU lain yang muncul baru di eResto (outlet/tipe baru) = otomatis belum
termap → masuk sheet `Skipped` laporan migrasi dgn alasan, lalu diputuskan
di sini (tambah baris + sumber bukti/keputusan user).

## Riwayat keputusan mapping

| Tanggal | Keputusan |
|---|---|
| 2026-10-05 | ACC 24 SKU varian (tabel `acc-user*`, `bukti-harga+acc` di atas); 19 SKU butuh item baru |
| 2026-10-09 | Goodie Bag kanonik = PEL260072; PG001 legacy di-merge & dihapus |
| 2026-10-12 | Olesan Pastry: BB0174/BB0352 → BB26012 utk PO > 2026-10-08 (≤ → BB260046) |
| 2026-10-13 | 28 SKU keperluan outlet dimapping (BB0263→ATK260041, BB0131→PEL260038, BB0136→PEL260041, BB0082→BHP260023, BB0087→BHP260020, BB0230→ATK260038, BB0267→BHP260033, sisanya bukti nama master BARU/stok csv); BB0080→PEL260074 & BB0117→PEL260077 ditambah juga ke lane SO FRC |

## Jejak turunan (agar tidak kehilangan sync)

ITEM_MAP aktif yang menyalin tabel ini:
- `pos_sync/migrate_po_juri_9_12_okt.py` (74 SKU — lane PO outlet→JURI)
- `pos_sync/migrate_so_frc_9_12_okt.py` (11 SKU — lane SO FRC)
- `pos_sync/migrate_po_juri_eksternal_9_12_okt.py` (32 SKU — PO eksternal)
- `pos_sync/migrate_po_gudang_jakarta_9okt.py`, `migrate_po_eresto_8_9_okt.py`,
  `migrate_po_selogiri_9okt.py` (lane harian; salinan lama, masih konsisten)

CSV lama (masih ada sebagai arsip, bukan sumber kebenaran):
- `experiments/sku_to_item_code.csv` (51 SKU — subset POS, tanpa SKU BB/RR stok)
- `experiments/stok_sku_to_item.csv` (47 SKU — subset stok outlet)

Jika tabel ini dan salinan skrip/CSV beda → **tabel ini yang benar**;
perbaiki salinannya.

---

# Bagian referensi (dipertahankan dari dokumen lama)

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
- **SELESAI 2026-10-09**: BB0066 Goodie Bag -> **`PEL260072` "Goodie Bag"**
  (keputusan user). Item legacy `PG001` "Goodie Bag 6 Roti" sudah
  **DI-MERGE** ke `PEL260072` (semua referensi transaksi ikut pindah) dan
  dihapus dari sistem; `POS Package` "Paket Goodiebag 6 ROPI" juga sudah
  memakai `PEL260072`. Jangan pakai `PG001` lagi.
- Jebakan teknis: Item doctype site ini ber-naming series
  `BB26-.###` yang menimpa `item_code` saat create; item harus
  di-`frappe.client.rename_doc` setelah dibuat agar kode konsisten.
  Sudah ditangani di `create_stok_items.py`.
