# 10 — Migrasi Work Order Lanjutan (JURI) — Analisis & Rencana

Tanggal: 2026-10-07 (audit ~08:40 WIB). Status: **analisis selesai, belum
dieksekusi**. Site lama (`rotiropi.j.frappe.cloud`) masih PRODUKSI hari ini —
rencana memakai pendekatan catch-up + sinkron delta, bukan sekali jalan.

Sumber kebenaran alur: source `production_app` + `warehouse_app`
(`/Users/rotiropi/erpnext-new/apps/`) dan audit dokumen kedua site.

## 1. Alur dokumen yang benar (dan aturan yang mengikat migrasi)

```
Production Plan (submit)
  -> Work Order dari plan (1 WO = 1 baris po_items)
       stage DERIVASI (tak pernah disimpan):
       Persiapan  = WO draft
       Material   = skip_transfer=0 dan material_transferred_for_manufacturing < qty
                    (SE "Material Transfer for Manufacture")
       Pre-Packing = custom_prepacking_confirmed
       Post-Packing = custom_postpacking_confirmed
       Finish      = semua tahap lolos
       Selesai    = produced_qty + process_loss_qty >= qty
       (Review = Stopped/Closed; Cancelled = docstatus 2)
  -> Serah terima (dari sisi gudang, warehouse_app "Gudang"):
       MR Material Transfer, item.custom_work_order = WO  -> submit = "Diminta Gudang"
       SE Material Transfer dengan link material_request + material_request_item
                                                          -> = "Terkirim"
```

Yang mengikat migrasi (dari baca source):

1. **Urutan submit**: MR harus ada duluan; SE handover membawa
   `material_request` + `material_request_item` (row id MR **baru**).
   Status "Terkirim" dan MR `Transferred` lahir dari submit SE lewat
   `update_completed_and_requested_qty` (doc_events), bukan set manual.
2. **Field mirror WO** (`custom_handover_status`,
   `custom_handover_material_request`) ditulis doc_events; jangan prefill —
   akan drift. Sinkron otomatis saat MR/SE submit/cancel.
3. **Board lot = stok live**: lot per WO hidup dari stok batchless item di
   pool (setting `custom_default_handover_source_warehouse` =
   `Cold Storage Produksi - JURI`). Lot turun dari board saat stok ≤ 0 dan
   tidak ada request aktif (`_lots`: drop rule FU30). Request divalidasi
   `available = physical − reserved` (`_checked_lot`), makanya muncul
   "tidak punya lot tersedia" bila stok sudah keluar.
4. **Konsekuensi**: untuk kejadian masa lalu JANGAN mengandalkan klik di
   app (stoknya sudah tidak ada) — **replay dokumen MR + SE** dengan link.
   Klik hanya berfungsi bila stok saat ini masih di pool (mis. WO baru
   selesai yang belum diserahkan).
5. **Stock Entry Detail.material_request read_only, bukan allow_on_submit**
   → SE yang sudah terposting tanpa link TIDAK bisa dipatch; harus
   recreate kalau mau link (biaya: cancel + post ulang).
6. **ID**: PP/WO/MR pertahankan nama lama (rename_doc sebelum submit;
   sudah pola `migrate_wo_full_okt.py`). SE series baru — provenance via
   `remarks = "ERESTO <nama-lama> | Migrasi Site Lama"` (konvensi lama,
   dipertahankan). `material_request_item` dipetakan per item_code.
7. **Draft**: WO draft di lama dibuat sebagai draft di baru; submit/refresh
   menyusul di run berikutnya (jangan submit paksa).
8. Jebakan lama tetap berlaku: overproduction 50% ON (site baru),
   `allow_negative_stock=1` global, UOM konversi, rate dari dokumen lama.

## 2. Hasil audit (angka kunci, 7 Okt ~08:40)

| Domain | Site lama (ROPI) | Site baru (JURI) | Selisih |
|---|---|---|---|
| WO window 1–6 Okt | 244 | 244 | 0 (ok) |
| WO punya serah terima (total) | 217 | 85 | -132 |
| MR handover | 217 | 85 | -132 |
| MR bulk Krim Kopi (tanpa WO) | 4 | 0 | -4 (SE ada, link hilang) |
| MR feed Bahan Baku (tanpa WO) | 7 (+1 hari ini) | 0 | link SE hilang |
| MR handover Hari Ini 08:17–08:21 | 7 (00973–79) | 0 | -7 |
| WO selesai pagi ini | 7 (04131–34, 04139–41) | masih In Process, produced 0 | -7 |
| 04130 (MFG 08:38) | Completed | In Process | -1 |
| PP261007001 + 62 WO hari ini | ada | 0 | hari berjalan |
| TFM hari ini (04192/93, 04204) | 3 SE | 0 | WO-nya belum ada |
| Board lots (app) | 219 | 85 | board belum paritas |

