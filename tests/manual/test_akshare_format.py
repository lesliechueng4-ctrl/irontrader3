"""
测试AKShare返回的数据格式
"""
from akshare import stock_zh_a_hist

print("Testing AKShare API for 002922")
print("=" * 60)

try:
    df = stock_zh_a_hist(symbol="sz002922", period="daily", adjust="qfq")
    
    print(f"\nTotal rows: {len(df)}")
    print(f"Columns: {df.columns.tolist()}")
    print(f"Column types:")
    for col in df.columns:
        print(f"  {col}: {df[col].dtype}")
    
    print(f"\nFirst 3 rows:")
    for i in range(min(3, len(df))):
        print(f"\nRow {i+1}:")
        for col in df.columns:
            val = df.iloc[i][col]
            print(f"  {col}: {val}")
    
    print(f"\nLast 3 rows:")
    for i in range(max(0, len(df)-3), len(df)):
        print(f"\nRow {i+1}:")
        for col in df.columns:
            val = df.iloc[i][col]
            print(f"  {col}: {val}")
    
except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
