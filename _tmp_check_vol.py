import tushare as ts
ts.set_token(os.environ.get('TUSHARE_TOKEN', ''))
pro = ts.pro_api()

# Check a known stock: 000001.SZ daily bar for 20260620
daily = pro.daily(ts_code="000001.SZ", trade_date="20260620")
if daily is not None and not daily.empty:
    print(f"Daily bar vol: {daily.iloc[0]['vol']} (单位: 手)")

# Check realtime quote
rt = ts.realtime_quote(ts_code="000001.SZ", src="sina")
if rt is not None and not rt.empty:
    vol_raw = float(rt.iloc[0]["VOLUME"])
    price = float(rt.iloc[0]["PRICE"])
    amount = float(rt.iloc[0]["AMOUNT"])
    print(f"Realtime VOLUME: {vol_raw}")
    print(f"Realtime PRICE: {price}")
    print(f"Realtime AMOUNT: {amount}")
    # If VOLUME is in 股, VOLUME/100 should be roughly daily vol
    # If VOLUME is in 手, VOLUME should be roughly daily vol
    print(f"VOLUME/100 = {vol_raw/100:.0f} (if 股->手)")
    print(f"Daily vol was: {daily.iloc[0]['vol'] if daily is not None else 'N/A'}")
    # Cross-check: AMOUNT / PRICE / 100 = vol in 手
    # AMOUNT is in 元, PRICE in 元/股
    # shares = AMOUNT / PRICE
    # 手 = shares / 100
    shares = amount / price
    lots = shares / 100
    print(f"Cross-check: AMOUNT/PRICE/100 = {lots:.0f} 手")
    print(f"Conclusion: VOLUME is in {'股 (shares)' if abs(vol_raw - shares) < abs(vol_raw/100 - shares) else '手 (lots)'}")
