import akshare as ak
import pandas as pd

stocks = ['300476.SZ', '600869.SH', '301035.SZ', '001203.SZ', '300570.SZ', '002281.SZ', '300223.SZ']

# Get stock names
print("=== Stock Names ===")
for s in stocks:
    code = s.split('.')[0]
    try:
        info = ak.stock_individual_info_em(symbol=code)
        name = info[info['item'] == '股票简称']['value'].values[0]
        industry = info[info['item'] == '行业']['value'].values[0] if '行业' in info['item'].values else 'N/A'
        print(f"{s} | {name} | {industry}")
    except Exception as e:
        print(f"{s} | ERROR: {e}")

print("\n=== Q1 2026 Financial Data (already reported) ===")
# Get Q1 2026 financial data
for s in stocks:
    code = s.split('.')[0]
    try:
        # Try to get the latest quarterly financial data
        fin = ak.stock_financial_abstract_ths(symbol=code, indicator="按年度")
        if fin is not None and not fin.empty:
            # Show latest 2 rows
            latest = fin.tail(2)
            for _, row in latest.iterrows():
                print(f"{s}: {row.to_dict()}")
        else:
            print(f"{s}: no financial data")
    except Exception as e:
        print(f"{s}: ERROR - {e}")
