"""
Test API endpoints with Python
"""
import requests
import json

print("=" * 80)
print("Testing IronTrader API")
print("=" * 80)

# Test 1: Market State
print("\n[1] Testing /api/market-state...")
try:
    response = requests.get('http://127.0.0.1:5002/api/market-state', timeout=10)
    data = response.json()
    print(f"Status Code: {response.status_code}")
    print(f"Success: {data.get('success')}")
    if data.get('success'):
        state = data.get('data', {})
        print(f"Market State: {state.get('state')}")
        print(f"Can Trade: {state.get('can_trade')}")
        print(f"Suggestion: {state.get('suggestion')}")
except Exception as e:
    print(f"Error: {e}")

# Test 2: Hot Sectors
print("\n[2] Testing /api/hot-sectors...")
try:
    response = requests.get('http://127.0.0.1:5002/api/hot-sectors', timeout=10)
    data = response.json()
    print(f"Status Code: {response.status_code}")
    print(f"Success: {data.get('success')}")
    if data.get('success'):
        sectors = data.get('data', [])
        print(f"Sector Count: {len(sectors)}")
        for i, sector in enumerate(sectors[:3]):
            print(f"   {i+1}. {sector['name']}: {sector['count']} stocks")
except Exception as e:
    print(f"Error: {e}")

# Test 3: ZT Pool
print("\n[3] Testing /api/zt-pool...")
try:
    response = requests.get('http://127.0.0.1:5002/api/zt-pool', timeout=10)
    data = response.json()
    print(f"Status Code: {response.status_code}")
    print(f"Success: {data.get('success')}")
    if data.get('success'):
        stocks = data.get('data', [])
        print(f"Stock Count: {len(stocks)}")
        print("\nTop 5 stocks:")
        for i, stock in enumerate(stocks[:5]):
            print(f"\n   {i+1}. {stock['code']} {stock['name']}")
            print(f"      Decision: {stock['decision']}")
            print(f"      Seal: {stock['seal_amount']}")
            print(f"      Limit Count: {stock['limit_count']}")
            
            # Chip quality info
            if 'chip_quality' in stock and stock['chip_quality']:
                cq = stock['chip_quality']
                print(f"      Chip Quality:")
                print(f"         Pass: {cq['pass_risk_filter']}")
                print(f"         Score: {cq['total_score']}")
                print(f"         Rec: {cq.get('recommendation', 'N/A')}")
except Exception as e:
    print(f"Error: {e}")

# Test 4: Root page
print("\n[4] Testing / (root page)...")
try:
    response = requests.get('http://127.0.0.1:5002/', timeout=10)
    print(f"Status Code: {response.status_code}")
    print(f"Content Length: {len(response.text)} bytes")
    if 'IronTrader' in response.text or '涨停股池' in response.text:
        print("Page contains expected content")
    else:
        print("Page content may not be loaded correctly")
except Exception as e:
    print(f"Error: {e}")

print("\n" + "=" * 80)
print("API Testing Complete!")
print("=" * 80)
print("\nAccess the web interface at: http://localhost:5002")
