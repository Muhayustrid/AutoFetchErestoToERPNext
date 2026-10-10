# docs/12 — Konsolidasi Stock Reconciliation JURI (Opening 30 Sep 23:00)

> Instruksi user 2026-10-09: "benerin stock reconciliation, akun yang dipakai
> salah — penyesuaian harusnya akun penyesuaian, opening pakai pembukaan
> sementara. Banyak cancelan — benerin dan jadiin satu aja. Opening semua,
> kejadiannya 30 September 2026, dibikin per gudang, misalnya jam 23:00."
> Scope: **PT. JUARA ROTI INDONESIA saja**. Dough di Gudang Barang Jadi
> ("kejadiannya setelah 30 September") **TIDAK diotak-atik** dulu.

## Aturan kanonik

| Jenis | Purpose | Akun | Waktu |
|---|---|---|---|
| Opening (saldo awal) | `Opening Stock` | `1171.000 - Pembukaan sementara - <abbr>` | 2026-09-30 23:00:00 (satu dokumen per gudang) |
| Penyesuaian operasional | `Stock Reconciliation` | `5110.020 - Penyesuaian Stock - <abbr>` | hari berjalan / per kasus |

Sebelum konsolidasi: 42 dokumen RECO JURI aktif, 31 di antaranya opening
tersebar jam 11:00–23:59 (3 dok bertanggal 2 Okt), dan 7 dokumen penyesuaian
salah akun (1171, harusnya 5110).

## Tooling

`pos_sync/konsolidasi_opening_reco.py`:

- `--plan` (default, read-only) → `reco_consolidate_plan.json` + ringkasan
  (per gudang: baris opening, posisi yang nilainya berubah, prediksi blokir
  validasi v16).
- `--execute [--warehouses "A,B"] [--sr7-only] [--enable-negative-window]`:
  cancel dok lama → submit opening gabungan per gudang → verifikasi → poll
  repost. Gate: kalau subset butuh flag dan flag tidak diberikan → STOP.
- `--cleanup [--execute-cleanup]`: hapus permanen dok RECO cancelled JURI
  (prosedur resmi: backup → purge Print Log → `delete_linked_ledger_entries=1`
  sementara → delete → restore → cek ledger/Bin).
- `--report` → `Laporan_Konsolidasi_Opening_RECO.xlsx`.

State: `reco_consolidate_state.json` (snapshot pra, cancelled, created,
sr7 map, noop, subst). Idempoten per fase.

`pos_sync/restore_sr7_zeroouts.py` — substitusi Material Receipt untuk
dokumen zero-out yang tak bisa di-recreate tanpa flag.

## Jebakan utama (terbukti live)

1. **Cancel RECO v16 menggeser trail** (`update_qty_in_future_sle`): shift
   `-qty` diterapkan ke semua baris SLE setelah timestamp dokumen, dibatasi
   "RECO berikutnya" yang masih visible. Urutan cancel harus **ascending
   creation**.
2. **Zero-out `qty=0` di atas saldo minus tak bisa di-recreate** dengan
   `allow_negative_stock=0` → `NegativeStockError` (validasi anchor).
   Jalan keluar tanpa flag: **SE Material Receipt** dengan qty = |saldo
   minus| dan rate sama (Bin → 0, GL setara, akun 5110). Contoh:
   `RECO-JURI-261009030` → `SE-MR-261009002`; `261009031` → `SE-MR-261009003`.
3. **Dokumen no-op** (mis. `RECO-JURI-261009029`, 22 baris qty 0 rate 0
   yang tak mengubah apa pun) → server menolak recreate
   (`EmptyStockReconciliationItemsError`); biarkan cancelled + hapus.
4. Trail SLE menyimpan **2.521 baris minus historis** (fase migrasi).
   Validasi v16 memindai ke depan dari timestamp dokumen, jadi cancel dok
   lama yang menyentuh posisi tersebut bisa memunculkan kembali minus.
   Verifikasi pasca-aksi: scan `qty_after_transaction < 0` (bukan hanya Bin).

## Hasil 2026-10-09

- 7 gudang aman dikonsolidasi **tanpa flag**: GIT, WIP Testing, GA, R&D,
  Testing Manufacture, Vendor, Mini Outlet (dok baru `RECO-JURI-261009042..048`).
- 4 dari 7 dokumen akun-salah beres: `026→049` (5110), `030→SE-MR-261009002`,
  `031→SE-MR-261009003`, `033→050` (5110); `029` no-op (dihapus).
- **Warehouse testing DIHAPUS (instruksi user 2026-10-09):** `Gudang Testing
  Manufacture - JURI` & `WIP Testing - JURI` (BARU) + `Gudang Finished Goods
  Testing` / `Gudang Testing Manufacture` / `WIP Testing` (`- ROPI`, LAMA)
  dihapus permanen — opening testing `RECO-JURI-261009043/046` ikut terhapus
  (`pos_sync/hapus_warehouse_testing.py`). Karena itu konsolidasi kini tinggal
  **12 gudang**; `RECO-JURI-261009042/044/045/047/048` tetap berlaku untuk
  gudang non-testing.
- **Sisa 7 gudang** (GBB, GBJ, Jakarta, Outlet, Peralatan, Produksi, WIP)
  + SR7 `032`/`034` **butuh `--enable-negative-window`** (validasi native
  v16 + riwayat minus historis) — menunggu izin user. Sisa cancelled dibuang
  lewat `--cleanup` setelah eksekusi penuh.
- Verifikasi tiap langkah: trail > 30 Sep identik, checkpoint 23:00 sesuai
  rencana, Bin 0 selisih, dok cancelled dihapus permanen (ledger 0).
