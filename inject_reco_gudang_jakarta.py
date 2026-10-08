"""
Injeksi Stock Reconciliation Gudang Jakarta ke ERPNext Cloud (ropierpnext.frappe.cloud).
Sumber: Data Stock Opname eResto SACK2.011026.001 per 30 September 2026.
Target: Gudang Jakarta - JURI (PT. JUARA ROTI INDONESIA).
"""

import json
import os
import re
import sys
import time
import urllib.parse
import pandas as pd
import requests

ENV_FILE = "/tmp/eresto_prod.env"
if not os.path.exists(ENV_FILE):
    print(f"Error: {ENV_FILE} not found!")
    sys.exit(1)

with open(ENV_FILE) as f:
    conf = dict(line.strip().split("=", 1) for line in f if "=" in line)

URL = conf["ERPNEXT_URL"].rstrip("/")
HEADERS = {
    "Authorization": f"token {conf['ERPNEXT_API_KEY']}",
    "Content-Type": "application/json",
    "Accept": "application/json",
}

COMPANY = "PT. JUARA ROTI INDONESIA"
WAREHOUSE = "Gudang Jakarta - JURI"
POSTING_DATE = "2026-09-30"
POSTING_TIME = "23:00:00"
PURPOSE = "Opening Stock"
EXPENSE_ACCOUNT = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"

