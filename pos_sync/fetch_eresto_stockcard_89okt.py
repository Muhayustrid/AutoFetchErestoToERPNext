"""Fetch eResto stock_cards 8-9 Okt 2026 (READ-ONLY, GET) -> JSON lokal.
Pusat division = yang memuat SKU produksi (BB0085 Krim Kopi dst)."""
import json, ssl, urllib.request, urllib.parse, os, time

env = {}
for line in open('/tmp/eresto_mig.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k] = v
tok = env['ERESTO_TOKEN']; email = env['ERESTO_EMAIL']; uid = env['ERESTO_USER_ID']
ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'eresto_stockcard_89okt.json')

def fetch(day, page, per=100):
    params = {'current_user_id': uid,
              'date[geq]': f'{day} 00:00:00.000', 'date[leq]': f'{day} 23:59:59.999',
              'division_id': '', 'domain': 'ropi', 'page': str(page), 'per_page': str(per),
              'simple': 'true', 'sort[order]': 'asc', 'sort[property]': 'date', 'token': tok}
    r = urllib.request.Request('https://ropi.eresto.id/v2/stock_cards?' + urllib.parse.urlencode(params),
        headers={'Authorization': f'Token token={tok}, email={email}',
                 'Referer': 'https://ropi.eresto.id/manager/v2/index.html', 'Accept': 'application/json'})
    for attempt in range(3):
        try:
            return json.load(urllib.request.urlopen(r, timeout=60, context=ctx))
        except Exception as e:
            print('retry', page, e); time.sleep(3)
    return {'stock_cards': []}

allrows = []
for day in ['Sat, 08 Oct 2026', 'Fri, 09 Oct 2026']:
    page = 1
    while page <= 400:
        d = fetch(day, page)
        rows = d.get('stock_cards', [])
        allrows += rows
        print(day, 'page', page, '->', len(rows), flush=True)
        if len(rows) < 100:
            break
        page += 1
    if page > 400:
        print('STOP: cap halaman tercapai', day)
json.dump(allrows, open(OUT, 'w'))
print('TOTAL:', len(allrows))
from collections import Counter
c = Counter((x.get('division') or {}).get('name', '?') for x in allrows)
print('--- divisions (top) ---')
for k, v in c.most_common(12):
    print(v, k)