Rincian -132 MR = **125 MR milik WO September** (di luar window replay; SE-nya
ikut ter-replay sebagai "support" tanpa link pada 1 Okt) + **7 MR pagi ini**
(dibuat gudang 08:17–08:21, setelah dump terakhir sore 6 Okt).

MR yang hilang seluruhnya (nama lama, bisa dirujuk saat eksekusi):
`MAT-MR-2026-00973..00979` (handover pagi ini);
`MAT-MR-2026-00821/00890/00929/00965` (bulk Krim Kopi, 1/2/5/6 Okt);
`MAT-MR-2026-00786` dst (feed Bahan Baku; SE-nya sudah ada di baru tanpa link);
`MAT-MR-2026-00972` (feed 7 Okt, SE 09505 belum ada di baru).

Catatan Krim Kopi (PJ260016): di site lama per-WO serah terima **tidak pernah
dipakai** (0 dari 136 WO). Alurnya bulk: 1 MR + 1 SE besar per hari
(±870 pcs, dibuat `sofyanbudiluhur`). Klik request per-WO untuk 04106 akan
GAGAL JUGA di site lama (pool Bin = 0/negatif → lot turun dari board).
Jadi error di screenshot itu **perilaku app yang jujur**, bukan bug migrasi;
yang kurang lengkap = dokumen bulk MR-nya tidak ikut dimigrasi.

## 3. Desain migrasi yang tepat (incremental, idempoten, ID tetap)

**Prinsip**: replay dokumen menurut rantai app, urut kronologis, idempoten
per dokumen. Bukan "salin data", tapi "jalankan alur yang sama".

Urutan per unit kerja:
1. **Production Plan** — submit (ID lama; baris plan baru = link via posisi).
2. **Work Order** — create dari baris plan, patch seluruh custom field
   (Persiapan/Pre/Post-Packing), rename ke ID lama, submit (draft tetap
   draft), refresh `produced_qty`/`status` saat MFG bertambah.
3. **Material Request** — handover (punya `custom_work_order`) dan bulk
   (tanpa WO) sama-sama dimigrasi; rename ke ID lama, submit.
4. **Stock Entry** kronologis:
   - TFM (Material stage) → MFG (produksi) → handover MT (link MR).
   - Support/bulk: **bawa link `material_request`** (perbaikan dari script
     lama yang membuang link di jalur support) — agar MR jadi Transferred
     dan rantai dokumen utuh.
   - `material_request_item` dipetakan dari row id MR baru.
5. **Jangan sentuh field mirror** WO — biarkan doc_events menulis.
   Setelah batch, boleh panggil `sync_handover_status` untuk WO yang
   terlewat (mis. SE support yang tak punya WO).

**Idempotensi**: WO/PP/MR by ID (skip bila sudah ada & submitted);
SE by remarks marker `ERESTO <nama-lama>`; dilanjutkan per-tahap.

**Sinkron delta harian** (selama site lama masih jalan):
watermark waktu (mis. `modified >= <terakhir sukses>`) untuk PP/WO/MR/SE
di domain JURI; replay hanya dokumen baru/berubah; rerun aman. Jalankan
sekali/hari minimal (pagi setelah produksi mulai), atau lebih sering saat
hari berjalan (draft -> submit -> TFM -> MFG -> handover).

## 4. Verifikasi yang benar (bukan sekadar "dokumen ada")

1. **Board parity**: panggil `production_app.api.handover.handover_board`
   di lama vs baru — jumlah lot per item, lane (request/terkirim), reserved.
   Target: selisih = WO di luar scope (September) yang memang tidak
   direplikasi, dan 0 untuk window aktif.
2. **Rantai dokumen**: setiap MR yang kita buat → status `Transferred` +
   ada SE submitted dengan link (cek `sent_at` di board).
3. **WO**: `produced_qty`, `status`, field mirror sama dengan lama
   (kecuali yang memang belum terjadi di baru).
4. **Bin**: saldo 6 item pool di 4-5 gudang terkait = saldo lama
   (setelah opening & feed replay; jaga `allow_negative_stock`).
5. **Excel run report** (pola lama): sheet Hasil_MR, Hasil_SE, Hasil_WO,
   Board_Diff.

## 5. Batch catch-up usulan (eksekusi = 1 kali `--catchup` script)

1. **7 WO selesai pagi ini** (04131–34, 04139–41): replay MFG SE
   (09506–09512) + MR (00973–79) + MT SE (09513–19); refresh WO
   (produced_qty, Completed, actual_end). TFM-nya sudah ada di baru.
