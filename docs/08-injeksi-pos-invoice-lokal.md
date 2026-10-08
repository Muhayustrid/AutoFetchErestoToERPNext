# Injeksi POS Invoice lokal (eResto 1–5 Okt 2026)

Data eResto 1–5 Okt 2026 diinjeksi ke **site lokal** `erp.localhost:8081`
sebagai POS Invoice + POS Opening Shift + POS Closing Shift per outlet-hari,
memakai jalur resmi POSNext. Semua tanggal posting = tanggal eResto asli.
Kode: `pos_sync/inject_pos_invoice.py` + `pos_sync/set_item_valuation.py`.

## Hasil akhir (semua cek LOLOS)

| Metrik | Nilai |
|---|---|
| Order eResto 1–5 Okt (list fresh 2026-10-05 20:47) | 38.852 |
| POS Invoice submitted | **38.168** (0 gagal; 38.168 dicek ulang dari DB) |
| Outlet-hari (Opening + Closing) | **553** |
| Omzet terinjeksi | **Rp992.613.000** = Σ eResto (selisih 0; dicocokkan ulang dari DB) |
| Skip | 684 order, Rp11.641.000 |
| Cek otomatis | posting_date = tanggal eResto (38.168 dicek, 0 beda); Σ Rp = Σ eResto; closing selisih 0 (553/553); GL balance 0 (sample 30) |

Breakdown per hari (sheet `Rekap_Harian`; identik dengan hitungan ulang dari DB):

| Tanggal | Invoice | Outlet | Omzet |
|---|---|---|---|
| 2026-10-01 | 9.275 | 135 | Rp243.007.000 |
| 2026-10-02 | 9.184 | 135 | Rp243.856.000 |
| 2026-10-03 | 7.724 | 134 | Rp203.227.000 |
| 2026-10-04 | 681 | 14 | Rp18.351.000 |
| 2026-10-05 | 11.304 | 135 | Rp284.172.000 |

Catatan data eResto (bukan bug injeksi):

- 4 Okt tipis (728 order, 14 outlet, semua cap `local_time` 20:xx) —
  isi eResto memang begitu.
- 5 Okt mengalir sepanjang hari: tarikan 11:55 = 5.511 order,
  tarikan ulang 20:47 = 11.484 (+5.973 order siang–malam).

Kategori skip (semuanya dilaporkan di sheet `Skipped`, tidak ditebak):

| Alasan | Order | Omzet | Catatan |
|---|---|---|---|
| `TANPA_ITEM_BAYAR` | 401 | Rp0 | order void/OC tanpa baris bayar |
| `SKU_UNMAPPED` | 222 | Rp8.203.000 | 19 SKU butuh item baru: CM01/MC01/MC02/MC05/MC06, CP02, CM02, CM06, CR03, AIR03, P0005, P0014–P0016, PR00045, GD001, SK001/SK002, SU001 |
| `OUTLET_TANPA_COMPANY` | 47 | Rp1.108.000 | `RS RIDHOKA SALMA CIKARANG` (outlet baru 5 Okt, company belum dibuat) |
| `TOTAL_BEDA` | 10 | Rp2.294.000 | `payment.total` ≠ jumlah baris item (DP/koreksi eResto) |
| `TOTAL_NOL` | 4 | Rp0 | total 0 |

## Tiga fase injeksi (keputusan mapping + data mengalir)

1. **Fase 1 — mapping awal (list cache 11:55):** 29.919 invoice /
   550 outlet-hari; skip 2.960 (SKU_UNMAPPED 2.603, dst).
2. **Fase 2 — setelah 24 SKU di-ACC + patch diskon:** rencana 32.315 →
   2.392 invoice baru disubmit (29.923 sudah ada); skip turun ke 564.
3. **Fase 3 — `--refresh-list` (tarikan ulang 20:47):** rencana 38.168 →
   5.826 invoice baru disubmit (32.342 sudah ada); skip 684. Data 5 Okt
   siang–malam hanya masuk di fase ini.

Total akhir di DB: **38.168 invoice** submitted (0 draft baru).
Rerun aman: marker `remarks = "ERESTO <order_no>"`, tidak pernah duplikat.

## Alur per outlet-hari (mengikuti POSNext)

1. **POS Opening Shift** dibuat lewat REST + submit, `period_start_date` dan
   `posting_date` = tanggal eResto (historis, 00:00:00). Empat baris
   `balance_details` (Cash/QRIS/Debit/Credit, amount 0).
2. **POS Invoice** per `order_no` lewat lane **backdate HO resmi**
   `pos_next.api.backdate_invoices.submit_backdate_invoice` — satu panggilan
   = draft + submit, server menetapkan `posting_date` + `posting_time` dari
   `date` eResto (jam asli order supaya urutan SLE benar).
3. **POS Closing Shift** dibangun dari rekap server
   (`pos_next.api.shifts.get_closing_shift_data`), `posting_date` = tanggal
   shift, `closing_amount = expected_amount` (selisih 0). Submit lewat REST.
4. Idempotency rerun: marker `remarks = "ERESTO <order_no>"` (sejajar migrasi
   1–2 Okt); shift dideteksi dari (company, posting_date, user). Invoice yang
   sudah ada dihitung `ADA` dan tidak diduplikasi.

