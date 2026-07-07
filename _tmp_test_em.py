import requests
import time

# First: call THS concept boards (same as server does before EM call)
import akshare as ak
print("Loading THS concept boards...")
boards = ak.stock_board_concept_name_ths()
print(f"Loaded {len(boards)} THS concepts")

# Short delay
time.sleep(0.5)

# Now try the EM industry board list call
print("Loading EM industry boards...")
try:
    r = requests.get(
        "https://push2.eastmoney.com/api/qt/clist/get",
        params={
            "pn": "1", "pz": "500", "po": "1", "np": "1",
            "ut": "bd1d9ddb04089700cf9c27f6f7426281",
            "fltt": "2", "invt": "2",
            "fid": "f3", "fs": "m:90+t:2+f:!50",
            "fields": "f12,f14",
        },
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        proxies={"http": None, "https": None},
        timeout=15,
    )
    data = r.json()
    items = data.get("data", {}).get("diff", [])
    print(f"EM industries: {len(items)}")
    for item in items[:5]:
        print(f"  {item.get('f12')} {item.get('f14')}")
except Exception as e:
    print(f"Error: {type(e).__name__}: {e}")

# Also test push2his K-line
print("\nTesting push2his after push2...")
try:
    time.sleep(0.3)
    r2 = requests.get(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get",
        params={
            "secid": "90.BK1036",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61",
            "klt": "101", "fqt": "1",
            "beg": "20250601", "end": "20260707", "lmt": "3",
        },
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
        proxies={"http": None, "https": None},
        timeout=10,
    )
    klines = r2.json().get("data", {}).get("klines", [])
    print(f"K-lines: {len(klines)}")
except Exception as e:
    print(f"K-line Error: {type(e).__name__}: {e}")

print("\nDone!")
