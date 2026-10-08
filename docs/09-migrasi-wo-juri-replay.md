# Migrasi Work Order Pabrik JURI 1–6 Okt 2026 (replay alur production_app)

244 Work Order pabrik `PT. JUARA ROTI INDONESIA` (Krim Kopi + 5 varian Dough)
direplay penuh dari site lama `rotiropi.j.frappe.cloud` ke site baru
`ropierpnext.frappe.cloud` **menurut alur riil production_app + warehouse_app**
— bukan sekadar salin field. Kode: `pos_sync/migrate_wo_full_okt.py`
(dump → plans → wos → mrs → ses → verify; semua idempoten + `pos_sync/wo_dump/*.json`).

## Alur yang ditiru (hasil bedah app)

```
Production Plan ──(1 WO per baris plan)──> Work Order (draft→submit)
   │
   ├─ Persiapan   : field custom di WO (adonan_ke, jam/suhu adonan, penimbang, kru, leader)
   ├─ Material    : SE "Material Transfer for Manufacture"  (GBB/GP → WIP)
   ├─ Pre-Packing : custom_good/reject/trial/sisa + custom_prepacking_confirmed=1
   ├─ Post-Packing: custom_*_postpacking + custom_postpacking_confirmed=1
   ├─ Finish      : SE "Manufacture" (WIP → Cold Storage)  ⇒ produced_qty/loss/status Completed
   └─ Selesai     : derive_stage() = selesai saat produced+loss >= qty (turunan, bukan aksi)
Gudang minta barang ──> Material Request (Material Transfer, custom_work_order)
   ⇒ hook production_app otomatis set WO.custom_handover_status = "Diminta Gudang"
Produksi serahkan  ──> SE Material Transfer dari MR  ⇒ hook set "Terkirim"
```

- **Box 1–3 sudah dipensiunkan** di production_app (FU96) & warehouse_app (kolom
  Serah Terima dihapus) → migrasi **tidak menulis** field box; nilai lama hanya
  diarsipkan di sheet `Arsip_Box_Lama`.
- `derive_stage` (production_app/api/work_order.py) murni turunan data — tidak ada
  aksi tambahan yang perlu dipanggil; state app otomatis konsisten.

## Hasil akhir (100% LOLOS, 0 selisih)

| Metrik | Nilai |
|---|---|
| Production Plan (ID lama dipertahankan) | **4** (`PP261001001/002/005/006`, submitted) |
| Work Order (ID lama, dari plan) | **244/244** — 221 Completed + 23 In Process (6 Okt berjalan, persis sumber) |
| Field custom produksi vs lama | 244/244 identik (adonan, QC, prepacking, postpacking) |
| Σ produced_qty | **81.620 = 81.620** (lama) |
| Material Request serah terima | **85** (ID lama; hook app mengisi `Diminta Gudang`) |
| SE serah terima | **85** submitted (hook → `Terkirim`; 0 manual set) |
| Stock Entry direplay | **629** submitted: 244 TFM + 244 Manufacture + 122 MT (85 serah terima + 37 pengumpan/transfer lain) + 8 Issue + 6 Repack + 5 Receipt |
| Verifikasi | `Laporan_Migrasi_WO_1_6_Okt2026.xlsx` — Hasil_WO **244 LOLOS / 0 selisih** (status, qty, produced, loss, transfer, actual start/end, MR, handover, jumlah SE per WO) |

Catatan replay SE: 2 dokumen lama tidak direplay — 1 Manufacture ber-`docstatus=2`
(batal, memang bukan bukti) dan 1 Material Issue yang **semua itemnya non-stock
di site baru** (tanpa efek ledger). Keduanya tercatat.

## Keputusan & jebakan yang ditemukan

- **ID dokumen**: Plan, WO, dan MR serah-terima identik dengan site lama via
  `Property Setter allow_rename=1` + `frappe.client.rename_doc` (form-encoded).
  Nama SE mengikuti seri site baru; nomor SE lama tercatat di `remarks`
  (`ERESTO <nama-lama>`) + sheet `SE_Mapping` (idempotency marker).
- **Custom Field tidak ikut meta DocType REST**: `fetch_meta` membaca child
  `fields` DocType yang **tidak memuat Custom Field** → semua `custom_*`
  terbuang diam-diam saat insert (WO jadi 0 semua). Fix: merge
  `/api/resource/Custom Field?filters=[["dt","=",...]]` ke meta. Tanpa ini
  Work Order "kosong" walau status/qty benar.
- **UOM di SE lama**: qty memakai UOM transaksi (30 zak = 750.000 g,
  `stock_qty` null di API) → replay harus mengalikan `conversion_factor` ke
  stock UOM; UOM `Kg` dipetakan ke `kg` (site baru huruf kecil).
- **Nama gudang**: `Gudang RnD - ROPI` → `Gudang R&D - JURI` (bukan sekadar
  akhiran - ROPI→- JURI; ada gudang khusus tanpa sufiks).
- **Item non-stock beda antar site**: `BHP260028` stock di lama, non-stock di
  baru — baris dilewati (Stock Entry tidak boleh memuat non-stock).
- **Valuation rate**: saat gudang sumber kosong di site baru (opening belum
  lengkap), ERPNext menolak TFM → rate diambil dari `basic_rate` SE lama +
  `allow_zero_valuation_rate` untuk baris yang tetap kosong.
- **Backdate**: `set_posting_time=1` + `allow_negative_stock=1` global (sudah
  menyala di site baru untuk fase migrasi) → submit tanggal historis lolos
  walau saldo antar-waktu bisa minus sementara. Saldo akhir tetap dipandu
  rekonsiliasi terpisah.
- **Salin field via `pick()`**: `operations`/`required_items` dikosongkan saat
  insert → ERPNext mengekspansi sendiri dari BOM aktif site baru
  (`BOM-PJ26xxxx-001`), sesuai keputusan "BOM site baru = acuan benar".

## Selisih saldo stok yang tersisa (bukan bug migrasi)

Spot-check Bin akhir vs site lama masih beda di beberapa pasangan karena
sumber-sumber di luar scope migrasi ini: (a) dasar opening stock site baru =
opname eResto (RECO-JURI-261006001..008), bukan buku besar lama; (b) Purchase
Receipt 2–6 Okt (lane pembelian) belum dimigrasi — persis penyebab selisih
besar BB260028/BB260011 dll di Gudang Bahan Baku; (c) 1 SE non-stock dilewati.
Paritas penuh menunggu lane PR/pembelian direplay.

## Rerun & upgrade parsial

- Rerun aman: `--plans`/`--wos`/`--mrs` skip dokumen yang sudah ada; `--ses`
  melewati SE ber-marker yang sudah submitted (0 duplikat; terbukti dari
  rerun kedua: "marker existing 628, job baru 1").
- 23 WO 6 Okt yang masih `In Process` di lama nanti bila selesai: cukup
  `--ses` lagi — SE Manufacture yang baru akan tersusul tanpa menyentuh yang
  lama (WO-nya sudah ada, tidak dibuat ulang).