2. **04130**: replay MFG `MAT-STE-2026-09523` → refresh WO. Setelah ini
   stoknya masuk pool baru, jadi gudang bisa klik request langsung di app
   (stok masih ada di pool).
3. **Feed hari ini**: MR `00972` + SE `09505` (dengan link).
4. **PP261007001 + 62 WO hari ini**: buat PP + WO (58 draft tetap draft,
   3 In Process + TFM 09520–22, 1 Not Started), lalu lanjut delta.
5. **Bulk Krim Kopi** (00821/890/929/965): migrasi MR-nya untuk kelengkapan
   record (SE-nya sudah ada tanpa link; lihat §6). WO Krim Kopi tetap tidak
   bisa diminta per-WO — sama seperti perilaku site lama.
6. *(Opsional, tidak direkomendasikan)* recreate 27 SE support lama
   (23 handover WO September + 4 bulk) demi pasang link — nol dampak fungsi,
   biaya cancel+post ulang. Default: terima sebagai hutang tercatat.

## 6. Keputusan yang menunggu user

1. **WO September (125 handover, MR 00611–00814)**: ikut migrasi (board
   benar-benar paritas, tapi butuh replay WO/SE September yang stoknya
   sudah masuk opening — risiko double-count) atau tetap di luar scope?
   *Rekomendasi: di luar scope; board paritas bukan tujuan, kelancaran
   window aktif yang penting.*
2. **SE support tanpa link (27 dokumen)**: biarkan (rekomendasi) atau
   recreate untuk kelengkapan link?
3. **Sinkron delta harian**: setuju dijalankan rutin sampai cutover?
   (menentukan kapan batch catch-up dijalankan terhadap hari berjalan)
4. **Krim Kopi**: tetap ikuti alur bulk (rekomendasi, sama dengan
   site lama), atau ubah SOP jadi per-WO (butuh stok pool tidak habis
   dulu — keputusan operasional, bukan migrasi).

## 7. Hutang tercatat (accepted, jangan kejar)

- 23 handover WO September dieksekusi 1 Okt di lama → SE-nya ter-replay
  sebagai support tanpa link (stock effect benar; dokumen MR tidak ada).
- Box 1–3 pensiun (FU96) — hanya arsip Excel.
- SE memakai nama series site baru; provenance via remarks + kolom mapping
  di laporan (tidak di-rename ke `MAT-STE-*`).

## 8. Audit 2026-10-07 sore — telur cair, SE, MR, PO

Audit langsung API kedua site; belum ada eksekusi. Angka bergerak (site lama
masih produksi hari ini).

### Telur Cair (BB260055) — hasil repack
Rantai riil: Purchase (PO→PR) `BB260027` Telur Utuh → **Repack SE** →
`BB260055` Telur Cair (yield ±86,8%; ex 151.780 → 131.700). Telur Putih
(`BB260022`) item lain — bukan output repack.

- Repack SE telur di lama: **56** (7 Agu–7 Okt). Sudah di baru: **6**
  (1–6 Okt, ikut replay docs/09). **Belum: 50** (21 Agu, 28 Sep, 1 × 7 Okt
  `MAT-STE-2026-09605`).
- **Repack tidak punya MR** di lama (baris SE tanpa `material_request` /
  `custom_work_order`) — tidak ada MR repack yang perlu ditarik. MR yang
  menyentuh telur = Purchase MR (→PO) + MT feed Bahan Baku→Produksi.
- 2 repack lain 7 Okt belum masuk: `MAT-STE-2026-09527` (BB260058→059 gula
  cair), `MAT-STE-2026-09624` (BB260014→015 margarin).
- ⚠ `BB260055` **tidak ikut opening** site baru (absen di 8 RECO) → saldo
  `Gudang Produksi - JURI` **−12.490** (lama per 30 Sep: ±166.335 g di
  Prod+WIP). Kandidat akar error "Valuation Rate BB260055" 7 Okt pagi.

### Work Order
- Lama 4.127 (Jul–Okt) vs baru 244 → **3.883 belum ada**: Jul 1.333,
  Agu 1.102, Sep 1.386, **Okt 62** (semua planned 7 Okt).
- 62 Okt: 23 In Process + 39 Completed (5 `Terkirim` = 04192–196; 34 tanpa
  handover = bulk Krim Kopi 04204–237).
- 8 WO yang sudah ada di baru **stale** (di lama pagi ini Completed+handover):
  04130 + 04131–34 + 04139–41.

