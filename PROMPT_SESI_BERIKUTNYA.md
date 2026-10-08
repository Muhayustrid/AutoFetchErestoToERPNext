# Prompt Sesi Berikutnya — eResto → ERPNext

> Tempelkan isi file ini (atau sebutkan path-nya) di awal sesi baru.
> Sesi baru WAJIB membaca `AGENTS.md` lalu `PROJECT_STATE.md` dulu;
> file ini merangkum sesi 2026-10-04 (siang–malam): pilot invoice,
> stok opname, mapping stok, dan pengetahuan rantai dough.

## Status terkini (akhir 2026-10-04)

- Fase: **setup lokal + pilot transaksi terbukti**. ERPNext lokal jalan
  (Docker, port 8081, site `erp.localhost`); eResto tetap live/stock truth.
- Kredensial HANYA via env `/tmp/eresto_mig.env`
  (`ERESTO_TOKEN/EMAIL/USER_ID`, `ERPNEXT_URL/API_KEY`). Jangan pernah
  tulis token ke file repo; kalau env hilang/token mati, minta user.
- 322 POS Profile, 16 Price Group, 2 Shift Group sudah siap sejak sesi lalu.

## Yang sudah terbukti sesi ini (jangan diulang dari nol)

### 1. Pilot penuh 1 order: fetch → shift → invoice → closing
- Order: `OR045.031026.000001` (TOSERBA JADI BARU KEBUMEN, 2026-10-03),
  PR001 x1 + CPN01 x2 = Rp36.000 cash. Skrip idempoten:
  `experiments/pilot_post_one.py` (kunci `remarks = ERESTO <order_no>`).
- Opening `POPEN-TJBK-261004001` → invoice `PINV-TJBK-261004001`
  (submit, 6 GL balance, 5 SLE) → closing `POCLO-TJBK-261004001`
  (Cash expected 36.000, actual 36.000, diff 0).
- Temuan penting: **item jual = Product Bundle non-stok**; `submit_invoice`
  menolak bila komponen stok kosong. Pilot pakai Stock Entry
  `SE-MR-261004001` untuk seed komponen. Produksi/bahan (PJO/dough/krim)
  belum mengalir dari eResto — itu fase berikutnya.
- `posting_date` = hari POST, bukan tanggal eResto. Backdate butuh jalur HO
  (`reopen_shift` + `submit_backdate_invoice`, role Manager + setting
  profil `allow_change_posting_date`) — BELUM dicoba.

### 2. Stok opname SO Monthly September (lengkap)
- Sumber: `/v2/stock_adjustments` (Sep 2026: 4.645 baris; 4.205
  `Auto stock balancing` DISKIP TOTAL sesuai instruksi user) →
  93 dokumen `SO Monthly September` di 91 outlet.
- Baris item ada di endpoint terpisah:
  `/v2/stock_adjustment_items?stock_adjustment_id=<id>` (detail SA hanya
  jurnal agregat). Kolom kunci: `current_quantity` (sistem),
  `real_quantity` (hasil hitung fisik = stok opname), `adjustment_*`.
  Item selisih 0 tetap termuat.
- Output: `experiments/fetch_so_monthly.py` →
  `Stock_SO_Monthly_September.xlsx` + `stock_so_monthly.json`
  (2.782 baris, checksum 93/93 OK). Cache list: `/tmp/sa_sep.json`.
- Stok live per outlet: `/v2/inventories` → `division_inventories[]`.

### 3. Mapping stok SKU → Item ERPNext (47 SKU: 39 target, 8 skip)
- Workbench: `experiments/build_stok_mapping.py` →
  `Template_Mapping_Stok.xlsx` + `stok_sku_to_item.csv`.
- **Keputusan user yang FIX:**
  - `RR0001` Ropi Butter → `PJO2603` (matang; untuk JUAL = `RP001` bundle).
    Pola: RR0002→PJO2601, RR0003→PJO2602, RR0008→PJO2605, RR0009→PJO2604.
  - `BB0046` Dough Butter → `PJ260012`; BB0047→PJ260013, BB0049→PJ260014,
    BB0168→PJ260010, BB0261→PJ260011.
  - `BB0085` Krim Kopi → `PJ260016`.
  - Bubuk tanpa padanan → **6 item baru dibuat**: `BB260057–BB260062`
    (`create_stok_items.py`).
  - Skip: Olesan Blueberry/Sarikaya, RR0004, RR0010, Dough
    Srikaya/Tiramisu/Vanilla, item TIDAK AKTIF.
- Konversi satuan: kg→g x1000; Pack→g sesuai gramasi nama (Jasmine 750,
  Latte 500, Classic 120, DarkCocoa 1000, Coffeemate 450, Milo 960,
  TehTarik 960, Lemonade 640); Pack dough→Pcs (asumsi 1:1, BELUM dikonfirmasi).