## Jebakan yang ditemukan (dan solusinya)

- **Satu user = satu shift terbuka** (aturan POSNext `create_opening_shift`).
  Karena itu grup outlet-hari diproses **berurutan**; invoice di dalam satu
  grup boleh paralel.
- **Backdate lane butuh flag**: `POS Next Global Settings.allow_change_posting_date=1`
  (juga dibaca `reopen_shift`). Script menyalakan sebelum run dan
  memulihkan setelahnya (kecuali `--keep-flags`).
- **Stok outlet kosong → butuh `allow_negative_stock`** (Stock Settings,
  dipetakan dari setting global POSNext). Hanya untuk site lokal.
- **Valuation rate wajib saat stok 0**: ERPNext menolak POS Invoice tanpa
  valuation rate bila gudang belum punya SLE; `allow_zero_valuation_rate`
  di baris POS Invoice **diabaikan** ERPNext (hanya dikenali untuk Sales
  Invoice/Stock Entry dll). Solusi: `set_item_valuation.py` mengisi
  `Item.valuation_rate` dari SLE non-nol terakhir **site lama** (nilai
  akuntansi asli), fallback lokal; 2 item tanpa riwayat diisi asumsi yang
  dicatat di skrip (AM001 = harga jual; PJO2601 = sejajar PJO2602).
- **Diskon di bawah harga list**: baris dengan `rate` < `price_list_rate`
  server dikirim dengan `price_list_rate` + `discount_amount` +
  `discount_percentage` eksplisit + `discount_confirmation_code` (kode
  aktif `Z86BKK3D`) supaya tidak jatuh ke gate "manual rate edit" (SEC-04).
  `Planner.server_price` menghormati masa berlaku Item Price
  (valid_from/valid_upto) per tanggal posting, mirror `_fetch_uom_prices_map`.
- **Race `tabSeries` saat paralel**: beberapa invoice dalam satu series
  (`PINV-<abbr>-<yymmdd>.###`) yang submit bersamaan memicu
  `MySQLdb.OperationalError (1020) Record has changed since last read`.
  Solusi: retry **serial** (2 ronde) untuk invoice yang gagal per grup.
- **`reopen_shift`** dipakai untuk shift yang sudah tertutup tapi masih
  punya order eResto baru (mis. shift pilot TJBK 4 Okt) — cancel closing →
  inject sisanya → close ulang (rekap server menghitung ulang semua).
- **Data hari berjalan masih mengalir**: jalankan ulang dengan
  `--refresh-list` agar list eResto ditarik fresh; hanya invoice yang belum
  ada yang disubmit (sisanya `ADA`).

## Jalankan

```
cd AutoFetchErestoToERPNext
.venv/bin/python pos_sync/set_item_valuation.py        # sekali (nilai fallback)
.venv/bin/python pos_sync/inject_pos_invoice.py \
    --date-from 2026-10-01 --date-to 2026-10-05 [--refresh-list] \
    [--dry-run] [--limit-groups N]
```

Output: `pos_sync/PosInvoice_Lokal_<from>_sd_<to>.xlsx`
(sheet `Rekap_Harian`, `Rekap_Outlet`, `Shift`, `Raw_Invoice`, `Skipped`,
`Validation`) + `pos_sync/pos_invoice_state.json` (resume).

Env: `/tmp/eresto_mig.env` — `ERPNEXT_URL`/`ERPNEXT_API_KEY` (lokal),
`ERESTO_TOKEN`/`ERESTO_EMAIL`/`ERESTO_USER_ID` (hanya bila perlu tarik list
baru), `ERPNEXT_OLD_API_KEY` (site lama, untuk valuation).

## Cek verifikasi (otomatis di akhir run)

- `posting_date` invoice = tanggal eResto asli.
- Σ grand_total invoice = Σ total eResto untuk order yang diinjeksi.
- Semua closing `difference` = 0.
- GL balance 0 per invoice (sample).

## Catatan FRC (perlu keputusan)

- Keputusan docs/02 "outlet FRC tidak ikut injeksi" baru diterapkan di
  jalur **JE agregat** (27 JE `ERESTO-*` FRC masih submitted, belum
  dibatalkan). Lane **POS Invoice lokal ini masih memuat outlet FRC**:
  554 invoice / Rp18.351.000 (7 outlet) — termasuk dalam total di atas.
  Bila FRC harus dikecualikan juga di sini, langkahnya: cancel closing →
  cancel invoice per outlet FRC → (opsional) rerun untuk sisanya.

## Catatan

- Draft `PINV-TJBK-261005001` & shift `SHIFT 2` milik user (uji UI) tidak
  disentuh; 10 opening shift uji `med-sec.*` (RPMD) juga dibiarkan.
- Invoice pilot lama `PINV-TJBK-261004001` (order OR045.031026.000001,
  posting 4 Okt padahal order 3 Okt) sudah **dibatalkan** (1 baris
  cancelled di DB); order-nya diinjeksi ulang di grup TJBK 3 Okt.
- Dokumen cancelled (docstatus 2) tidak dihitung sebagai marker saat rerun.
- 24 SKU hasil ACC user 2026-10-05 (docs/02) sudah dipakai run ini.