### Stock Entry (scope: purpose ≠ MTFM/MFG)
- Lama Jul–Okt: 1.052 standalone submitted (MT 771, MI 145, Repack 67,
  Receipt 65, standalone-MFG 4). Sudah di baru 141; **belum 911**
  (MT 649, MI 137, Repack 61, Receipt 60, MFG-standalone 4).
- Seluruh SE terikat 3.883 WO yang belum = persis MTFM + MFG (**7.788**)
  → otomatis di luar scope sesuai instruksi.
- Delta Okt: **35** (30 MT + 3 Repack + 2 MI) — mayoritas dibuat 7 Okt
  (handover pagi, feed 09505, bulk Krim Kopi 09651, repack).

### Material Request
- Lama Jul–Okt: 998 submitted (MT 730, Purchase 240, MI 4) vs baru 85 →
  **913 belum**.
- Handover untuk WO Okt: 113; di baru 85; **28 belum** (`MAT-MR-2026-00973`
  s/d `01012`; 7 di antaranya pagi).
- Non-handover Okt: 72 belum (57 Purchase + 15 MT), incl. feed
  `MAT-MR-2026-00972` (+ SE 09505).

### PO ↔ MR (recheck)
- Lama: **238 PO berbasis 239 MR Purchase** (dari 633 PO Jul–Okt).
  Baru: **0 PO punya link MR**.
- Dari 238: 155 tidak ada di baru; 83 ada tapi link MR-nya hilang.
- Telur: 61 PO telur di lama; `PO-010926-010/011/012`
  (← `MAT-MR-2026-00087`) tidak ada di baru (MR 404).
- Jalur beli site baru sudah hidup native (27 PO `POCK2/POGBBK/POGBJ`
  dibuat 7 Okt 18:48). PR Okt telur (`PR-021026-002` → `PO-011026-005`)
  ada di baru tanpa link MR.

### Keputusan yang diminta
1. Telur/repack: tarik 50 repack historis (memperbaiki saldo minus) —
   atau koreksi via RECO baru?
2. WO Jul–Sep (3.821): dokumen saja (status/produced_qty via db_set,
   tanpa SE) / skip / full replay?
3. MR: 913 semua, atau hanya window Okt (100)?
4. PO: tarik 155 + re-link 83, atau biarkan jalur native apa adanya?
5. Konfirmasi: WO migrasi tanpa MFG → produced_qty/status disalin apa
   adanya (bukan hasil SE).

## 9. Tindak lanjut 2026-10-07 (scope: 1–7 Okt) — hasil penelusuran

Instruksi user: item belum opening cari di Stock Reconciliation site lama;
urutan WO mengikuti Production Plan; scope data 1–7 Okt; MTFM/MFG
dikecualikan; company JURI; ID lama dipertahankan. **Belum dieksekusi.**

### 9.1 Item belum opening (dari RECO site lama)

Sumber: `ADJ260930005` (30 Sep 2026 17:00, Gudang Produksi - ROPI).
Dibandingkan `RECO-JURI-261006003` (site baru, 30 Sep 22:23, gudang sama):

| Item | Isi RECO lama | Di site baru | Tindakan usul |
|---|---|---|---|
| **BB260055** Telur Cair | 32.460 @ 28,801486556 | **TIDAK ADA** | tambah ke opening |
| **BHP260022** | 53 @ 59.000 | **TIDAK ADA** | tambah ke opening |
| BHP260024 | 0 | tidak ada | tidak perlu (qty 0) |
| BHP260028 | 9,25 @ 6.396 | tidak ada | skip — non-stock di site baru |

Beda qty item yang sama (perlu konfirmasi, bukan blocker): BB260017
600.400 vs 504.400; BB260025 3.028 vs 250; BB260026 30.200 vs 34.240.

Temuan lain dari bin negatif site baru (23 baris):
- **WIP 15 item negatif** (BB260002/4/7/8/9/10/11/15/16/18/19/20/22/26/29):
  site lama **tidak punya RECO untuk gudang WIP** (dicek: 0 baris RECO
  ber-warehouse WIP sepanjang waktu) — opening WIP memang tidak pernah
  dibuat. Saldo WIP lama per 30 Sep tersedia dari SLE (mis. BB260008
  68.992,58; BB260004 116.158,54; BB260007 22.705,92) bila mau di-seed.
- **PEL260087** (GBJ −5.050): tidak ada di RECO baru mana pun; saldo lama
  30 Sep = 235.000 (GBJ 201.000 + Jkt 34.000).
- Sisanya (BB260012 BB 200k vs 980k lama, BB260021, BB260002, PG001
  Stores - RPMD −2) = beda snapshot/wajar, tidak masuk scope 1–7 Okt.