RAW_TEXT = """1.	BB0036	Capitan Roti	3 Pcs	4Pcs	1Pcs	Rp9.516,44/Pcs	Rp9.516,44
2.	BB0235	Dispenser Lakban	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
3.	BB0046	Dough Butter	1060 Pack	1123Pack	63Pack	Rp9.269,56/Pack	Rp583.982,28
4.	BB0047	Dough Coklat	1332 Pack	1418Pack	86Pack	Rp9.541,86/Pack	Rp820.599,62
5.	BB0261	Dough Gempi	1112 Pack	1149Pack	37Pack	Rp7.377,56/Pack	Rp272.969,55
6.	BB0049	Dough Keju	880 Pack	923Pack	43Pack	Rp10.869,54/Pack	Rp467.390,21
7.	BB0223	Ember 15 L	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
8.	BB0298	Gelas 14 Oz (Isi 150 pcs)	6100 Pcs	2600Pcs	-3500Pcs	Rp380,99/Pcs	-Rp1.333.474,45
9.	BB0257	Gelas Cup 9 Oz (Isi 50 pcs)	8700 Pcs	9250Pcs	550Pcs	Rp323,84/Pcs	Rp178.110,52
10.	BB0064	Gelas Takar 2 L	1 Pcs	1Pcs	0Pcs	Rp13.581,55/Pcs	Rp0,00
11.	BB0065	Gelas Takar 5 L	2 Pcs	2Pcs	0Pcs	Rp57.682,92/Pcs	Rp0,00
12.	BB0066	Goodie Bag	6640 Pcs	6664Pcs	24Pcs	Rp1.367,24/Pcs	Rp32.813,65
13.	BB0305	Gula Cair Sachet (Isi 100 Sachet)	3740 Sachet	6240Sachet	2500Sachet	Rp265,31/Sachet	Rp663.283,25
14.	BB0071	Gula Stik	2750 Pcs	2750Pcs	0Pcs	Rp227,42/Pcs	Rp0,00
15.	BB0072	Gunting	7 Pcs	7Pcs	0Pcs	Rp4.473,83/Pcs	Rp0,00
16.	BB0329	Jasmine Green Tea 750g	185 Pack	197Pack	12Pack	Rp63.744,13/Pack	Rp764.929,50
17.	BB0073	Jigger	0 Pcs	0Pcs	0Pcs	Rp7.642,86/Pcs	Rp0,00
18.	BB0328	Jilbab Outlet	20 Pcs	40Pcs	20Pcs	Rp24.500,00/Pcs	Rp490.000,00
19.	BB0074	Kanebo	14 Pcs	16Pcs	2Pcs	Rp7.922,60/Pcs	Rp15.845,21
20.	BB0313	Jug Stainless	12 Pcs	12Pcs	0Pcs	Rp35.211,31/Pcs	Rp0,00
21.	BB0075	Kaos Gempi	0 Pcs	0Pcs	0Pcs	Rp55.000,00/Pcs	Rp0,00
22.	BB0076	Kaos Panjang	16 Pcs	16Pcs	0Pcs	Rp55.000,00/Pcs	Rp0,00
23.	BB0077	Kaos Pendek	0 Pcs	20Pcs	20Pcs	Rp50.000,00/Pcs	Rp1.000.000,00
24.	BB0078	Kaos Polo	0 Pcs	0Pcs	0Pcs	Rp70.000,00/Pcs	Rp0,00
25.	BB0079	Kardus Packing Ropi Beku	496 Pcs	163Pcs	-333Pcs	Rp6.806,01/Pcs	-Rp2.266.400,63
26.	BB0080	Kardus Ropi Kapasitas 20 roti (25 pcs/pack)	50 Pcs	100Pcs	50Pcs	Rp4.167,12/Pcs	Rp208.356,24
27.	BB0081	Keju Chedar	30 Pcs	34Pcs	4Pcs	Rp10.682,67/Pcs	Rp42.730,69
28.	BB0191	Kertas Thermal	117 Pack	150Pack	33Pack	Rp24.334,63/Pack	Rp803.042,87
29.	BB0322	Kopi Hitam @6gr (Isi 20 Sachet)	0 Pcs	0Pcs	0Pcs	Rp702,09/Pcs	Rp0,00
30.	BB0085	Krim Kopi	2330 Pcs	2330Pcs	0Pcs	Rp14.186,71/Pcs	Rp0,00
31.	BB0086	Krim Kopi 700gr	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
32.	BB0088	Krim Pandan	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
33.	BB0089	Krim Susu	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
34.	BB0068	Kuas Oles Loyang 1,5'	6 Pcs	7Pcs	1Pcs	Rp9.055,40/Pcs	Rp9.055,40
35.	BB0090	Kuas Oles Loyang 2'	6 Pcs	7Pcs	1Pcs	Rp10.016,32/Pcs	Rp10.016,32
36.	BB0270	Kuas Silikon	6 Pcs	7Pcs	1Pcs	Rp12.777,04/Pcs	Rp12.777,04
37.	BB0271	Kursi Outlet	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
38.	BB0082	Lakban Besar	116 Pcs	66Pcs	-50Pcs	Rp10.623,31/Pcs	-Rp531.165,60
39.	BB0229	Lap Microfiber	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
40.	BB0349	Lemonade 640g	26 Pack	26Pack	0Pack	Rp48.738,75/Pack	Rp0,00
41.	BB0092	Loyang	71 Pcs	80Pcs	9Pcs	Rp52.840,94/Pcs	Rp475.568,46
42.	BB0093	Loyang Gempi	78 Pcs	106Pcs	28Pcs	Rp24.955,50/Pcs	Rp698.754,06
43.	BB0096	Meises Coklat 1kg	10 kg	11kg	1kg	Rp24.544,53/kg	Rp24.544,53
44.	BB0097	Meises Warna 500 gram	0 kg	0kg	0kg	Rp8.000,00/kg	Rp0,00
45.	BB0097	Meises Warna 500 gram	0 Pack	0Pack	0Pack	Rp16.327,25/Pack	Rp0,00
46.	BB0183	Memory Card	0 Pcs	0Pcs	0Pcs	Rp152.250,00/Pcs	Rp0,00
47.	BB0346	Milo Activ 960g	39 Pack	39Pack	0Pack	Rp94.594,63/Pack	Rp0,00
48.	BB0100	Minyak Oles 1 Kg	18 kg	22kg	4kg	Rp21.996,50/kg	Rp87.986,00
49.	BB0102	Olesan Choco Crunchy (1 Kg)	26 kg	32kg	6kg	Rp50.895,03/kg	Rp305.370,18
50.	BB0103	Olesan Dark Choco (1 Kg)	29 kg	35kg	6kg	Rp57.081,00/kg	Rp342.486,00
51.	BB0105	Olesan Margarine	24 Pcs	28Pcs	4Pcs	Rp7.407,92/Pcs	Rp29.631,70
52.	BB0174	Olesan Pastry	327 Pcs	330Pcs	3Pcs	Rp1.707,48/Pcs	Rp5.122,43
53.	BB0110	Olesan Tiramisu (1 Kg)	20 kg	23kg	3kg	Rp51.913,27/kg	Rp155.739,81
54.	BB0262	Orbit Outlet	0 Unit	0Unit	0Unit	Rp0,00/Unit	Rp0,00
55.	BB0314	Palu Karet Outlet	5 Pcs	6Pcs	1Pcs	Rp26.937,99/Pcs	Rp26.937,99
56.	BB0112	Paper Bag Kapasitas 1 Roti	112759 Pcs	117059Pcs	4300Pcs	Rp219,38/Pcs	Rp943.318,95
57.	BB0114	Parutan Keju	5 Pcs	6Pcs	1Pcs	Rp2.314,72/Pcs	Rp2.314,72
58.	BB0222	Pel Lantai	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
59.	BB0116	Pisau Roti	5 Pcs	6Pcs	1Pcs	Rp7.739,37/Pcs	Rp7.739,37
60.	BB0117	Plastik Alas Gempi	5350 Pcs	5800Pcs	450Pcs	Rp106,67/Pcs	Rp48.000,02
61.	BB0296	Plastik Cup Isi 1	121 Pack	131Pack	10Pack	Rp3.932,56/Pack	Rp39.325,64
62.	BB0297	Plastik Cup Isi 2	121 Pack	127Pack	6Pack	Rp3.951,09/Pack	Rp23.706,57
63.	BB0118	Plastik Kresek Ukuran 17	354 Pack	360Pack	6Pack	Rp5.640,47/Pack	Rp33.842,80
64.	BB0119	Plastik Kresek Ukuran 24	126 Pack	144Pack	18Pack	Rp6.085,94/Pack	Rp109.546,88
65.	BB0120	Plastik Krim	1402 Pcs	1370Pcs	-32Pcs	Rp440,00/Pcs	-Rp14.080,00
66.	BB0138	Plastik Sampah	0 kg	0kg	0kg	Rp19.351,63/kg	Rp0,00
67.	BB0122	Plastik Seal Roti	32000 Pcs	32500Pcs	500Pcs	Rp96,06/Pcs	Rp48.029,00
68.	BB0137	Plastik Wrapping	28 Pcs	20Pcs	-8Pcs	Rp32.983,08/Pcs	-Rp263.864,65
69.	BB0128	Regulator	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
70.	BB0129	Rice Bucket	0 Pcs	0Pcs	0Pcs	Rp434.143,33/Pcs	Rp0,00
71.	BB0220	Sapu Outlet	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
72.	BB0130	Saringan Teh	5 Pcs	5Pcs	0Pcs	Rp10.081,82/Pcs	Rp0,00
73.	BB0131	Sarung Tangan Oven	6 Pcs	7Pcs	1Pcs	Rp77.646,60/Pcs	Rp77.646,60
74.	BB0132	Sarung Tangan Plastik	81 Pack	80Pack	-1Pack	Rp28.377,75/Pack	-Rp28.377,75
75.	BB0133	Sealware Gempi	19 Pcs	22Pcs	3Pcs	Rp25.326,68/Pcs	Rp75.980,05
76.	BB0134	Sedotan Teh	71 Pack	79Pack	8Pack	Rp7.472,01/Pack	Rp59.776,09
77.	BB0135	Selang Gas	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
78.	BB0344	Selezione 500g	7 Pack	7Pack	0Pack	Rp181.982,00/Pack	Rp0,00
79.	BB0136	Sendok Es Batu	6 Pcs	7Pcs	1Pcs	Rp14.438,03/Pcs	Rp14.438,03
80.	BB0269	Serokan Sampah Outlet	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
81.	BB0141	Solet Gempi	21 Pcs	24Pcs	3Pcs	Rp802,68/Pcs	Rp2.408,05
82.	BB0142	Spatula	7 Pcs	8Pcs	1Pcs	Rp16.793,32/Pcs	Rp16.793,32
83.	BB0143	Stirrer	14000 Pcs	14000Pcs	0Pcs	Rp23,94/Pcs	Rp0,00
84.	BB0145	Susu Bubuk untuk Campuran Minuman (1 Kg)	0 kg	0kg	0kg	Rp63.439,62/kg	Rp0,00
85.	BB0148	Tabung Gas Outlet	0 Tabung	0Tabung	0Tabung	Rp0,00/Tabung	Rp0,00
86.	BB0347	Teh Tarik 960g	10 Pack	10Pack	0Pack	Rp97.792,81/Pack	Rp0,00
87.	BB0152	Teko Listrik	3 Pcs	4Pcs	1Pcs	Rp160.600,00/Pcs	Rp160.600,00
88.	BB0159	Timbangan	3 Pcs	3Pcs	0Pcs	Rp67.008,88/Pcs	Rp0,00
89.	BB0232	Tong Sampah	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
90.	BB0160	Topi	21 Pcs	29Pcs	8Pcs	Rp14.596,67/Pcs	Rp116.773,35
91.	BB0161	Toples 1300L	13 Pcs	13Pcs	0Pcs	Rp3.849,62/Pcs	Rp0,00
92.	BB0162	Toples Athena	6 Pcs	7Pcs	1Pcs	Rp6.500,00/Pcs	Rp6.500,00
93.	BB0164	Wijen Hitam 250 gram	6 Pack	6Pack	0Pack	Rp19.587,94/Pack	Rp0,00
94.	BB0165	Wijen Putih 250 gram	5 Pack	5Pack	0Pack	Rp12.208,17/Pack	Rp0,00
95.	BB0168	Dough Croissant	326 Pack	346Pack	20Pack	Rp11.508,38/Pack	Rp230.167,60
96.	BB0312	Air Mineral Outlet 600 ml	120 Botol	264Botol	144Botol	Rp1.697,29/Botol	Rp244.410,00
97.	BB0006	Apron	11 Pcs	14Pcs	3Pcs	Rp35.000,00/Pcs	Rp105.000,00
98.	BB0007	Apron Gempi	24 Pcs	24Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
99.	BB0008	Balon ROPI Warna Kuning (Isi 100pcs)	200 Pcs	300Pcs	100Pcs	Rp1.065,98/Pcs	Rp106.598,00
100.	BB0009	Balon ROPI Warna Orange (Isi 100pcs)	900 Pcs	1000Pcs	100Pcs	Rp1.063,00/Pcs	Rp106.300,00
101.	BB0010	Balon ROPI Warna Pink (Isi 100pcs)	200 Pcs	200Pcs	0Pcs	Rp1.063,00/Pcs	Rp0,00
102.	BB0011	Balon ROPI Warna Putih (Isi 100pcs)	200 Pcs	200Pcs	0Pcs	Rp1.063,00/Pcs	Rp0,00
103.	BB0012	Beater Better	3 Pcs	3Pcs	0Pcs	Rp155.693,37/Pcs	Rp0,00
104.	BB0260	Bill Holder	0 Pcs	0Pcs	0Pcs	Rp0,00/Pcs	Rp0,00
105.	BB0021	Botol Bistro 600 ml	7 Pcs	7Pcs	0Pcs	Rp11.542,86/Pcs	Rp0,00
106.	BB0022	Botol Bistro 800 ml	7 Pcs	7Pcs	0Pcs	Rp17.220,00/Pcs	Rp0,00
107.	BB0185	Botol Spray	10 Pcs	11Pcs	1Pcs	Rp3.895,05/Pcs	Rp3.895,05
108.	BB0171	Box Gempi (Isi 100 pcs)	4807 Pcs	5389Pcs	582Pcs	Rp1.942,89/Pcs	Rp1.130.760,35
109.	BB0309	Bubuk Hepi Drink Cappucino (30 Gr)	0 Sachet	0Sachet	0Sachet	Rp3.800,00/Sachet	Rp0,00
110.	BB0311	Bubuk Hepi Drink Chocolate	0 Sachet	0Sachet	0Sachet	Rp1.048,77/Sachet	Rp0,00
111.	BB0310	Bubuk Hepi Drink Kopi Karamel (30 Gr)	0 Sachet	0Sachet	0Sachet	Rp3.800,00/Sachet	Rp0,00
112.	BB0308	Bubuk Hepi Drink Moccacino (30 Gr)	0 Sachet	0Sachet	0Sachet	Rp3.799,89/Sachet	Rp0,00
113.	BB0217	CCTV Outlet	0 Pcs	0Pcs	0Pcs	Rp338.000,00/Pcs	Rp0,00
114.	BB0341	Coffee Classic 120g	215 Pack	228Pack	13Pack	Rp47.675,67/Pack	Rp619.783,67
115.	BB0340	Coffee Latte 500g	228 Pack	260Pack	32Pack	Rp53.237,83/Pack	Rp1.703.610,67
116.	BB0039	Coffee Spoon	7 Pcs	7Pcs	0Pcs	Rp2.480,24/Pcs	Rp0,00
117.	BB0345	Coffeemate 450g	30 Pack	30Pack	0Pack	Rp29.012,05/Pack	Rp0,00
118.	BB0040	Corong	7 Pcs	8Pcs	1Pcs	Rp4.468,39/Pcs	Rp4.468,39
119.	BB0042	Crispy Ball 500 gram	13 Pack	13Pack	0Pack	Rp30.877,87/Pack	Rp0,00
120.	BB0156	Cup Holder	10 Pcs	10Pcs	0Pcs	Rp211.368,98/Pcs	Rp0,00
121.	BB0342	Dark Cocoa Drink 1Kg	250 Pack	262Pack	12Pack	Rp78.576,56/Pack	Rp942.918,75
122.	BB0043	Daun Teh Enak Kata Orang	170 Pcs	170Pcs	0Pcs	Rp9.600,00/Pcs	Rp0,00
123.	BB0044	Dispenser 8L	2 Pcs	0Pcs	-2Pcs	Rp85.150,00/Pcs	-Rp170.300,00"""