- Jebakan: Item doctype site ini ber-naming series `BB26-.###` yang menimpa
  `item_code` saat create → wajib `frappe.client.rename_doc` pasca-create
  (sudah ditangani di `create_stok_items.py`).

### 4. Pengetahuan tetap: dough → matang → bundle (docs/05)
- Dokumen: `docs/05-alur-dough-ke-bundle.md` (dirujuk AGENTS.md).
- Rantai: dough pabrik (`PJ*`/eResto `BB00xx`) → dimasak outlet sesi
  "Masak" → matang (`PJO*`/eResto `RR*`) → bundle jual (`RP*/CR*/GM*`).
- Yield terukur dari 48 sesi (Kebumen + Majenang): Ropi **1 pack dough
  → 12 pcs**, Gempi **1→3**, Croissant **1→6**. Bahan pendamping
  (Krim Kopi BB0085, Gula BB0305) belum teratribusi per produk.
- Jejak API: `/v2/productions` (daftar sesi), `/v2/stock_cards`
  (`Production` = hasil keluar, `ProductionResultItem` = bahan terpakai),
  jurnal auto eResto Dr `1 1 03 03` / Cr `1 1 03 02` = referensi rekon.
- **Pengecualian: Dubai Dough Salt Butter (`PJ260015`) dijual dalam
  bentuk dough** (kata user) — tanpa matang, tanpa bundle.
- Perbaikan: bundle `GM001` sempat berisi dirinya sendiri (GM001+box),
  sudah diganti `PJO2604` + `PEL260069`.

## Klarifikasi user (verbatim, wajib diingat)

- "produk ropi, croissant dan gempi itu pake bundle"
- "RR0001 alias ropi butter itu RP001"
- "BB0046 dough butter itu jadi PJ260012, PJO2603 itu hasil production
  dough ropi butter"
- "dubai dough salt butter memang ga ada karna dijual dalam bentuk itu"
- "SO Monthly September… yang Auto Stock Balancing diskip total ya!"
- "dough ropi butter jadi ropi butter matang trus jadi bundle ropi
  butter, itu juga terjadi pada semua dough ya!" (→ docs/05)

## Pertanyaan terbuka (tunggu keputusan user, JANGAN tebak)

1. `BB0066` Goodie Bag → `PG001` "Goodie Bag 6 Roti"? (status TEBAKAN
   di workbench stok).
2. Asumsi **1 Pack dough = 1 Pcs** untuk PJ260010–260014 — benar?
3. 64 SKU POS unmapped (MC01/MC05, AIR03, TJ02, PR00072–75,
   PG002–004, dll) — tambah item, map ke terdekat, atau skip?

## Next steps prioritas

1. Seed stok outlet dari `stock_so_monthly.json` via Stock Entry
   (setelah pertanyaan 1–2 dijawab; satu SE per outlet per SKU,
   idempotency mis. remarks `ERESTO-SO-<sa_number>`).
2. Coba jalur backdate HO → posting_date = tanggal eResto; verifikasi
   gate role + setting profil.
3. Desain & bangun `pos_sync/` produksi: Stock Entry per sesi masak
   pakai yield docs/05 (probe resep resmi dulu untuk bahan pendamping).
4. Rancang alur agregat Phase 1 (docs/03) bila user mau mulai posting
   massal; idempotency `outlet_id + date`.
5. Purchase flow: reuse transport/normalize PO CLI legacy
   (`/Users/rotiropi/Downloads/EResto_ERPNext_PO_Improved.py`), JANGAN
   pakai map lamanya.
6. Rotasi token eResto (pernah terekspos di shell/arsip) — ingatkan user.

## File kunci sesi ini

- `experiments/pilot_post_one.py` — pilot 1 order (idempoten).
- `experiments/fetch_so_monthly.py` + `Stock_SO_Monthly_September.xlsx`
  + `stock_so_monthly.json` — SO Monthly September.
- `experiments/build_stok_mapping.py` + `Template_Mapping_Stok.xlsx`
  + `stok_sku_to_item.csv` — mapping stok.
- `experiments/create_stok_items.py` — 6 item baru + fix rename.
- `docs/05-alur-dough-ke-bundle.md` — pengetahuan tetap rantai barang.
- `docs/01-eresto-api.md` — endpoint baru (stock_adjustments,
  stock_adjustment_items, inventories, stock_cards) sudah didokumentasikan.

## Aturan kerja (dari AGENTS.md, tetap berlaku)

- Baca `PROJECT_STATE.md` sebelum kerja; update + changelog tiap akhir sesi.
- Jangan sentuh `Backup SIte Production/`; jangan hardcode/print token.
- Jangan tebak Item Code — sumber: `sku_to_item_code.csv` (POS) dan
  `stok_sku_to_item.csv` (stok).
- Jangan POST/seed massal sebelum mapping disetujui user.