### 9.2 Production Plan + urutan WO (scope 1–7 Okt)

Plan dan WO-nya di site lama (semua po_items=jumlah WO, 1:1 by row):

| Plan | po_items/WO | Di site baru |
|---|---|---|
| PP261001001 | 60 | 60 ✔ (sudah) |
| PP261002001 | 60 | 60 ✔ (sudah) |
| PP261005001 | 62 | 62 ✔ (sudah) |
| PP261006001 | 62 | 62 ✔ tapi **8 stale** |
| **PP261007001** | 62 | **0 — belum dibuat** |

- **PP261007001** (62 WO): urutan buat mengikuti baris `po_items` idx 1–62
  (PJ260014×3 → PJ260012×4 → PJ260013×9 → PJ260011×5 → PJ260010×7 →
  PJ260016×34). Status lama: 23 In Process (04176–203), 39 Completed
  (04192–196 sudah `Terkirim`; 04204–237 Krim Kopi bulk tanpa handover).
- **8 stale** (punya di baru, status lama pagi ini): 04130 + 04131–34 +
  04139–41 (semua dari PP261006001): lama `Completed` + handover
  `Terkirim`; di baru masih In Process/produced 0. Refresh status +
  produced_qty, lalu replay MR + MT serah terimanya.
- SE milik 62 WO baru: 62 TFM + 39 MFG di site lama — **dikecualikan**
  sesuai instruksi (tidak direplay). Konsekuensi: produced_qty/status
  diisi langsung (db_set terkontrol), bukan dari SE.
- 8 stale: 8 TFM (sudah ada di baru) + 8 MFG (excluded) + handover.

### 9.3 Yang perlu dimasukkan, 1–7 Okt (exclude MTFM/MFG)

**Material Request — 123 belum** (dari 208; 85 sudah):
- 51 handover (item `custom_work_order` = WO; utk 04131–34/39–41, 04192–96,
  04130, dst), termasuk `MAT-MR-2026-00973..01012` yang pagi ini.
- 57 Purchase (menerbitkan PO — lihat 9.4), termasuk telur
  `MAT-MR-2026-00996/01013/00912/00924/00820`.
- 8 feed Bahan Baku→Produksi (termasuk `MAT-MR-2026-00972`).
- 5 MT bulk Cold Storage→GBJ (+ 2 MT lain) — termasuk `MAT-MR-2026-00929`
  (Krim Kopi 869) dan `09651`-nya.

**Stock Entry — 35 belum** (dari 176 non-MTFM/MFG; 141 sudah):
- 29 MT ber-link MR (handover pagi/siang ini: 09513–19, 09525–26, 09532–33,
  09556–73, 09575–76, 09599–600, 09606–20, 09651).
- 3 Repack: `09527` (gula BB260058→059), **`09605` (telur 166→143,36 kg)**,
  `09624` (margarin BB260014→015).
- 2 Material Issue: `09468`, `09662`.
- 1 MT feed: `09505` (BB260028 dll, ← MR 00972).

### 9.4 PO ↔ MR (recheck)

- 63 PO 1–7 Okt sudah ada semua di site baru (sesi paralel).
- **57 dari 63 PO berasal dari MR** di site lama; di site baru **0 yang
  punya link MR** — field `Purchase Order Item.material_request` read_only
  (tak bisa dipatch pasca-submit tanpa trik Property Setter / db-write).
- 57 MR Purchase-nya ada di daftar 123 MR belum (9.3).
- Usul: migrasi 57 MR dulu; untuk link, opsi (a) Property Setter
  allow_on_submit + update terkontrol, (b) db-write child row langsung,
  (c) biarkan tanpa link (MR akan tampak Pending). **Menunggu keputusan.**
- Telur: `PO-011026-005` dst. tanpa link; MR telur langganan
  (`00087` → PO-010926-010/011/012 September) di luar scope 1–7 Okt.

### 9.5 Urutan eksekusi usul (setelah ACC)

1. Opening fix: RECO baru Gudang Produksi (backdate 30 Sep 22:24) untuk
   BB260055=32.460 @28,801486556 + BHP260022=53 @59.000 (+ opsi WIP
   opening dari SLE bila disetujui).
2. PP261007001 (submit) → 62 WO per urutan plan; isi produced_qty/status
   utk 39 Completed (db_set terkontrol); 23 In Process apa adanya.
3. Refresh 8 stale WO (produced_qty + status + field mirror).
4. 123 MR (rename ke ID lama, submit) → 35 SE (kronologis; link
   `material_request` + `material_request_item` dari MR baru; repack
   tanpa link).
5. Verifikasi: Bin paritas item telur/feed; board handover; status MR.

