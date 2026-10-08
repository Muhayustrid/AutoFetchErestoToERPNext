# Alur barang Ropi: dough → matang → bundle jual

Sumber: data produksi eResto (Kebumen `045.xxxxx`, Majenang `120.xxxxx`,
1–4 Okt 2026) + master ERPNext lokal.
Dokumen ini pengetahuan tetap — berlaku untuk **semua** keluarga produk
dough (Ropi Butter/Coklat/Keju, Gempi, Croissant). Jangan diubah tanpa
verifikasi ulang dari data.

## Tiga tingkat barang

Satu roti melewati tiga tingkat sebelum sampai ke pembeli. Nama berbeda
di tiap sistem, tapi barangnya sama.

| Tingkat | Dibuat oleh | Nama eResto | Contoh eResto | Nama ERPNext | Contoh ERPNext |
|---|---|---|---|---|---|
| 1. Dough | Pabrik (kirim ke outlet) | `Dough ...` (semi finished) | `BB0046` Dough Butter | `Produk Jadi Pabrik` | `PJ260012` Dough Ropi Butter |
| 2. Matang | Outlet, sesi "Masak" | `RR....` (finished good) | `RR0001` Ropi Butter | `Produk Jadi Outlet` | `PJO2603` Ropi Butter Matang |
| 3. Bundle jual | Outlet, saat jual | produk POS | `PR001` Ropi Butter | bundle (`Products`) | `RP001` = PJO2603 + paper bag |

Artinya: **yang dijual ke customer bukan dough dan bukan matang polos,
tapi bundle** = 1 matang + kemasan (paper bag / box / olesan). Matang
hanya barang antara di dapur outlet — **satu-satunya pengecualian:
Dubai Dough Salt Butter, yang justru dijual dalam bentuk dough**
(lihat bawah).

## Tabel lengkap (semua keluarga dough)

| Dough (Pabrik) | eResto | Matang (Outlet) | eResto | Bundle jual | Isi bundle |
|---|---|---|---|---|---|
| `PJ260012` Dough Ropi Butter | `BB0046` | `PJO2603` Ropi Butter Matang | `RR0001` | `RP001` | PJO2603 + `PEL260076` Paper Bag |
| `PJ260013` Dough Ropi Coklat | `BB0047` | `PJO2601` Ropi Coklat Matang | `RR0002` | `RP002` | PJO2601 + PEL260076 |
| `PJ260014` Dough Ropi Keju | `BB0049` | `PJO2602` Ropi Keju Matang | `RR0003` | `RP003` | PJO2602 + PEL260076 |
| `PJ260011` Dough Gempi | `BB0261` | `PJO2604` Gempi Matang | `RR0009` | `GM001` | PJO2604 + `PEL260069` Box Gempi |
| `PJ260010` Dough Croissant | `BB0168` | `PJO2605` Croissant Matang | `RR0008` | `CR001` | PJO2605 + PEL260076 |
| `PJ260015` Dubai Dough Salt Butter | belum terlihat di sampel | — tidak ada — | — | **dijual sebagai dough** | **pengecualian**: tanpa tahap matang & tanpa bundle |

**Pengecualian — Dubai Dough Salt Butter (`PJ260015`).** Dijual dalam
bentuk dough (konfirmasi user 2026-10-04): tidak dimasak outlet, tidak
melewati tahap matang, tidak dibungkus jadi bundle. Jangan buatkan
item PJO/padanan untuknya dan jangan harap ada output matang di data
produksi. SKU eResto-nya belum muncul di data yang kita pegang
(3 outlet-hari POS + SO Monthly September) — lengkapi saat produk ini
muncul/tersinkron.

Varian Gempi rasa (Dark Choco/Tiramisu/Choco Crunchy) memakai matang
yang sama (`PJO2604`) + olesan: `GM003` = PJO2604 + `BB260044` 45 g +
box; `GM004` = PJO2604 + `BB260047` 45 g + box; `GM005` = PJO2604 +
`BB260043` 60 g + box.

Dough yang belum punya padanan ERPNext (skip per keputusan
2026-10-04): `BB0052` Srikaya, `BB0053` Tiramisu, `BB0054` Vanilla
(eResto stok 0), dan 'Teh Enak Seduh' bukan roti.

## Resep produksi (terukur dari data, bukan asumsi)

Dari sesi produksi Kebumen + Majenang (1–4 Okt 2026):

- **1 pack dough Ropi (Butter/Coklat/Keju) → 12 pcs matang**. Terukur
  konsisten lintas sesi: 4 pack butter → 48, 9 pack coklat → 108,
  5 pack keju → 60 (Kebumen); 1 pack → 12 (Majenang). Baris krim
  `BB0085` ikut keluar di sesi yang sama, tapi atribusi per-produknya
  belum terpisah di stock card — jangan pakai angkanya dulu.
- **1 pack dough Gempi → 3 pcs matang** (+ gula sachet; atribusi
  belum terpisah). Contoh: 2 pack → 6 Roti Gempi.
- **1 pack dough Croissant → 6 pcs matang**. Contoh: 2 pack → 12
  croissant.

Rasio yield (12/3/6) yang dipakai untuk desain; angka bahan
pendamping (krim/gula) menunggu probe resep resmi sebelum jadi BOM.

## Jejak di API eResto

- `GET /v2/productions` — daftar sesi "Masak" per outlet
  (`division_id`, `production_number` `045.DDMMYY.NNNNNN`).
- `GET /v2/stock_cards?division_id=...` — mutasi stok. Baris produksi:
  - `reference_type = Production` → barang **keluar** hasil masak
    (matang masuk, `stock_in > 0`), `reference.production_number`.
  - `reference_type = ProductionResultItem` → **bahan terpakai**
    (dough/krim/gula keluar, `stock_out > 0`).
- `GET /v2/productions/{id}` — header + `transaction_group` jurnal
  otomatis: **Dr Persediaan Finished Good (`1 1 03 03`), Cr
  Persediaan Semi Finished (`1 1 03 02`)** per produk, nilai HPP per
  sesi (contoh: 3 produk = 3 pasang baris Dr/Cr).
- Stok berjalan per outlet: `/v2/inventories` → `division_inventories[]`.

## Implikasi migrasi

- Seed stok outlet dari SO Monthly September memakai tingkat 1
  (dough) dan tingkat 2 (matang) **terpisah** — keduanya punya saldo
  di outlet. Bundle tidak punya saldo (non-stok).
- Jual Ropi di ERPNext otomatis memotong stok PJO (matang) + kemasan
  lewat Product Bundle — sudah terbukti di pilot `PINV-TJBK-261004001`.
  Karena itu stok matang harus terisi dari produksi, bukan dijual
  dari nol.
- Sinkron produksi (fase berikutnya) = Stock Entry per sesi masak:
  konsumsi PJ+BB, hasil PJO, mengikuti resep di atas.
- Jurnal eResto (Dr Finished / Cr Semi Finished) adalah referensi
  rekonsiliasi saat membandingkan hasil posting ERPNext.
- **Riwayat perbaikan:** bundle `GM001` sempat berisi dirinya sendiri
  (`GM001` + box) — diperbaiki 2026-10-04 menjadi `PJO2604` + box,
  konsisten dengan pola semua bundle lain.
