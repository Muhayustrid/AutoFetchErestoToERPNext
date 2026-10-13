"""Revisi Olesan Pastry (keputusan user 2026-10-12, eksekusi off-hours):
DN + SO + PO intercompany: item olesan -> BB26012 (Olesan Pastry 250 g).
Company guard: PT. JUARA ROTI INDONESIA saja.
Rantai: temp MR kompensasi (deadlock 015/018) -> cancel 7 DN (desc) ->
cancel zero-out SE-MR-261009002 -> cancel+amend 2 PO (BB260060->BB26012) ->
amend 7 SO (BB260046->BB26012, remap purchase_order_item) -> rebuild 7 DN
(backdate dipertahankan, so_detail & poi diremap per idx) -> hapus DN lama &
zero-out. SO/PO lama dibiarkan cancelled (dirujuk amended_from).
Idempoten: state json + backup. Usage: python3 revisi_olesan_dn.py [--execute]
"""
import json, ssl, sys, time, urllib.request, urllib.parse, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE = os.path.join(HERE, 'revisi_olesan_state.json')
BACKUP = os.path.join(HERE, 'audit_logs', 'backup_revisi_olesan.json')
COMPANY = 'PT. JUARA ROTI INDONESIA'

env = {}
for line in open('/tmp/eresto_prod.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1)
        env[k] = v
base = env['ERPNEXT_URL']
tok = env['ERPNEXT_API_KEY']
print('TARGET SITE:', base)  # AGENTS: wajib cetak target
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

EXECUTE = '--execute' in sys.argv

def req(path, method='GET', data=None, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(base + path, method=method,
                data=json.dumps(data).encode() if data is not None else None,
                headers={'Authorization': 'token ' + tok, 'Content-Type': 'application/json'})
            resp = urllib.request.urlopen(r, timeout=90, context=ctx)
            body = resp.read().decode()
            return json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:800]
            if e.code in (429, 500, 502, 503, 504) and i < tries - 1:
                time.sleep(2 * (i + 1)); continue
            raise RuntimeError(f'HTTP {e.code}: {body}')

def get_doc(doctype, name):
    return req('/api/resource/%s/%s' % (urllib.parse.quote(doctype), urllib.parse.quote(name)))['data']

def guard(doc, label, kind='juri_company'):
    # DN/SO = dokumen JURI (company). PO intercompany = company outlet,
    # tapi supplier-nya PT. JUARA ROTI INDONESIA.
    if kind == 'juri_company' and doc.get('company') != COMPANY:
        raise SystemExit(f'GUARD: {label} company={doc.get("company")} bukan {COMPANY} — STOP')
    if kind == 'juri_supplier' and doc.get('supplier') != COMPANY:
        raise SystemExit(f'GUARD: {label} supplier={doc.get("supplier")} bukan {COMPANY} — STOP')

# (dn, so, po) — urut posting time asc. po = PO intercompany bila baris SO ter-link.
DNS = [('DN-081026-006','SLS-081026-006', None),
       ('DN-081026-007','SLS-081026-007', None),
       ('DN-081026-015','SLS-081026-015', 'PO223.071026.006'),
       ('DN-081026-018','SLS-081026-016', 'POO80.071026.003'),
       ('DN-081026-008','SLS-081026-008', None),
       ('DN-081026-009','SLS-081026-009', None),
       ('DN-081026-011','SLS-081026-011', None)]
POS_REV = ['PO223.071026.006', 'POO80.071026.003']
ZERO_OUT = 'SE-MR-261009002'
OLD2NEW_ITEM = {'BB260046': 'BB26012', 'BB260060': 'BB26012'}
OLESON = ('BB260046', 'BB260060', 'BB26012')

NOCOPY = {'name','owner','creation','modified','modified_by','docstatus','idx','parent','parentfield',
          'parenttype','_user_tags','_comments','_assignments','_liked','update_stock',
          'per_billed','per_returned','status','delivery_status','per_installed'}
NOCOPY_ROW = {'name','owner','creation','modified','modified_by','docstatus','idx','parent','parentfield',
              'parenttype','so_detail','dn_detail','pr_detail','against_sales_invoice','delivered_qty',
              'billed_amt','amount','base_amount','net_amount','base_net_amount','stock_qty','stock_uom',
              'actual_qty','target_warehouse','sales_order','delivery_note'}

def strip(doc):
    d = {k: v for k, v in doc.items() if k not in NOCOPY}
    d['docstatus'] = 0
    for fld in ('items', 'taxes', 'payment_schedule'):
        if fld in d:
            d[fld] = [{k: v for k, v in r.items() if k not in NOCOPY_ROW} for r in d[fld]]
    return d

state = {'cancelled_dn': [], 'cancelled_po': [], 'cancelled_so': [], 'amended_po': {}, 'amended_so': {},
         'new_dn': {}, 'zero_out_cancelled': False, 'temp_mr': '',
         'deleted_dn': [], 'zero_out_deleted': False, 'backup_saved': True}
if os.path.exists(STATE):
    state.update(json.load(open(STATE)))

def save():
    json.dump(state, open(STATE, 'w'), indent=1)

# ---------- backup (sekali) ----------
if not state.get('backup_docs'):
    data = {dn: get_doc('Delivery Note', dn) for dn, _, _ in DNS}
    data.update({so: get_doc('Sales Order', so) for _, so, _ in DNS})
    data.update({po: get_doc('Purchase Order', po) for po in POS_REV})
    data[ZERO_OUT] = get_doc('Stock Entry', ZERO_OUT)
    json.dump(data, open(BACKUP, 'w'), indent=1)
    for k, v in data.items():
        guard(v, k, 'juri_supplier' if k in POS_REV else 'juri_company')
    state['backup_docs'] = True
    save()
    print('BACKUP + guard company OK:', BACKUP)

def cancel(doctype, name, key):
    if name in state[key]:
        return
    d = get_doc(doctype, name)
    guard(d, name, 'juri_supplier' if doctype == 'Purchase Order' else 'juri_company')
    if d['docstatus'] == 2:
        state[key].append(name); save(); return
    if not EXECUTE:
        print(f'[DRY] cancel {doctype} {name}'); return
    req('/api/resource/%s/%s' % (urllib.parse.quote(doctype), urllib.parse.quote(name)),
        'PUT', {'docstatus': 2})
    state[key].append(name); save()
    print(f'cancelled {doctype} {name}')

def submit_doc(doctype, name):
    req('/api/resource/%s/%s' % (urllib.parse.quote(doctype), urllib.parse.quote(name)),
        'PUT', {'docstatus': 1})

def amend_po(po_name):
    if po_name in state['amended_po']:
        return state['amended_po'][po_name]
    old = get_doc('Purchase Order', po_name)
    guard(old, po_name, 'juri_supplier')
    if old['docstatus'] == 2 and not EXECUTE:
        print(f'[DRY] amend {po_name}'); return None
    if not any(r['item_code'] in OLESON for r in old['items']):
        print(po_name, 'tanpa baris olesan, skip'); return None
    new = strip(old)
    new['amended_from'] = po_name
    new['items'] = [dict(r, item_code='BB26012', item_name='Olesan Pastry (250 g)')
                    if r['item_code'] in ('BB260060', 'BB260046') else r for r in new['items']]
    if not EXECUTE:
        print(f'[DRY] amend+submit {po_name}'); return None
    res = req('/api/resource/Purchase%20Order', 'POST', new)['data']
    submit_doc('Purchase Order', res['name'])
    state['amended_po'][po_name] = res['name']; save()
    print(f'amended PO {po_name} -> {res["name"]}')
    return res['name']

def amend_so(so_name, po_name):
    if so_name in state['amended_so']:
        return state['amended_so'][so_name]
    old = get_doc('Sales Order', so_name)
    guard(old, so_name)
    if old['docstatus'] == 2 and not EXECUTE:
        print(f'[DRY] amend {so_name}'); return None
    new = strip(old)
    new['amended_from'] = so_name
    # remap PO link di baris (bila ada) ke PO hasil amend
    new_po = state['amended_po'].get(po_name) if po_name else None
    poi_map = {}
    if new_po:
        old_po = get_doc('Purchase Order', po_name)
        new_podoc = get_doc('Purchase Order', new_po)
        # map per idx (amend menjaga urutan baris)
        for o, n in zip(old_po['items'], new_podoc['items']):
            poi_map[o['name']] = n['name']
    new['items'] = []
    for r in old['items']:
        r = {k: v for k, v in r.items() if k not in NOCOPY_ROW}
        if r['item_code'] in ('BB260046', 'BB260060'):
            r['item_code'] = 'BB26012'; r['item_name'] = 'Olesan Pastry (250 g)'
        if new_po and r.get('purchase_order'):
            r['purchase_order'] = new_po
            if r.get('purchase_order_item') in poi_map:
                r['purchase_order_item'] = poi_map[r['purchase_order_item']]
        new['items'].append(r)
    if not EXECUTE:
        print(f'[DRY] amend+submit {so_name}'); return None
    res = req('/api/resource/Sales%20Order', 'POST', new)['data']
    submit_doc('Sales Order', res['name'])
    state['amended_so'][so_name] = res['name']; save()
    print(f'amended SO {so_name} -> {res["name"]}')
    return res['name']

def rebuild_dn(dn_name, so_name):
    if dn_name in state['new_dn']:
        return state['new_dn'][dn_name]
    old = get_doc('Delivery Note', dn_name)
    guard(old, dn_name)
    new_so = get_doc('Sales Order', state['amended_so'][so_name])
    # map baris SO lama -> baru per idx (utk so_detail)
    old_so = get_doc('Sales Order', so_name)
    so_map = {o['name']: n['name'] for o, n in
              zip(sorted(old_so['items'], key=lambda r: r['idx']),
                  sorted(new_so['items'], key=lambda r: r['idx']))}
    new = strip(old)
    new['set_posting_time'] = 1  # jebakan #2: pertahankan backdate
    # field posting_date tidak boleh dihapus dari doc (NOCOPY tidak memuatnya, tapi strip() perlu di-override)
    new['posting_date'] = old['posting_date']
    new['posting_time'] = old['posting_time']
    new['items'] = []
    dropped = []
    for r in old['items']:
        old_sodet = r.get('so_detail')  # ambil SEBELUM strip (ada di NOCOPY_ROW)
        r = {k: v for k, v in r.items() if k not in NOCOPY_ROW}
        if r['item_code'] in ('BB260046', 'BB260060'):
            r['item_code'] = 'BB26012'; r['item_name'] = 'Olesan Pastry (250 g)'
        # BB260019 & BB260046 out-of-stock trail 8 Okt; pergerakan bahan antar
        # gudang JURI dipindah ke SE-MTF terpisah (jangan lewat DN)
        if r['item_code'] in ('BB260019', 'BB260046'):
            dropped.append((dn_name, r['item_code'], r['qty']))
            continue
        # remap so_detail utk SEMUA baris (mandatory di DN baru)
        if old_sodet in so_map:
            r['so_detail'] = so_map[old_sodet]
        r['against_sales_order'] = state['amended_so'][so_name]
        new['items'].append(r)
    if not EXECUTE:
        print(f'[DRY] rebuild {dn_name}'); return None
    if dropped:
        print('  DROPPED (pindah SE-MTF):', dropped)
    if dropped:
        state.setdefault('dropped_bahan', []).extend(dropped); save()
    if os.environ.get('DEBUG_PAYLOAD'):
        print('SAMPLE ROW:', json.dumps({k: new['items'][0].get(k) for k in ('item_code','so_detail','against_sales_order','qty')}, indent=1))
    res = req('/api/resource/Delivery%20Note', 'POST', new)['data']
    submit_doc('Delivery Note', res['name'])
    state['new_dn'][dn_name] = res['name']; save()
    print(f'rebuilt DN {dn_name} -> {res["name"]} (BB26012, backdate {old["posting_date"]} {old["posting_time"]})')
    return res['name']

def delete_doc(doctype, name, key):
    if name in state[key]:
        return
    if not EXECUTE:
        print(f'[DRY] delete {doctype} {name}'); return
    req('/api/resource/%s/%s' % (urllib.parse.quote(doctype), urllib.parse.quote(name)), 'DELETE')
    state[key].append(name); save()
    print(f'deleted {doctype} {name}')

# ---------- 1a) temp MR kompensasi +500 g @ 08-10-2026 07:59 (deadlock 015/018) ----------
if not state.get('temp_mr'):
    if not EXECUTE:
        print('[DRY] buat temp MR +500 g BB260046 @ GBJ 07:59')
    else:
        res = req('/api/resource/Stock%20Entry', 'POST', {
            'doctype': 'Stock Entry', 'stock_entry_type': 'Material Receipt',
            'purpose': 'Material Receipt', 'set_posting_time': 1,
            'posting_date': '2026-10-08', 'posting_time': '07:59:00',
            'company': COMPANY,
            'remarks': 'ERESTO TEMP-KOMPENSASI REVISI OLESAN (AKAN DICANCEL+HAPUS)',
            'items': [{'item_code': 'BB260046', 'qty': 500, 'uom': 'g', 'stock_uom': 'g',
                       'conversion_factor': 1.0, 'transfer_qty': 500.0,
                       't_warehouse': 'Gudang Barang Jadi - JURI',
                       'basic_rate': 34.15, 'use_serial_batch_fields': 1}]})['data']
        state['temp_mr'] = res['name']; save()
        submit_doc('Stock Entry', res['name'])
        print('temp MR:', res['name'])
# ---------- 1b) cancel 7 DN (DESC posting time) ----------
for dn, so, po in sorted(DNS, key=lambda x: x[0], reverse=True):
    cancel('Delivery Note', dn, 'cancelled_dn')
# ---------- 1c) cancel temp MR & zero-out ----------
if state.get('temp_mr') and not state.get('temp_mr_cancelled'):
    if EXECUTE:
        req('/api/resource/Stock%20Entry/' + urllib.parse.quote(state['temp_mr']),
            'PUT', {'docstatus': 2})
        state['temp_mr_cancelled'] = True; save()
        print('temp MR cancelled')
    else:
        print('[DRY] cancel temp MR')
if not state['zero_out_cancelled']:
    d = get_doc('Stock Entry', ZERO_OUT)
    guard(d, ZERO_OUT)
    if d['docstatus'] == 2:
        state['zero_out_cancelled'] = True; save()
    elif EXECUTE:
        req('/api/resource/Stock%20Entry/' + ZERO_OUT, 'PUT', {'docstatus': 2})
        state['zero_out_cancelled'] = True; save(); print('cancelled', ZERO_OUT)
    else:
        print('[DRY] cancel', ZERO_OUT)
# ---------- 2) amend PO: cancel SO dulu (SO merefer PO) ----------
for dn, so, po in DNS:
    if po:
        cancel('Sales Order', so, 'cancelled_so')
for po in POS_REV:
    cancel('Purchase Order', po, 'cancelled_po')
    amend_po(po)
# ---------- 3) amend SO (yang belum) ----------
for dn, so, po in DNS:
    cancel('Sales Order', so, 'cancelled_so')
    amend_so(so, po)
# ---------- 4) rebuild DN ----------
for dn, so, po in DNS:
    rebuild_dn(dn, so)
# ---------- 5) hapus cancelled: DN lama, temp MR, zero-out ----------
for dn, _, _ in DNS:
    delete_doc('Delivery Note', dn, 'deleted_dn')
delete_doc('Stock Entry', state['temp_mr'], 'temp_mr_deleted')
delete_doc('Stock Entry', ZERO_OUT, 'zero_out_deleted')
print('SELESAI. SO & PO lama dibiarkan cancelled (dirujuk amended_from).')
