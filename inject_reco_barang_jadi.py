"""
Injeksi Stock Reconciliation Gudang Barang Jadi ke ERPNext Cloud (ropierpnext.frappe.cloud).
Sumber: Data Stock Opname eResto per 30 September 2026 jam 11:00:00.
Target: Gudang Barang Jadi - JURI (PT. JUARA ROTI INDONESIA).
"""

import json
import os
import sys
import time
import urllib.parse
import pandas as pd
import requests

# Load Cloud credentials
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
WAREHOUSE = "Gudang Barang Jadi - JURI"
POSTING_DATE = "2026-09-30"
POSTING_TIME = "11:00:00"
PURPOSE = "Opening Stock"
EXPENSE_ACCOUNT = "1171.000 - Pembukaan sementara - JURI"
COST_CENTER = "Main - JURI"

# Daftar 110 Item Opname Hasil Mapping & Konversi UOM
ITEMS_DATA = [
    # 1. BB0006 Apron
    {"sku": "BB0006", "name": "Apron", "eresto_qty": 77.0, "eresto_uom": "Pcs", "eresto_rate": 35000.0,
     "item_code": "PEL260006", "qty": 77.0, "rate": 35000.0, "uom": "Pcs"},
    # 2. BB0007 Apron Gempi
    {"sku": "BB0007", "name": "Apron Gempi", "eresto_qty": 45.0, "eresto_uom": "Pcs", "eresto_rate": 35000.0,
     "item_code": "PEL260005", "qty": 45.0, "rate": 35000.0, "uom": "Pcs"},
    # 3. BB0009 Balon ROPI Warna Orange (Isi 100pcs)
    {"sku": "BB0009", "name": "Balon ROPI Warna Orange (Isi 100pcs)", "eresto_qty": 100.0, "eresto_uom": "Pcs", "eresto_rate": 1063.0,
     "item_code": "PEL260097", "qty": 100.0, "rate": 1063.0, "uom": "Pcs"},
    # 4. BB0012 Beater Better
    {"sku": "BB0012", "name": "Beater Better", "eresto_qty": 4.0, "eresto_uom": "Pcs", "eresto_rate": 145612.49,
     "item_code": "PEL260008", "qty": 4.0, "rate": 145612.49, "uom": "Pcs"},
    # 5. BB0036 Capitan Roti
    {"sku": "BB0036", "name": "Capitan Roti", "eresto_qty": 5.0, "eresto_uom": "Pcs", "eresto_rate": 9147.62,
     "item_code": "PEL260011", "qty": 5.0, "rate": 9147.62, "uom": "Pcs"},
    # 6. BB0039 Coffee Spoon
    {"sku": "BB0039", "name": "Coffee Spoon", "eresto_qty": 13.0, "eresto_uom": "Pcs", "eresto_rate": 2140.36,
     "item_code": "PEL260042", "qty": 13.0, "rate": 2140.36, "uom": "Pcs"},
    # 7. BB0064 Gelas Takar 2 L
    {"sku": "BB0064", "name": "Gelas Takar 2 L", "eresto_qty": 2.0, "eresto_uom": "Pcs", "eresto_rate": 13302.0,
     "item_code": "PEL260016", "qty": 2.0, "rate": 13302.0, "uom": "Pcs"},
    # 8. BB0065 Gelas Takar 5 L
    {"sku": "BB0065", "name": "Gelas Takar 5 L", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 56900.0,
     "item_code": "PEL260063", "qty": 1.0, "rate": 56900.0, "uom": "Pcs"},
    # 9. BB0072 Gunting
    {"sku": "BB0072", "name": "Gunting", "eresto_qty": 14.0, "eresto_uom": "Pcs", "eresto_rate": 4312.48,
     "item_code": "ATK260029", "qty": 14.0, "rate": 4312.48, "uom": "Pcs"},
    # 10. BB0074 Kanebo
    {"sku": "BB0074", "name": "Kanebo", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 7151.54,
     "item_code": "PEL260018", "qty": 1.0, "rate": 7151.54, "uom": "Pcs"},
    # 11. BB0075 Kaos Gempi
    {"sku": "BB0075", "name": "Kaos Gempi", "eresto_qty": 14.0, "eresto_uom": "Pcs", "eresto_rate": 55000.0,
     "item_code": "PEL260089", "qty": 14.0, "rate": 55000.0, "uom": "Pcs"},
    # 12. BB0068 Kuas Oles Loyang 1,5'
    {"sku": "BB0068", "name": "Kuas Oles Loyang 1,5'", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 8997.56,
     "item_code": "PEL260021", "qty": 7.0, "rate": 8997.56, "uom": "Pcs"},
    # 13. BB0090 Kuas Oles Loyang 2' (deduplicated)
    {"sku": "BB0090", "name": "Kuas Oles Loyang 2'", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 9997.17,
     "item_code": "PEL260022", "qty": 7.0, "rate": 9997.17, "uom": "Pcs"},
    # 14. BB0295 Alat Test Uang Palsu
    {"sku": "BB0295", "name": "Alat Test Uang Palsu", "eresto_qty": 11.0, "eresto_uom": "Pcs", "eresto_rate": 128286.0,
     "item_code": "PEL260004", "qty": 11.0, "rate": 128286.0, "uom": "Unit"},
    # 15. BB0226 Buku Tulis
    {"sku": "BB0226", "name": "Buku Tulis", "eresto_qty": 32.0, "eresto_uom": "Pcs", "eresto_rate": 3352.11,
     "item_code": "ATK260044", "qty": 32.0, "rate": 3352.11, "uom": "Pcs"},
    # 16. BB0245 Cash Drawer
    {"sku": "BB0245", "name": "Cash Drawer", "eresto_qty": 6.0, "eresto_uom": "Unit", "eresto_rate": 311562.24,
     "item_code": "PEL260012", "qty": 6.0, "rate": 311562.24, "uom": "Unit"},
    # 17. BB0235 Dispenser Lakban
    {"sku": "BB0235", "name": "Dispenser Lakban", "eresto_qty": 3.0, "eresto_uom": "Pcs", "eresto_rate": 26133.34,
     "item_code": "ATK260035", "qty": 3.0, "rate": 26133.34, "uom": "Pcs"},
    # 18. BB0268 Dispenser Sabun Cair
    {"sku": "BB0268", "name": "Dispenser Sabun Cair", "eresto_qty": 5.0, "eresto_uom": "Pcs", "eresto_rate": 14681.16,
     "item_code": "PEL260014", "qty": 5.0, "rate": 14681.16, "uom": "Pcs"},
    # 19. BB0223 Ember 15 L
    {"sku": "BB0223", "name": "Ember 15 L", "eresto_qty": 5.0, "eresto_uom": "Pcs", "eresto_rate": 43800.0,
     "item_code": "PEL260015", "qty": 5.0, "rate": 43800.0, "uom": "Pcs"},
    # 20. BB0264 Isi Staples
    {"sku": "BB0264", "name": "Isi Staples", "eresto_qty": 16.0, "eresto_uom": "Pcs", "eresto_rate": 1545.0,
     "item_code": "ATK260046", "qty": 16.0, "rate": 1545.0, "uom": "Pack"},
    # 21. BB0236 Kalkulator
    {"sku": "BB0236", "name": "Kalkulator", "eresto_qty": 4.0, "eresto_uom": "Pcs", "eresto_rate": 22409.71,
     "item_code": "ATK260045", "qty": 4.0, "rate": 22409.71, "uom": "Pcs"},
    # 22. BB0228 Keset
    {"sku": "BB0228", "name": "Keset", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 19230.95,
     "item_code": "PEL260020", "qty": 6.0, "rate": 19230.95, "uom": "Pcs"},
    # 23. BB0270 Kuas Silikon
    {"sku": "BB0270", "name": "Kuas Silikon", "eresto_qty": 8.0, "eresto_uom": "Pcs", "eresto_rate": 12358.81,
     "item_code": "PEL260023", "qty": 8.0, "rate": 12358.81, "uom": "Pcs"},
    # 24. BB0271 Kursi Outlet
    {"sku": "BB0271", "name": "Kursi Outlet", "eresto_qty": 11.0, "eresto_uom": "Pcs", "eresto_rate": 44000.0,
     "item_code": "PEL260024", "qty": 11.0, "rate": 44000.0, "uom": "Pcs"},
    # 25. BB0229 Lap Microfiber
    {"sku": "BB0229", "name": "Lap Microfiber", "eresto_qty": 15.0, "eresto_uom": "Pcs", "eresto_rate": 4556.14,
     "item_code": "PEL260025", "qty": 15.0, "rate": 4556.14, "uom": "Pcs"},
    # 26. BB0092 Loyang
    {"sku": "BB0092", "name": "Loyang", "eresto_qty": 321.0, "eresto_uom": "Pcs", "eresto_rate": 52840.94,
     "item_code": "PEL260027", "qty": 321.0, "rate": 52840.94, "uom": "Pcs"},
    # 27. BB0093 Loyang Gempi
    {"sku": "BB0093", "name": "Loyang Gempi", "eresto_qty": 326.0, "eresto_uom": "Pcs", "eresto_rate": 25723.74,
     "item_code": "PEL260026", "qty": 326.0, "rate": 25723.74, "uom": "Pcs"},
    # 28. BB0307 Mika Display
    {"sku": "BB0307", "name": "Mika Display", "eresto_qty": 13.0, "eresto_uom": "Pcs", "eresto_rate": 10950.93,
     "item_code": "PEL260028", "qty": 13.0, "rate": 10950.93, "uom": "Pcs"},
    # 29. BB0283 Papan Menu Oultet
    {"sku": "BB0283", "name": "Papan Menu Oultet", "eresto_qty": 3.0, "eresto_uom": "Pcs", "eresto_rate": 66815.04,
     "item_code": "PEL260030", "qty": 3.0, "rate": 66815.04, "uom": "Set"},
    # 30. BB0222 Pel Lantai
    {"sku": "BB0222", "name": "Pel Lantai", "eresto_qty": 8.0, "eresto_uom": "Pcs", "eresto_rate": 195889.93,
     "item_code": "PEL260003", "qty": 8.0, "rate": 195889.93, "uom": "Pcs"},
    # 31. BB0234 Penggaris Merah
    {"sku": "BB0234", "name": "Penggaris Merah", "eresto_qty": 19.0, "eresto_uom": "Pcs", "eresto_rate": 3846.45,
     "item_code": "ATK260027", "qty": 19.0, "rate": 3846.45, "uom": "Pcs"},
    # 32. BB0266 Pompa Galon Outlet
    {"sku": "BB0266", "name": "Pompa Galon Outlet", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 40600.0,
     "item_code": "PEL260034", "qty": 1.0, "rate": 40600.0, "uom": "Pcs"},
    # 33. BB0263 Pulpen Outlet
    {"sku": "BB0263", "name": "Pulpen Outlet", "eresto_qty": 13.0, "eresto_uom": "Pcs", "eresto_rate": 1822.34,
     "item_code": "ATK260041", "qty": 13.0, "rate": 1822.34, "uom": "Pcs"},
    # 34. BB0129 Rice Bucket
    {"sku": "BB0129", "name": "Rice Bucket", "eresto_qty": 9.0, "eresto_uom": "Pcs", "eresto_rate": 506000.0,
     "item_code": "PEL260036", "qty": 9.0, "rate": 506000.0, "uom": "Pcs"},
    # 35. BB0274 Sabun Cuci Outlet
    {"sku": "BB0274", "name": "Sabun Cuci Outlet", "eresto_qty": 4.0, "eresto_uom": "Pcs", "eresto_rate": 7050.0,
     "item_code": "BHP260034", "qty": 4.0, "rate": 7050.0, "uom": "Pcs"},
    # 36. BB0273 Sabun Lantai Outlet
    {"sku": "BB0273", "name": "Sabun Lantai Outlet", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 9400.0,
     "item_code": "BHP260035", "qty": 1.0, "rate": 9400.0, "uom": "Pcs"},
    # 37. BB0220 Sapu Outlet
    {"sku": "BB0220", "name": "Sapu Outlet", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 23466.67,
     "item_code": "PEL260037", "qty": 6.0, "rate": 23466.67, "uom": "Pcs"},
    # 38. BB0269 Serokan Sampah Outlet
    {"sku": "BB0269", "name": "Serokan Sampah Outlet", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 22376.45,
     "item_code": "PEL260032", "qty": 6.0, "rate": 22376.45, "uom": "Pcs"},
    # 39. BB0231 Spidol
    {"sku": "BB0231", "name": "Spidol", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 7299.14,
     "item_code": "ATK260043", "qty": 7.0, "rate": 7299.14, "uom": "Pcs"},
    # 40. BB0272 Spons Cuci Outlet
    {"sku": "BB0272", "name": "Spons Cuci Outlet", "eresto_qty": 11.0, "eresto_uom": "Pcs", "eresto_rate": 3280.72,
     "item_code": "PEL260045", "qty": 11.0, "rate": 3280.72, "uom": "Pcs"},
    # 41. BB0306 Standing Display
    {"sku": "BB0306", "name": "Standing Display", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 15531.75,
     "item_code": "PEL260046", "qty": 1.0, "rate": 15531.75, "uom": "Pcs"},
    # 42. BB0265 Staples
    {"sku": "BB0265", "name": "Staples", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 9328.71,
     "item_code": "PEL260047", "qty": 6.0, "rate": 9328.71, "uom": "Pcs"},
    # 43. BB0275 Tempat Sendok Outlet
    {"sku": "BB0275", "name": "Tempat Sendok Outlet", "eresto_qty": 10.0, "eresto_uom": "Pcs", "eresto_rate": 11000.0,
     "item_code": "PEL260049", "qty": 10.0, "rate": 11000.0, "uom": "Pcs"},
    # 44. BB0267 Tinta Isi Ulang Outlet
    {"sku": "BB0267", "name": "Tinta Isi Ulang Outlet", "eresto_qty": 5.0, "eresto_uom": "Pcs", "eresto_rate": 17970.89,
     "item_code": "BHP260033", "qty": 5.0, "rate": 17970.89, "uom": "Pcs"},
    # 45. BB0232 Tong Sampah
    {"sku": "BB0232", "name": "Tong Sampah", "eresto_qty": 5.0, "eresto_uom": "Pcs", "eresto_rate": 81000.0,
     "item_code": "PEL260051", "qty": 5.0, "rate": 81000.0, "uom": "Pcs"},
    # 46. BB0076 Kaos Panjang
    {"sku": "BB0076", "name": "Kaos Panjang", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 55000.0,
     "item_code": "PEL260068", "qty": 1.0, "rate": 55000.0, "uom": "Pcs"},
    # 47. BB0082 Lakban Besar
    {"sku": "BB0082", "name": "Lakban Besar", "eresto_qty": 26.0, "eresto_uom": "Pcs", "eresto_rate": 12137.82,
     "item_code": "BHP260023", "qty": 26.0, "rate": 12137.82, "uom": "Pcs"},
    # 48. BB0087 Lakban Kecil
    {"sku": "BB0087", "name": "Lakban Kecil", "eresto_qty": 15.0, "eresto_uom": "Pcs", "eresto_rate": 3270.7,
     "item_code": "BHP260020", "qty": 15.0, "rate": 3270.7, "uom": "Pcs"},
    # 49. BB0114 Parutan Keju
    {"sku": "BB0114", "name": "Parutan Keju", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 2373.23,
     "item_code": "PEL260031", "qty": 7.0, "rate": 2373.23, "uom": "Pcs"},
    # 50. BB0116 Pisau Roti
    {"sku": "BB0116", "name": "Pisau Roti", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 8300.52,
     "item_code": "PEL260033", "qty": 6.0, "rate": 8300.52, "uom": "Pcs"},
    # 51. BB0118 Plastik Kresek Ukuran 17
    {"sku": "BB0118", "name": "Plastik Kresek Ukuran 17", "eresto_qty": 566.0, "eresto_uom": "Pack", "eresto_rate": 5564.29,
     "item_code": "PEL260081", "qty": 566.0, "rate": 5564.29, "uom": "Pack"},
    # 52. BB0119 Plastik Kresek Ukuran 24
    {"sku": "BB0119", "name": "Plastik Kresek Ukuran 24", "eresto_qty": 131.0, "eresto_uom": "Pack", "eresto_rate": 6004.71,
     "item_code": "PEL260080", "qty": 131.0, "rate": 6004.71, "uom": "Pack"},
    # 53. BB0128 Regulator
    {"sku": "BB0128", "name": "Regulator", "eresto_qty": 1.0, "eresto_uom": "Pcs", "eresto_rate": 126420.0,
     "item_code": "PEL260035", "qty": 1.0, "rate": 126420.0, "uom": "Pcs"},
    # 54. BB0130 Saringan Teh
    {"sku": "BB0130", "name": "Saringan Teh", "eresto_qty": 2.0, "eresto_uom": "Pcs", "eresto_rate": 10003.82,
     "item_code": "PEL260067", "qty": 2.0, "rate": 10003.82, "uom": "Pcs"},
    # 55. BB0132 Sarung Tangan Plastik
    {"sku": "BB0132", "name": "Sarung Tangan Plastik", "eresto_qty": 7.0, "eresto_uom": "Pack", "eresto_rate": 29400.15,
     "item_code": "BHP260027", "qty": 7.0, "rate": 29400.15, "uom": "Pack"},
    # 56. BB0133 Sealware Gempi
    {"sku": "BB0133", "name": "Sealware Gempi", "eresto_qty": 26.0, "eresto_uom": "Pcs", "eresto_rate": 24715.15,
     "item_code": "PEL260039", "qty": 26.0, "rate": 24715.15, "uom": "Pcs"},
    # 57. BB0134 Sedotan Teh (CONVERT: 1 Pack = 250 Pcs)
    {"sku": "BB0134", "name": "Sedotan Teh", "eresto_qty": 15.0, "eresto_uom": "Pack", "eresto_rate": 7480.72,
     "item_code": "PEL260084", "qty": 15.0 * 250, "rate": 7480.72 / 250, "uom": "Pcs"},
    # 58. BB0135 Selang Gas
    {"sku": "BB0135", "name": "Selang Gas", "eresto_qty": 8.0, "eresto_uom": "Pcs", "eresto_rate": 29875.0,
     "item_code": "PEL260040", "qty": 8.0, "rate": 29875.0, "uom": "Pcs"},
    # 59. BB0136 Sendok Es Batu
    {"sku": "BB0136", "name": "Sendok Es Batu", "eresto_qty": 3.0, "eresto_uom": "Pcs", "eresto_rate": 12890.4,
     "item_code": "PEL260041", "qty": 3.0, "rate": 12890.4, "uom": "Pcs"},
    # 60. BB0185 Botol Spray
    {"sku": "BB0185", "name": "Botol Spray", "eresto_qty": 9.0, "eresto_uom": "Pcs", "eresto_rate": 4417.33,
     "item_code": "PEL260010", "qty": 9.0, "rate": 4417.33, "uom": "Pcs"},
    # 61. BB0156 Cup Holder
    {"sku": "BB0156", "name": "Cup Holder", "eresto_qty": 2.0, "eresto_uom": "Pcs", "eresto_rate": 171261.39,
     "item_code": "PEL260013", "qty": 2.0, "rate": 171261.39, "uom": "Pcs"},
    # 62. BB0328 Jilbab Outlet
    {"sku": "BB0328", "name": "Jilbab Outlet", "eresto_qty": 71.0, "eresto_uom": "Pcs", "eresto_rate": 22807.26,
     "item_code": "SG260012", "qty": 71.0, "rate": 22807.26, "uom": "Pcs"},
    # 63. BB0313 Jug Stainless
    {"sku": "BB0313", "name": "Jug Stainless", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 29619.63,
     "item_code": "PEL260017", "qty": 6.0, "rate": 29619.63, "uom": "Pcs"},
    # 64. BB0191 Kertas Thermal (CONVERT: 1 Pack = 10 Pcs/roll)
    {"sku": "BB0191", "name": "Kertas Thermal", "eresto_qty": 37.0, "eresto_uom": "Pack", "eresto_rate": 24545.87,
     "item_code": "PEL260075", "qty": 37.0 * 10, "rate": 24545.87 / 10, "uom": "Pcs"},
    # 65. BB0314 Palu Karet Outlet
    {"sku": "BB0314", "name": "Palu Karet Outlet", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 27460.0,
     "item_code": "PEL260029", "qty": 7.0, "rate": 27460.0, "uom": "Pcs"},
    # 66. BB0296 Plastik Cup Isi 1
    {"sku": "BB0296", "name": "Plastik Cup Isi 1", "eresto_qty": 353.0, "eresto_uom": "Pack", "eresto_rate": 3915.74,
     "item_code": "PEL260078", "qty": 353.0, "rate": 3915.74, "uom": "Pack"},
    # 67. BB0297 Plastik Cup Isi 2
    {"sku": "BB0297", "name": "Plastik Cup Isi 2", "eresto_qty": 86.0, "eresto_uom": "Pack", "eresto_rate": 4043.78,
     "item_code": "PEL260079", "qty": 86.0, "rate": 4043.78, "uom": "Pack"},
    # 68. BB0137 Plastik Wrapping
    {"sku": "BB0137", "name": "Plastik Wrapping", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 33299.01,
     "item_code": "BHP260025", "qty": 6.0, "rate": 33299.01, "uom": "Pcs"},
    # 69. BB0141 Solet Gempi
    {"sku": "BB0141", "name": "Solet Gempi", "eresto_qty": 7.0, "eresto_uom": "Pcs", "eresto_rate": 700.0,
     "item_code": "PEL260043", "qty": 7.0, "rate": 700.0, "uom": "Pcs"},
    # 70. BB0142 Spatula
    {"sku": "BB0142", "name": "Spatula", "eresto_qty": 8.0, "eresto_uom": "Pcs", "eresto_rate": 17218.65,
     "item_code": "PEL260044", "qty": 8.0, "rate": 17218.65, "uom": "Pcs"},
    # 71. BB0230 Sticker Label Tom & Jerry
    {"sku": "BB0230", "name": "Sticker Label Tom & Jerry", "eresto_qty": 67.0, "eresto_uom": "Pcs", "eresto_rate": 2226.15,
     "item_code": "ATK260038", "qty": 67.0, "rate": 2226.15, "uom": "Pcs"},
    # 72. BB0143 Stirrer
    {"sku": "BB0143", "name": "Stirrer", "eresto_qty": 11000.0, "eresto_uom": "Pcs", "eresto_rate": 21.57,
     "item_code": "PEL260085", "qty": 11000.0, "rate": 21.57, "uom": "Pcs"},
    # 73. BB0152 Teko Listrik
    {"sku": "BB0152", "name": "Teko Listrik", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 170029.83,
     "item_code": "PEL260048", "qty": 6.0, "rate": 170029.83, "uom": "Unit"},
    # 74. BB0159 Timbangan
    {"sku": "BB0159", "name": "Timbangan", "eresto_qty": 12.0, "eresto_uom": "Pcs", "eresto_rate": 67323.01,
     "item_code": "PEL260050", "qty": 12.0, "rate": 67323.01, "uom": "Unit"},
    # 75. BB0160 Topi
    {"sku": "BB0160", "name": "Topi", "eresto_qty": 19.0, "eresto_uom": "Pcs", "eresto_rate": 17546.83,
     "item_code": "PEL260052", "qty": 19.0, "rate": 17546.83, "uom": "Pcs"},
    # 76. BB0161 Toples 1300L
    {"sku": "BB0161", "name": "Toples 1300L", "eresto_qty": 26.0, "eresto_uom": "Pcs", "eresto_rate": 4301.11,
     "item_code": "PEL260053", "qty": 26.0, "rate": 4301.11, "uom": "Pcs"},
    # 77. BB0162 Toples Athena
    {"sku": "BB0162", "name": "Toples Athena", "eresto_qty": 12.0, "eresto_uom": "Pcs", "eresto_rate": 5313.47,
     "item_code": "PEL260054", "qty": 12.0, "rate": 5313.47, "uom": "Pcs"},
    # 78. BB0260 Bill Holder
    {"sku": "BB0260", "name": "Bill Holder", "eresto_qty": 6.0, "eresto_uom": "Pcs", "eresto_rate": 67708.89,
     "item_code": "PEL260009", "qty": 6.0, "rate": 67708.89, "uom": "Pcs"},
    # 79. BB0171 Box Gempi (Isi 100 pcs)
    {"sku": "BB0171", "name": "Box Gempi (Isi 100 pcs)", "eresto_qty": 17800.0, "eresto_uom": "Pcs", "eresto_rate": 1942.96,
     "item_code": "PEL260069", "qty": 17800.0, "rate": 1942.96, "uom": "Pcs"},
    # 80. BB0298 Gelas 14 Oz (Isi 150 pcs)
    {"sku": "BB0298", "name": "Gelas 14 Oz (Isi 150 pcs)", "eresto_qty": 104100.0, "eresto_uom": "Pcs", "eresto_rate": 379.95,
     "item_code": "PEL260070", "qty": 104100.0, "rate": 379.95, "uom": "Pcs"},
    # 81. BB0257 Gelas Cup 9 Oz (Isi 50 pcs)
    {"sku": "BB0257", "name": "Gelas Cup 9 Oz (Isi 50 pcs)", "eresto_qty": 18900.0, "eresto_uom": "Pcs", "eresto_rate": 332.67,
     "item_code": "PEL260071", "qty": 18900.0, "rate": 332.67, "uom": "Pcs"},
    # 82. BB0066 Goodie Bag
    {"sku": "BB0066", "name": "Goodie Bag", "eresto_qty": 26725.0, "eresto_uom": "Pcs", "eresto_rate": 1369.34,
     "item_code": "PEL260072", "qty": 26725.0, "rate": 1369.34, "uom": "Pcs"},
    # 83. BB0079 Kardus Packing Ropi Beku
    {"sku": "BB0079", "name": "Kardus Packing Ropi Beku", "eresto_qty": 2700.0, "eresto_uom": "Pcs", "eresto_rate": 7599.51,
     "item_code": "PEL260073", "qty": 2700.0, "rate": 7599.51, "uom": "Pcs"},
    # 84. BB0080 Kardus Ropi Kapasitas 20 roti (25 pcs/pack)
    {"sku": "BB0080", "name": "Kardus Ropi Kapasitas 20 roti (25 pcs/pack)", "eresto_qty": 55.0, "eresto_uom": "Pcs", "eresto_rate": 4167.12,
     "item_code": "PEL260074", "qty": 55.0, "rate": 4167.12, "uom": "Pcs"},
    # 85. BB0112 Paper Bag Kapasitas 1 Roti
    {"sku": "BB0112", "name": "Paper Bag Kapasitas 1 Roti", "eresto_qty": 64400.0, "eresto_uom": "Pcs", "eresto_rate": 217.59,
     "item_code": "PEL260076", "qty": 64400.0, "rate": 217.59, "uom": "Pcs"},
    # 86. BB0102 Olesan Choco Crunchy (1 Kg) (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0102", "name": "Olesan Choco Crunchy (1 Kg)", "eresto_qty": 179.0, "eresto_uom": "kg", "eresto_rate": 49557.26,
     "item_code": "BB260043", "qty": 179.0 * 1000, "rate": 49557.26 / 1000, "uom": "g"},
    # 87. BB0071 Gula Stik
    {"sku": "BB0071", "name": "Gula Stik", "eresto_qty": 1000.0, "eresto_uom": "Pcs", "eresto_rate": 249.8,
     "item_code": "BB260039", "qty": 1000.0, "rate": 249.8, "uom": "Pcs"},
    # 88. BB0110 Olesan Tiramisu (1 Kg) (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0110", "name": "Olesan Tiramisu (1 Kg)", "eresto_qty": 23.0, "eresto_uom": "kg", "eresto_rate": 50883.77,
     "item_code": "BB260047", "qty": 23.0 * 1000, "rate": 50883.77 / 1000, "uom": "g"},
    # 89. BB0301 Bubuk Beras Kencur
    {"sku": "BB0301", "name": "Bubuk Beras Kencur", "eresto_qty": 70.0, "eresto_uom": "Pcs", "eresto_rate": 2750.0,
     "item_code": "BB260034", "qty": 70.0, "rate": 2750.0, "uom": "Sachet"},
    # 90. BB0311 Bubuk Hepi Drink Chocolate
    {"sku": "BB0311", "name": "Bubuk Hepi Drink Chocolate", "eresto_qty": 5340.0, "eresto_uom": "Sachet", "eresto_rate": 1031.27,
     "item_code": "BB260060", "qty": 5340.0, "rate": 1031.27, "uom": "Sachet"},
    # 91. BB0302 Bubuk Jahe Gula Aren
    {"sku": "BB0302", "name": "Bubuk Jahe Gula Aren", "eresto_qty": 70.0, "eresto_uom": "Pcs", "eresto_rate": 2750.0,
     "item_code": "BB260035", "qty": 70.0, "rate": 2750.0, "uom": "Sachet"},
    # 92. BB0303 Bubuk Kunir Asem
    {"sku": "BB0303", "name": "Bubuk Kunir Asem", "eresto_qty": 73.0, "eresto_uom": "Pcs", "eresto_rate": 2750.0,
     "item_code": "BB260036", "qty": 73.0, "rate": 2750.0, "uom": "Sachet"},
    # 93. BB0304 Bubuk Susu Jahe
    {"sku": "BB0304", "name": "Bubuk Susu Jahe", "eresto_qty": 70.0, "eresto_uom": "Pcs", "eresto_rate": 2750.0,
     "item_code": "BB260037", "qty": 70.0, "rate": 2750.0, "uom": "Sachet"},
    # 94. BB0341 Coffee Classic 120g (CONVERT: 1 Pack = 120 g)
    {"sku": "BB0341", "name": "Coffee Classic 120g", "eresto_qty": 305.0, "eresto_uom": "Pack", "eresto_rate": 47675.68,
     "item_code": "BB260032", "qty": 305.0 * 120, "rate": 47675.68 / 120, "uom": "g"},
    # 95. BB0340 Coffee Latte 500g (CONVERT: 1 Pack = 500 g)
    {"sku": "BB0340", "name": "Coffee Latte 500g", "eresto_qty": 929.0, "eresto_uom": "Pack", "eresto_rate": 53237.83,
     "item_code": "BB260031", "qty": 929.0 * 500, "rate": 53237.83 / 500, "uom": "g"},
    # 96. BB0042 Crispy Ball 500 gram (CONVERT: 1 Pack = 500 g)
    {"sku": "BB0042", "name": "Crispy Ball 500 gram", "eresto_qty": 21.0, "eresto_uom": "Pack", "eresto_rate": 27886.17,
     "item_code": "BB260048", "qty": 21.0 * 500, "rate": 27886.17 / 500, "uom": "g"},
    # 97. BB0342 Dark Cocoa Drink 1Kg (CONVERT: 1 Pack = 1000 g)
    {"sku": "BB0342", "name": "Dark Cocoa Drink 1Kg", "eresto_qty": 421.0, "eresto_uom": "Pack", "eresto_rate": 78576.56,
     "item_code": "BB260033", "qty": 421.0 * 1000, "rate": 78576.56 / 1000, "uom": "g"},
    # 98. BB0305 Gula Cair Sachet (Isi 100 Sachet)
    {"sku": "BB0305", "name": "Gula Cair Sachet (Isi 100 Sachet)", "eresto_qty": 5700.0, "eresto_uom": "Sachet", "eresto_rate": 265.31,
     "item_code": "BB260038", "qty": 5700.0, "rate": 265.31, "uom": "Sachet"},
    # 99. BB0329 Jasmine Green Tea 750g (CONVERT: 1 Pack = 750 g)
    {"sku": "BB0329", "name": "Jasmine Green Tea 750g", "eresto_qty": 506.0, "eresto_uom": "Pack", "eresto_rate": 63744.13,
     "item_code": "BB260030", "qty": 506.0 * 750, "rate": 63744.13 / 750, "uom": "g"},
    # 100. BB0081 Keju Chedar (CONVERT: 1 Pcs blok = 250 g)
    {"sku": "BB0081", "name": "Keju Chedar", "eresto_qty": 204.0, "eresto_uom": "Pcs", "eresto_rate": 10874.19,
     "item_code": "BB260040", "qty": 204.0 * 250, "rate": 10874.19 / 250, "uom": "g"},
    # 101. BB0322 Kopi Hitam @6gr (Isi 20 Sachet)
    {"sku": "BB0322", "name": "Kopi Hitam @6gr (Isi 20 Sachet)", "eresto_qty": 4930.0, "eresto_uom": "Pcs", "eresto_rate": 723.5,
     "item_code": "BB260061", "qty": 4930.0, "rate": 723.5, "uom": "Pcs"},
    # 102. BB0096 Meises Coklat 1kg (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0096", "name": "Meises Coklat 1kg", "eresto_qty": 15.0, "eresto_uom": "kg", "eresto_rate": 23557.57,
     "item_code": "BB260041", "qty": 15.0 * 1000, "rate": 23557.57 / 1000, "uom": "g"},
    # 103. BB0100 Minyak Oles 1 Kg (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0100", "name": "Minyak Oles 1 Kg", "eresto_qty": 18.0, "eresto_uom": "kg", "eresto_rate": 21996.93,
     "item_code": "BB260042", "qty": 18.0 * 1000, "rate": 21996.93 / 1000, "uom": "g"},
    # 104. BB0103 Olesan Dark Choco (1 Kg) (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0103", "name": "Olesan Dark Choco (1 Kg)", "eresto_qty": 121.0, "eresto_uom": "kg", "eresto_rate": 57081.0,
     "item_code": "BB260044", "qty": 121.0 * 1000, "rate": 57081.0 / 1000, "uom": "g"},
    # 105. BB0105 Olesan Margarine (CONVERT: 1 Pcs = 250 g)
    {"sku": "BB0105", "name": "Olesan Margarine", "eresto_qty": 41.0, "eresto_uom": "Pcs", "eresto_rate": 7372.37,
     "item_code": "BB260045", "qty": 41.0 * 250, "rate": 7372.37 / 250, "uom": "g"},
    # 106. BB0174 Olesan Pastry (CONVERT: 1 Pcs = 50 g)
    {"sku": "BB0174", "name": "Olesan Pastry", "eresto_qty": 360.0, "eresto_uom": "Pcs", "eresto_rate": 1708.61,
     "item_code": "BB260046", "qty": 360.0 * 50, "rate": 1708.61 / 50, "uom": "g"},
    # 107. BB0117 Plastik Alas Gempi
    {"sku": "BB0117", "name": "Plastik Alas Gempi", "eresto_qty": 37205.0, "eresto_uom": "Pcs", "eresto_rate": 106.67,
     "item_code": "PEL260077", "qty": 37205.0, "rate": 106.67, "uom": "Pcs"},
    # 108. BB0120 Plastik Krim
    {"sku": "BB0120", "name": "Plastik Krim", "eresto_qty": 302.0, "eresto_uom": "Pcs", "eresto_rate": 395.54,
     "item_code": "BB260019", "qty": 302.0, "rate": 395.54, "uom": "Pcs"},
    # 109. BB0122 Plastik Seal Roti
    {"sku": "BB0122", "name": "Plastik Seal Roti", "eresto_qty": 418000.0, "eresto_uom": "Pcs", "eresto_rate": 97.45,
     "item_code": "PEL260083", "qty": 418000.0, "rate": 97.45, "uom": "Pcs"},
    # 110. BB0145 Susu Bubuk untuk Campuran Minuman (1 Kg) (CONVERT: 1 kg = 1000 g)
    {"sku": "BB0145", "name": "Susu Bubuk untuk Campuran Minuman (1 Kg)", "eresto_qty": 56.0, "eresto_uom": "kg", "eresto_rate": 62565.05,
     "item_code": "BB260062", "qty": 56.0 * 1000, "rate": 62565.05 / 1000, "uom": "g"},
]

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