# Base mapping from earlier verified master
from inject_reco_barang_jadi import ITEMS_DATA
sku_map = {it['sku']: it for it in ITEMS_DATA}

# Specific mapping for items unique to Jakarta or Dough
extra_map = {
    'BB0046': ('PJ260012', 'Dough Ropi Butter', 12.0, 'Pack', 'Pcs'),
    'BB0047': ('PJ260013', 'Dough Ropi Coklat', 12.0, 'Pack', 'Pcs'),
    'BB0261': ('PJ260011', 'Dough Gempi', 3.0, 'Pack', 'Pcs'),
    'BB0049': ('PJ260014', 'Dough Ropi Keju', 12.0, 'Pack', 'Pcs'),
    'BB0168': ('PJ260010', 'Dough Croissant', 6.0, 'Pack', 'Pcs'),
    'BB0085': ('PJ260016', 'Krim Kopi', 1.0, 'Pcs', 'Pcs'),
    'BB0349': ('BB260051', 'Lemonade (640 g)', 640.0, 'Pack', 'g'),
    'BB0346': ('BB260052', 'Milo Activ (960 g)', 960.0, 'Pack', 'g'),
    'BB0347': ('BB260054', 'Teh Tarik (960 g)', 960.0, 'Pack', 'g'),
    'BB0345': ('BB260050', 'Coffeemate (450 g)', 450.0, 'Pack', 'g'),
    'BB0344': ('BB260053', 'Selezione (500 g)', 500.0, 'Pack', 'g'),
    'BB0312': ('PJ260009', 'Air Mineral Outlet (600 ml)', 1.0, 'Botol', 'Botol'),
    'BB0131': ('PEL260038', 'Sarung Tangan Oven', 1.0, 'Pcs', 'Pcs'),
    'BB0077': ('PEL260019', 'Kaos Polo Ropi', 1.0, 'Pcs', 'Pcs'),
}