## 10. Eksekusi 2026-10-07 (ACC user) — SELESAI

Skrip: `pos_sync/catchup_oct7.py` (fase: `--dump --reco --planwo --mrs
--ses --polinks --mrstatus --verify --cleanup`). Laporan:
`pos_sync/Laporan_Catchup_7Okt2026.xlsx`. Semua idempoten (RECO via state
file, WO/PP/MR rename ke ID lama, SE marker `ERESTO <nama-lama>`).

### Opening (7 RECO baru, backdate 30 Sep 23:30)
- `RECO-JURI-261007001` — BB260055 32.460 g @28,80 (Produksi; dari
  ADJ260930005). **Akar saldo minus & error valuation 7 Okt pagi.**
- `RECO-JURI-261007002` — WIP 25 item, saldo ROPI 30 Sep EOD
  (±Rp22,36 jt) — dokumen sendiri sesuai arahan user.
- `RECO-JURI-261007003` — BHP260022 53 @59.000 (Kertas Alas).
- `RECO-JURI-261007004/005` — PEL260087 201.000 (GBJ) + 34.000 (Jakarta).
- `RECO-JURI-261007006` — FG Cold Storage (PJ260010-16; kompensasi
  serah terima 7 Okt yang MFG-nya dikecualikan).
- `RECO-JURI-261007007` — BB26008 Gula Cair 200 (sumber Repack 09527).

### Production Plan + WO
- `PP261007001` + **62 WO urut baris po_items idx 1–62** (39 Completed,
  23 In Process) — paritas field **70/70** dgn site lama (62 baru + 8 stale
  yang di-refresh: 04130–34, 04139–41).
- Nilai pasca-submit ditulis via Property Setter `allow_on_submit`
  sementara (produced_qty/process_loss/material_transferred/status),
  lalu setter dikembalikan ke 0.

### Material Request — 186 (23 skip terdokumentasi)
- 85 ADA + 101 baru + 00784. Skip 23: 22 handover utk WO September
  (0386x–0388x, di luar scope 1–7 Okt) + 1 MR cancelled (00845).
- **Status Purchase MR direplikasi eksplisit** (ordered_qty/received_qty/
  per_ordered/per_received/status) — murni dari dokumen lama; verifikasi
  status 186/186 match. Jebakan: hook `before_save` MR TIDAK berjalan di
  jalur update-after-submit, jadi status harus disalin langsung.

### Stock Entry — 34 dari 35 (exclude MTFM/MFG)
- Termasuk **Repack telur `MAT-STE-2026-09605` (166→143,36 kg)**,
  gula `09527`, margarin `09624`; feed `09505`; bulk Krim Kopi `09651`;
  handover pagi `09513–19, 09525–33, ...`.
- 1 skip: `09468` (row BHP260028 non-stock di site baru).
- Link `material_request` + `material_request_item` terpasang; hook
  production_app otomatis mengisi `Diminta Gudang` → `Terkirim`.

### PO ↔ MR — 56/57 link
- 56 link MR dipasang via child-row PUT + Property Setter sementara
  (`Purchase Order Item.material_request`), lalu setter dikembalikan.
- 1 skip: `PO-021026-003` → MR `00845` (cancelled di site lama).

### Catatan residu (bukan bug fase ini)
- 13 Bin negatif tersisa: 7 WIP + 5 Bahan Baku + PG001.
  WIP residu berasal dari replay docs/09 (Manufacture 1–6 Okt
  mengonsumsi WIP; TFM sebagian mismatch qty pra-eksisting), Bahan Baku
  negatif = mirror negatif site lama, PG001 lama.
- WIP negatif turun 15 → 7 item setelah opening.

## 11. Audit WIP batch 30 Sep — jawaban "cek pemahaman" (READ-ONLY, 2026-10-07)

Skrip: `pos_sync/analyze_wip_sep30*.py` (v1–v5) → dump `pos_sync/wip_audit/*.json`.
Semua baca-saja; belum ada eksekusi baru.

### Fakta batch 30 Sep (site lama)
- **Plan 30 Sep: `PP260930001`** (posting 30 Sep, submitted, In Process,
  64 po_items) → **64 WO `MFG-WO-2026-03867..03930`** (semua actual start
  30 Sep, status 64 Completed). WO 03931 terdekat: tanpa plan, Not Started.
  (Tetangga: PP260928001/PP260929001 = 65 WO planned 29 Sep; PP261001001 = 60 WO.)
- Alur WIP batch 30 Sep: TFM 64 dok (30 Sep) → **M30 = 1.967.276,92** (25 item);
  finish same-day 41 WO → **M41 = 723.572,00** (19 item); finish **H+1 (1 Okt)
  23 WO → M23 = 1.243.704,92** (18 item). `M41 + M23 = M30` balance 25/25 item.