def main():
    print(f"=== Menyiapkan Injeksi Stock Reconciliation: {WAREHOUSE} ===")
    print(f"Total item yang akan diinjeksi: {len(ITEMS_DATA)}")

    # 1. Cek keberadaan semua Item Code di ERPNext Cloud
    print("\n[1/4] Memeriksa keberadaan 110 Item Code di ERPNext...")
    item_codes = [it["item_code"] for it in ITEMS_DATA]
    
    # Batch query or verify items
    missing_items = []
    for it in ITEMS_DATA:
        code = it["item_code"]
        st, res = req("GET", f"/api/resource/Item/{urllib.parse.quote(code)}")
        if st != 200:
            missing_items.append(code)
            print(f"  MISSING: {code} ({it['name']})")
        else:
            # Check default inventory account for Company
            doc = res.get("data", {})
            defaults = doc.get("item_defaults", [])
            has_company_default = any(d.get("company") == COMPANY for d in defaults)
            if not has_company_default:
                # Add default inventory account
                # Determine account based on group
                grp = doc.get("item_group", "")
                acc = "1141.000 - Finished Goods - JURI"
                if "Bahan Baku" in grp:
                    acc = "1143.000 - Raw Material - JURI"
                elif "Perlengkapan" in grp:
                    acc = "1141.000 - Finished Goods - JURI"
                
                print(f"  Menambahkan Item Default untuk {code} (Group: {grp}, Acc: {acc})...")
                defaults.append({
                    "company": COMPANY,
                    "default_warehouse": WAREHOUSE,
                    "default_inventory_account": acc
                })
                put_st, put_res = req("PUT", f"/api/resource/Item/{urllib.parse.quote(code)}", {
                    "item_defaults": defaults
                })
                if put_st != 200:
                    print(f"    Gagal update defaults {code}: {put_res}")

    if missing_items:
        print(f"\nFATAL: Terdapat {len(missing_items)} item yang tidak ditemukan di ERPNext: {missing_items}")
        sys.exit(1)
    print("  OK: Semua 110 item terdaftar dan valid di ERPNext Cloud.")

    # 2. Susun dokumen Stock Reconciliation
    print(f"\n[2/4] Menyusun dokumen Stock Reconciliation ({POSTING_DATE} {POSTING_TIME})...")
    reco_items = []
    total_reco_value = 0.0

    for it in ITEMS_DATA:
        code = it["item_code"]
        qty = round(it["qty"], 4)
        rate = round(it["rate"], 4)
        val = qty * rate
        total_reco_value += val

        e_uom = it["eresto_uom"]
        e_qty = round(it["eresto_qty"], 4)
        e_rate = round(it["eresto_rate"], 4)
        factor = round(qty / e_qty, 4) if e_qty != 0 else 1.0

        reco_items.append({
            "item_code": code,
            "warehouse": WAREHOUSE,
            "qty": qty,
            "valuation_rate": rate,
            "uom": it["uom"],
            "custom_uom": e_uom,
            "custom_conversion_factor": factor,
            "custom_qty_after": e_qty,
            "custom_qty_before": 0.0,
            "custom_qty_difference_per_uom": e_qty,
            "custom_valuation_rate_per_uom": e_rate,
        })

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

    print(f"  Total items: {len(reco_items)}")
    print(f"  Total perkiraan nilai stok: Rp {total_reco_value:,.2f}")

    # 3. POST Draft Stock Reconciliation
    print(f"\n[3/4] Mengirim dokumen Stock Reconciliation (POST Draft)...")
    st, res = req("POST", "/api/resource/Stock Reconciliation", payload)
    if st != 200:
        print(f"  GAGAL POST Stock Reconciliation ({st}):\n{json.dumps(res, indent=2)}")
        sys.exit(1)

    reco_doc = res.get("data", {})
    reco_name = reco_doc.get("name")
    print(f"  OK: Berhasil membuat Draft Stock Reconciliation: {reco_name}")

    # 4. Submit Stock Reconciliation (docstatus = 1)
    print(f"\n[4/4] Men-submit dokumen {reco_name} (docstatus = 1)...")
    sub_st, sub_res = req("PUT", f"/api/resource/Stock Reconciliation/{urllib.parse.quote(reco_name)}", {
        "docstatus": 1
    })
    if sub_st != 200:
        print(f"  GAGAL SUBMIT Stock Reconciliation ({sub_st}):\n{json.dumps(sub_res, indent=2)}")
        sys.exit(1)

    print(f"  OK: Dokumen {reco_name} BERHASIL DISUBMIT!")

    # 5. Buat Laporan Excel
    excel_path = "pos_sync/Injeksi_Reco_Barang_Jadi.xlsx"
    df_report = pd.DataFrame(ITEMS_DATA)
    df_report["converted_qty"] = df_report["qty"]
    df_report["converted_rate"] = df_report["rate"]
    df_report["total_value"] = df_report["converted_qty"] * df_report["converted_rate"]
    df_report["erpnext_reco_no"] = reco_name
    df_report["warehouse"] = WAREHOUSE
    df_report["posting_date"] = f"{POSTING_DATE} {POSTING_TIME}"
    
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_report.to_excel(writer, sheet_name="Stock_Reco_Barang_Jadi", index=False)
    print(f"\nLaporan injeksi disimpan di: {excel_path}")

if __name__ == "__main__":
    main()