def req(method, path, payload=None, params=None, max_retries=4):
    url = f"{URL}{path}"
    for attempt in range(1, max_retries + 1):
        try:
            r = requests.request(method, url, json=payload, params=params, headers=HEADERS, timeout=90)
            if r.status_code in {429, 500, 502, 503, 504}:
                time.sleep(2 ** attempt)
                continue
            return r.status_code, r.json()
        except requests.RequestException as e:
            if attempt == max_retries:
                return -1, {"error": str(e)}
            time.sleep(2 ** attempt)
    return -1, {"error": "Failed after retries"}

def parse_items():
    items = []
    skipped_zero = []
    skipped_unmatched = []

    for l in RAW_TEXT.strip().split("\n"):
        p = l.split("\t")
        if len(p) < 8:
            continue
        sku = p[1].strip()
        name = p[2].strip()
        m = re.match(r"^([\d\.\-]+)\s*([a-zA-Z]+)", p[4].strip())
        after_qty = float(m.group(1)) if m else 0.0
        uom = m.group(2) if m else ""
        c = p[6].replace("Rp", "").split("/")[0].replace(".", "").replace(",", ".").strip()
        rate = float(c) if c else 0.0

        if after_qty == 0:
            skipped_zero.append((sku, name))
            continue

        item_code = None
        item_name = None
        factor = 1.0
        c_uom = uom
        s_uom = uom

        if sku in extra_map:
            item_code, item_name, factor, c_uom, s_uom = extra_map[sku]
        elif sku in sku_map:
            orig = sku_map[sku]
            item_code = orig["item_code"]
            item_name = orig["name"]
            c_uom = orig["eresto_uom"]
            s_uom = orig["uom"]
            factor = orig["qty"] / orig["eresto_qty"] if orig["eresto_qty"] != 0 else 1.0
        else:
            skipped_unmatched.append((sku, name, after_qty, rate))
            continue

        items.append({
            "sku": sku,
            "name": name,
            "item_code": item_code,
            "item_name": item_name,
            "eresto_qty": after_qty,
            "eresto_uom": uom,
            "eresto_rate": rate,
            "custom_uom": c_uom,
            "custom_qty_after": after_qty,
            "conversion_factor": factor,
            "stock_uom": s_uom,
            "native_qty": after_qty * factor,
            "native_rate": rate / factor if factor != 0 else rate,
        })

    return items, skipped_zero, skipped_unmatched

