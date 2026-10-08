# Prompt Sesi Berikutnya — Fix WO Outlet Multi-Level BOM (production_app)

> Tempelkan isi file ini (atau sebutkan path-nya) di awal sesi baru.
> Sesi baru WAJIB membaca `AGENTS.md` lalu `PROJECT_STATE.md` dulu.
> Konteks dokumen terkait: `docs/05-alur-dough-ke-bundle.md` (rantai barang
> tetap), `docs/09-migrasi-wo-juri-replay.md` (alur riil production_app).
> Semua fakta di bawah SUDAH diverifikasi 2026-10-07 via API cloud —
> jangan investigasi ulang dari nol; verifikasi ringan saja bila perlu.

## Masalah (apa yang terjadi)

Site produksi cloud `https://ropierpnext.frappe.cloud` (ERPNext 16 / Frappe 16,
app `production_app` + `warehouse_app` + `pos_next`). Pagi 2026-10-07, kasir
`kasir1_dlg@mail.com` (company RS PKU MUHAMMADIYAH DELANGGU) membuat WO lewat
wizard "Tambah Plan" → generate Work Order native:

- `WO-RPMD-261007001` — PJO2601 Ropi Coklat Matang ×12
- `WO-RPMD-261007002` — PJO2603 Ropi Butter Matang ×6

(source/fg warehouse = `Stores - RPMD`, wip kosong, status Not Started,
docstatus 1, belum punya transaksi apa pun). Saat menekan **Selesai**
(langkah Finish), muncul error:

> "Valuation Rate for Item BB260055 is required to do accounting entry for
> Stock Entry SE-MFG-261007001"

## Akar masalah (terverifikasi)

1. Kedua WO terbentuk dengan **`use_multi_level_bom = 1`** — default ERPNext
   (field default=1, `allow_on_submit=0`). production_app TIDAK PERNAH set 0
   (dicari di seluruh kode app: hanya file test yang set 0; `hooks.py`
   tidak punya doc_events untuk Work Order).
2. SE Manufacture buatan app (langkah Finish, `production_app/api/work_order.py`
   ~baris 1359/1436: insert+submit dalam SATU request — *"so any failure rolls
   back everything"*) ikut **meledakkan resep dough**: `BOM-PJ260013-001`
   (11 bahan, termasuk **BB260055 Telur Cair 225 g**) dan `BOM-PJ260016-001`
   Krim Kopi (7 bahan) — bukan cuma dough + Krim Kopi seperti resep WO
   (`BOM-PJO2601-002` / `BOM-PJO2603-002`).
3. Bahan adonan itu dicoba dikonsumsi dari `Stores - RPMD` — Telur Cair di
   gudang itu saldo 0 nilai Rp0, dan master item `BB260055` valuation_rate=0
   (juga last_purchase_rate=0, standard_rate=0) → ERPNext tidak bisa hitung
   rate baris keluar → throw persis error di atas.
4. **Konsep yang benar** (docs/05): resep lengkap dough (tepung, telur, dst.)
   hanya diproduksi di PABRIK (WO JURI); outlet cukup mengonsumsi dough (PJ*)
   + packaging. Migrasi kemarin aman karena skrip
   `pos_sync/inject_delanggu_work_order_production.py` set
   `use_multi_level_bom: 0` eksplisit per WO.
5. Karena submit atomik, SE yang gagal **rollback total**: tidak ada draft
   yatim (GET 404; tidak ada SE satupun hari itu). Kedua WO masih utuh.
6. JANGAN gunakan jalan pintas "Allow Zero Valuation Rate" — itu menutupi
   resep yang salah; bahan adonan memang tidak seharusnya tercatat
   dikonsumsi di outlet.

## Yang diminta (solusi + perbaikan)

1. **Usulkan & putuskan mekanisme terbaik** untuk memaksa
   `use_multi_level_bom = 0` pada WO outlet (PJO*), mis. doc_events
   `validate`/`before_save` Work Order di production_app, atau intervensi
   saat wizard membuat Production Plan. Pertimbangkan trade-off:
   - Jangan mematikan multi-level untuk WO yang memang butuh (kalau ada).
   - Solusi harus tangguh untuk WO yang dibuat lewat jalur mana pun
     (wizard app maupun form Production Plan native).
2. **Implementasikan** di source app lokal
   `/Users/rotiropi/erpnext-new/apps/production_app`, lengkap dengan test
   kecil mengikuti gaya test existing (folder `tests/`, pytest).
3. **Uji dulu di site lokal** `erp.localhost:8081` (env `/tmp/eresto_mig.env`,
   `ERPNEXT_URL` mengarah ke lokal): buat WO outlet simulasi → pastikan
   field=0 → alur SE Manufacture lolos tanpa error.
4. **Deploy ke cloud** setelah user setuju — konfirmasi dulu mekanisme deploy
   app ke frappe.cloud dengan user (ikuti pola update app yang berlaku,
   repo `Muhayustrid/POSNext` pernah disebut di changelog).
5. **Bersihkan 2 WO hari ini** di cloud (`WO-RPMD-261007001/002`): cancel +
   delete (aman — tanpa transaksi terhubung, SE-nya sudah rollback), lalu
   minta kasir (atau simulasi) mengulang alur wizard sampai Selesai sukses.
6. **Verifikasi akhir**: WO baru Completed tanpa error; SE Manufacture hanya
   mengonsumsi dough + Krim Kopi sesuai BOM WO; saldo `Stores - RPMD` wajar.

## Flag tambahan (minta keputusan user, jangan eksekusi diam-diam)

- **Stok Telur Cair `BB260055` minus 12,49 kg (−Rp323.682) di
  `Gudang Produksi - JURI`** — sisa backfill MTFM replay migrasi (transfer
  keluar tanpa penerimaan awal). Koreksi via Stock Reconciliation berdampak
  ke nilai persediaan pabrik → butuh persetujuan user.
- Master `BB260055` tidak punya valuation_rate di mana pun; selama hanya
  dikonsumsi di JURI (SLE-nya bernilai ~Rp25,9/g) aman — jangan diubah
  tanpa keputusan user.

## Aturan kerja singkat

- Kredensial: `/tmp/eresto_prod.env` (cloud; ada juga `ERPNEXT_CASHIER_API_KEY`
  kasir Delanggu) dan `/tmp/eresto_mig.env` (lokal). Jangan pernah tulis
  token ke repo/output; /tmp volatil — kalau hilang, minta user.
- Di laptop ini `urllib`/Python 3.14 gagal SSL verify ke cloud → pakai `curl`.
- Update `PROJECT_STATE.md` di akhir sesi (Status, Known issues, Changelog).
- Gaya kerja user: drive to completion — tanya hanya untuk keputusan bisnis
  (nilai persediaan, deploy ke production).