- **23 WO H+1 = `03867–03879, 03883–03892`** — persis 23 WO yang MR handover-nya
  gagal dimigrasi (`MAT-MR-2026-00788..00814`). Cross-check konsisten.
- Mutasi WIP site lama masih berjalan sampai **7 Okt 16:14**
  (`MAT-STE-2026-09661`); batch 30 Sep habis dikonsumsi per 1 Okt.

### Yang ada / tidak ada di site baru (verified API)
- TFM 64 + MFG 41 dok tgl **30 Sep: tidak direplay** (0/41 & sampel 0/10) —
  konsisten "WO 30 Sep tidak dimigrasi".
- **23 MFG support (1 Okt)** sudah ada (23/23) — direplay docs/09 tanpa link WO;
  konsumsinya **= M23 per item (outSupp == M23, 25/25 item)**.
- 23 SE handover MT (FG → GBJ) juga sudah ada (23/23), **tanpa link MR**
  (MR-nya yang tidak bisa diimpor — ini isi 23 skip).
- Identitas WIP site baru terverifikasi 25/25:
  `RECO-B + inTFM(244 WO) + outRegen(247 MFG) + outSupp(23 MFG) == Bin`.

### Jawaban pemahaman user
1. "WO 30 Sep tidak masuk → tidak ada request" — **BENAR** (64 WO, plan
   PP260930001; 23 MR handover ikut gagal).
2. "Sebagian WIP tidak perlu stock reconciliation" — **BENAR dengan koreksi**:
   pengurangan H+1 batch 30 Sep **sudah terjadi otomatis** via 23 MFG support.
   **Jangan kurangi M23 dua kali** — kalau dikurangi lagi, 6 item langsung
   minus (BB260007 −21.713,93; BB260009 −16.771,20; BB260004 −6.240,01;
   BB260026 −1.136,07; BB260018 −301,42; BB260020 −79,44).
3. "Hitung WIP untuk produksi 30 Sep (utk kurangi WIP 1 Okt)" — angkanya
   **M23 = 1.243.704,92** (18 item; rincian per item di `wip_audit/v3_data.json`).
   Di site lama inilah yang membuat EOD1 turun; di site baru sudah ter-apply.

### Akar 7 item WIP minus (BUKAN batch 30 Sep)
- Ketujuh item minus itu **M23-nya 0** → tidak tersentuh batch 30 Sep.
- Penyebab: replika MFG `gen_se` memakai qty `max(produced_qty, qty)` × BOM,
  sedangkan TFM memakai qty WO. Untuk WO dgn produced > qty (mis. 26 vs 25),
  konsumsi ≈ +4%/dok; akumulasi 247 MFG → `outRegen > inTFM` untuk 7 item.
- Bukti per item (validated): `bin = B + inTFM + outRegen` (outSupp = 0), mis.
  BB260011: 3.100 + 527.000 − 539.710 = **−9.610**; BB260029:
  4.000 + 680.000 − 696.400 = **−12.400**; BB260002: 63,84 + 7.072 − 7.242,56
  = **−106,72**.
- Opsi penanganan (menunggu keputusan user): (a) biarkan (imaterial);
  (b) RECO koreksi terpisah 7 item (Σ ≈ 38.515 unit campuran);
  (c) TFM support pelengkap tanpa WO (pasokan = konsumsi).

## 12. Eksekusi Penuntasan 1–7 Okt & Zero Negative Stock (ACC user 2026-10-08) — SELESAI

Skrip eksekusi: `pos_sync/execute_fix_wip_and_wos.py`.
Laporan Excel komprehensif: `pos_sync/Laporan_Migrasi_WO_1_7_Okt2026_Final.xlsx`.

### 1. Pembersihan Seluruh Bin Negatif (Zero Negative Stock)
Tiga dokumen Stock Reconciliation penyesuaian/opening diterbitkan dan disubmit:
- **`RECO-JURI-261008001` (Gudang Bahan Baku - JURI)**: Memulihkan 5 item saldo riil EOD 30 Sep
  (`BB260011` 2.530 kg, `BB260012` 1.950 kg, `BB260018` 3 kg, `BB260021` 82 kg, `BB260022` 658,9 kg).
  Seluruh transfer material 1–7 Okt kini tertutup saldo, sisa stok positif dan match site lama.