def main():
    items, skipped_zero, skipped_unmatched = parse_items()
    print(f"=== Menyiapkan Injeksi Stock Reconciliation: {WAREHOUSE} ===")
    print(f"Total baris valid yang akan diinjeksi: {len(items)}")
    print(f"Dilewati (stok 0): {len(skipped_zero)}")
    print(f"Dilewati (belum ada di master): {len(skipped_unmatched)}")
    for sk in skipped_unmatched:
        print(f"  - {sk[0]} | {sk[1]} (Qty: {sk[2]}, Rate: Rp {sk[3]:,.2f})")

    # 1. Cek keberadaan dan Item Defaults
    print("\n[1/4] Memeriksa Item Code dan Item Defaults di ERPNext...")
    for it in items:
        code = it["item_code"]
        st, res = req("GET", f"/api/resource/Item/{urllib.parse.quote(code)}")
        if st != 200:
            print(f"  FATAL: {code} tidak ditemukan di ERPNext!")
            sys.exit(1)
        doc = res.get("data", {})
        defaults = doc.get("item_defaults", [])
        juri = next((d for d in defaults if d.get("company") == COMPANY), None)
        if not juri or not juri.get("default_inventory_account"):
            grp = doc.get("item_group", "")
            acc = "1143.000 - Raw Material - JURI" if "Bahan Baku" in grp else "1141.000 - Finished Goods - JURI"
            print(f"  Menambahkan Item Default untuk {code} (Acc: {acc})...")
            if not juri:
                defaults.append({
                    "company": COMPANY,
                    "default_warehouse": WAREHOUSE,
                    "default_inventory_account": acc
                })
                req("PUT", f"/api/resource/Item/{urllib.parse.quote(code)}", {"item_defaults": defaults})
            else:
                req("POST", "/api/method/frappe.client.set_value", {
                    "doctype": "Item Default",
                    "name": juri["name"],
                    "fieldname": "default_inventory_account",
                    "value": acc
                })
    print("  OK: Semua item terdaftar dan memiliki akun persediaan default.")

    # 2. Susun dokumen Stock Reconciliation
    print(f"\n[2/4] Menyusun dokumen Stock Reconciliation ({POSTING_DATE} {POSTING_TIME})...")
    reco_items = []
    total_val = 0.0

    for it in items:
        # Fallback for Apron Gempi where eResto recorded rate 0
        if it["item_code"] == "PEL260005" and it["eresto_rate"] == 0:
            it["eresto_rate"] = 35000.0
            it["native_rate"] = 35000.0

        qty = round(it["native_qty"], 4)
        rate = round(it["native_rate"], 4)
        c_qty = round(it["custom_qty_after"], 4)
        c_rate = round(it["eresto_rate"], 4)
        factor = round(it["conversion_factor"], 4)
        
        val = c_qty * c_rate
        total_val += val

        row = {
            "item_code": it["item_code"],
            "warehouse": WAREHOUSE,
            "qty": qty,
            "valuation_rate": rate,
            "uom": it["stock_uom"],
            "custom_uom": it["custom_uom"],
            "custom_conversion_factor": factor,
            "custom_qty_after": c_qty,
            "custom_qty_before": 0.0,
            "custom_qty_difference_per_uom": c_qty,
            "custom_valuation_rate_per_uom": c_rate,
            "allow_zero_valuation_rate": 1 if rate == 0 else 0,
        }
        reco_items.append(row)

    payload = {
        "doctype": "Stock Reconciliation",
        "company": COMPANY,
        "purpose": PURPOSE,
        "set_posting_time": 1,
        "posting_date": POSTING_DATE,
        "posting_time": POSTING_TIME,
        "set_warehouse": WAREHOUSE,
        "expense_account": EXPENSE_ACCOUNT,
        "cost_center": COST_CENTER,
        "items": reco_items,
    }

    print(f"  Total item: {len(reco_items)}")
    print(f"  Total nilai persediaan: Rp {total_val:,.2f}")

    # 3. POST Draft
    print(f"\n[3/4] Mengirim dokumen Stock Reconciliation (POST Draft)...")
    st, res = req("POST", "/api/resource/Stock Reconciliation", payload)
    if st != 200:
        print(f"  GAGAL POST Stock Reconciliation ({st}):\n{json.dumps(res, indent=2)}")
        sys.exit(1)

    reco_name = res.get("data", {}).get("name")
    print(f"  OK: Berhasil membuat Draft Stock Reconciliation: {reco_name}")

    # 4. Submit
    print(f"\n[4/4] Men-submit dokumen {reco_name} (docstatus = 1)...")
    sub_st, sub_res = req("PUT", f"/api/resource/Stock Reconciliation/{urllib.parse.quote(reco_name)}", {
        "docstatus": 1
    })
    if sub_st != 200:
        print(f"  GAGAL SUBMIT Stock Reconciliation ({sub_st}):\n{json.dumps(sub_res, indent=2)}")
        sys.exit(1)

    print(f"  OK: Dokumen {reco_name} BERHASIL DISUBMIT!")

    # 5. Buat Laporan Excel
    excel_path = "pos_sync/Injeksi_Reco_Gudang_Jakarta.xlsx"
    df_report = pd.DataFrame(items)
    df_report["erpnext_reco_no"] = reco_name
    df_report["warehouse"] = WAREHOUSE
    df_report["posting_date"] = f"{POSTING_DATE} {POSTING_TIME}"
    df_report["total_value"] = df_report["custom_qty_after"] * df_report["eresto_rate"]
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_report.to_excel(writer, sheet_name="Reco_Gudang_Jakarta", index=False)
    print(f"\nLaporan injeksi disimpan di: {excel_path}")

if __name__ == "__main__":
    main()
