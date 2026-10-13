# Lengkapi item_defaults per company outlet — ERPNext BARU (CLOUD)

Site: `https://ropierpnext.frappe.cloud`. Skrip: `pos_sync/lengkapi_item_defaults_semua.py`
(dry-run default, `--execute`, `--company`, `--item`). Backup per item:
`audit_logs/item_defaults_261013_133320/` (uji 1 item) + `audit_logs/item_defaults_261013_133329/` (196 item).

## Scope
- Company target: 165 (semua kecuali 7 FRC + 5 grup: JURI GROUP, OUTLET, TRAINING,
  Outlet Pameran, PT. JUARA ROTI INDONESIA). **PT. JURI ditunda** — CoA-nya tidak punya akun 5220.0xx.
- Item: 261 item aktif grup Inventories dengan coverage ≥150 company.
  31 item hanya pabrik (0 PO outlet) **dilewati** (`JURI_ONLY`): 29 Bahan Baku
  (Butter, Tepung, Gula, Filling, Margarine, Telur, Susu, Ragi, dll.) + PJ260008 Krim Kopi 700 g
  + PJ260015 Dubai Dough. Baris outlet yang kosong pada item ini dibiarkan (4.929 baris).

## Aturan akun (keputusan user)
| Kelompok | Akun |
|---|---|
| Item yang sudah punya akun | akun terbanyak (mode) item itu, ganti suffix abbr |
| Bahan Baku yang dipesan outlet (28: Olesan, Bubuk minuman, Keju, Meises, Gula Stik/Cair, Plastik Krim, dll.) | `4210.000 - HPP Pembelian` |
| Produk Jadi Pabrik (7: Dough ×5, Krim Kopi, Air Mineral Outlet) | `4210.000 - HPP Pembelian` |
| Peralatan (17) + 13 Perlengkapan aset (Cash Drawer, Mesin Kasir POS, CCTV, Modem, Teko, Dispenser, Meja/Stand Booth, Meja Minum, Standing Display, Poster, Bill Holder, Alat Test Uang) | `1211.004 - Aktiva Tetap - Mesin & Peralatan` |
| Paper Bag, Plastik Alas Gempi, Seragam/Sepatu Pabrik SG260005-011 | `5220.016 - Biaya Perlengkapan Outlet` |

Baris baru: akun di atas + `Stores - <ABBR>` + `default_inventory_account` (mode item tsb).

## Hasil
- 12.948 baris ditulis di 197 item (11.766 akun kosong diisi + 1.182 baris baru untuk
  RSMS, RSPY, RSUKJ, RRSC, RFB, RSUPP). Item Default total 48.772 → 49.954.
- Verifikasi live: 230 item × 165 company → 0 baris hilang, 0 akun kosong,
  0 akun suffix salah, 0 duplikat (company, item). Rerun dry-run = 0 perubahan.
- Susulan (`FILL_ONLY`): 5 baris outlet item coverage kecil diisi tanpa membuat baris outlet lain —
  BB260061 Kopi Hitam (RPMD) → 4210.000; PEL260072 Goodie Bag & PEL260097 Balon Orange
  (RPMD, RQLY) → 5220.016. Backup `audit_logs/item_defaults_261013_141711/`.

## Temuan, belum disentuh
- 14 item tidak seragam: ATK260002/006/007/010/016/017/019/024/029/030/034 (5130.005 di 159
  company) dan BHP260020/034/035 (5220.011) tercatat `5220.016` di 6 company baru
  (+LBSM/RSMMP utk ATK260029/BHP260020) — efek skrip BHP 14 Okt.
- PT. JURI: 217 baris akun kosong + 83 item tanpa baris.
- JURI punya 2 akun bernomor 5130.010: `Biaya Perlengkapan Gudang` dan
  `Biaya Perlengkapan Pabrik` (tanpa account_number, dipakai 11 baris BHP).