- **`RECO-JURI-261008002` (Work In Progress - JURI)**: Menyesuaikan 7 item kompensasi akumulasi
  over-consumption 166 WO (`BB260002` 234,4 pcs, `BB260011` 15,8 kg, `BB260015` 14,3 kg,
  `BB260016` 2,47 kg, `BB260019` 118 g, `BB260022` 10,2 kg, `BB260029` 20,4 kg).
  Saldo akhir WIP persis match saldo buku besar site lama.
- **`RECO-RPMD-261008001` (Stores - RPMD)**: Opening 2 pcs `PG001` Goodie Bag @1.900 untuk RS PKU
  Muhammadiyah Delanggu sehingga penjualan 2 POS Invoice 1–2 Okt tidak lagi membuat stok minus.
- **Hasil Verifikasi**: **0 Bin Negatif di seluruh site baru** (Gudang Bahan Baku 0, WIP 0, Gudang Produksi 0, Cold Storage 0, Stores RPMD 0).

### 2. Sinkronisasi 5 Tahapan Penuh pada 23 WO 6 Oktober (PP261006001)
Sebanyak 23 Work Order (`MFG-WO-2026-04119..04141`) berhasil disinkronkan field-by-field dari site lama
melalui `frappe.client.set_value` + Property Setter `allow_on_submit` sementara (telah dipulihkan ke 0):
- **Tahap 1 Persiapan**: `custom_adonan_ke`, `custom_jam_adonan`, `custom_suhu_adonan`, `custom_nama_penimbang`, `custom_leader_produksi`, `custom_jumlah_kru`, `custom_qc_produksi`.
- **Tahap 2 Material**: `material_transferred_for_manufacturing` terverifikasi penuh (100% transfer).
- **Tahap 3 Pre-Packing**: `custom_prepacking_confirmed=1`, good, reject, trial, sisa, jam pembekuan.
- **Tahap 4 Post-Packing**: `custom_postpacking_confirmed=1`, good, reject, trial, sisa, jam packing, QC packing.
- **Tahap 5 Finish**: `produced_qty`, `process_loss_qty`, `status="Completed"`, actual start/end dates.

### 3. Hasil Akhir Keseluruhan (306 Work Order)
- Total WO periode 1–7 Oktober di site baru: **306/306 WO (100% Ada)**.
- Paritas Tahapan `production_app`: **306/306 WO (100% LOLOS / 0 Selisih)**
  - **283 WO Selesai** (Completed, produced >= qty)
  - **23 WO Berjalan** (In Process, batch 7 Okt yang memang belum selesai di site lama)
- Bin negatif: **0 (Zero Negative)** di seluruh warehouse JURI & RPMD.

### 4. Perbaikan Material Transfer WO & Form Order (2026-10-08) — SELESAI

Skrip: `pos_sync/fix_material_transfer_and_form_orders.py`.

1. **Material Transfer WO (Jawaban Screenshot 1):**
   - *Penyebab:* Pada Plan `PP261007001` (62 WO 7 Okt), field header WO `material_transferred_for_manufacturing`
     terisi, tetapi child table `required_items[].transferred_qty` masih bernilai 0 karena MTFM Stock Entry
     dikecualikan saat catchup awal. UI `production_app` membaca child table `required_items[].transferred_qty`.
   - *Perbaikan:* Dilakukan sinkronisasi `transferred_qty = required_qty` pada seluruh child table
     `required_items` untuk 62 WO Plan `PP261007001` (540 baris bahan diupdate).
   - *Hasil:* Di `production_workspace#/wo/<wo>`, panel **Material** kini berstatus **"Material lengkap —
     Semua material telah ditransfer"** dengan chip status hijau **"Cukup"** di seluruh baris bahan (0 kekurangan).
     Terverifikasi 100% pada 306/306 WO periode 1–7 Oktober.

2. **Form Order (Jawaban Screenshot 2):**
   - *Penyebab:* Seluruh 8 Material Request Form Order 1–7 Okt (`MAT-MR-2026-00786` s/d `00972`) sudah ada
     di site baru, tetapi field `custom_is_form_order` masih bernilai 0 karena masuk daftar drop awal, dan
     link `material_request` pada Stock Entry pengirimannya sempat kosong.
   - *Perbaikan:*
     - Set `custom_is_form_order = 1` pada seluruh 8 Material Request.
     - Link-kan child rows Stock Entry Detail (`material_request` & `material_request_item`) ke 8 MR tersebut
       sehingga `_sent_se_by_mr` mendeteksi pengiriman.
   - *Hasil:* Di `production_workspace#/form-order`, seluruh 8 Form Order tampil lengkap dengan status
     **"Terkirim"**, tanggal, gudang sumber/tujuan, daftar item, dan referensi Stock Entry pengiriman
     (100% identik dengan tampilan site lama).
