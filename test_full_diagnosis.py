"""
Complete Diagnosis Script
Test all components work properly
"""
import sys
import traceback

print("=" * 80)
print("IronTrader Full Diagnosis")
print("=" * 80)

# Test 1: Import basic modules
print("\n[1/5] Testing basic module imports...")
try:
    from data_fetcher import DataFetcher
    print("[OK] DataFetcher imported successfully")
except Exception as e:
    print(f"[FAIL] DataFetcher import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 2: Import ChipQualityStrategy
print("\n[2/5] Testing ChipQualityStrategy import...")
try:
    from chip_quality_strategy import ChipQualityStrategy
    print("[OK] ChipQualityStrategy imported successfully")
except Exception as e:
    print(f"[FAIL] ChipQualityStrategy import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 3: Import DecisionMakerEnhanced
print("\n[3/5] Testing DecisionMakerEnhanced import...")
try:
    from decision_maker_enhanced import DecisionMakerEnhanced
    print("[OK] DecisionMakerEnhanced imported successfully")
except Exception as e:
    print(f"[FAIL] DecisionMakerEnhanced import failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 4: Initialize data fetcher
print("\n[4/5] Testing data fetcher initialization...")
try:
    data_fetcher = DataFetcher()
    print("[OK] DataFetcher initialized successfully")
except Exception as e:
    print(f"[FAIL] DataFetcher initialization failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 5: Get limit-up pool
print("\n[5/5] Testing limit-up pool fetch...")
try:
    df = data_fetcher.get_limit_up_pool()
    
    # Handle both list and DataFrame
    if df is None or (isinstance(df, list) and len(df) == 0):
        print("[WARN] Limit-up pool is empty (maybe not trading hours)")
    else:
        if isinstance(df, list):
            count = len(df)
            print(f"[OK] Successfully fetched {count} limit-up stocks")
            print(f"   Top 3:")
            for i, row in enumerate(df[:3]):
                print(f"      {row['code']} {row['name']} seal: {row['seal_amount']}")
        else:
            count = len(df)
            print(f"[OK] Successfully fetched {count} limit-up stocks")
            print(f"   Top 3:")
            for i, row in df.head(3).iterrows():
                print(f"      {row['code']} {row['name']} seal: {row['seal_amount']}")
except Exception as e:
    print(f"[FAIL] Failed to fetch limit-up pool: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 6: Initialize chip quality strategy
print("\n[6/8] Testing ChipQualityStrategy initialization...")
try:
    chip_quality = ChipQualityStrategy(data_fetcher, {
        'n_lookback': 5,
        'turnover_min': 5.0,
        'turnover_max': 25.0,
        'turnover_high': 40.0,
        'max_amplitude': 8.0,
        'shadow_threshold': 3.0
    })
    print("[OK] ChipQualityStrategy initialized successfully")
except Exception as e:
    print(f"[FAIL] ChipQualityStrategy initialization failed: {e}")
    traceback.print_exc()
    sys.exit(1)

# Test 7: Analyze single stock chip quality
if df is not None and ((isinstance(df, list) and len(df) > 0) or (not isinstance(df, list) and len(df) > 0)):
    print("\n[7/8] Testing chip quality analysis (first limit-up stock)...")
    try:
        # Get first stock
        if isinstance(df, list):
            first_stock = df[0]
            code = first_stock['code']
        else:
            code = df.iloc[0]['code']
        
        result = chip_quality.analyze_stock(code, days=30)
        
        print(f"[OK] Successfully analyzed chip quality for {code}")
        print(f"   Pass risk filter: {result['pass_risk_filter']}")
        print(f"   Total score: {result['total_score']}")
        print(f"   Recommendation: {result.get('recommendation', 'N/A')}")
        print(f"   Filter details: {result['filter_details']}")
        print(f"   Score details: {result['score_details']}")
    except Exception as e:
        print(f"[FAIL] Chip quality analysis failed: {e}")
        traceback.print_exc()
        # Don't exit, continue testing

# Test 8: Initialize decision engine
print("\n[8/8] Testing DecisionMakerEnhanced initialization...")
try:
    decision_maker = DecisionMakerEnhanced(
        enable_chip_quality=True,
        chip_config={
            'n_lookback': 5,
            'turnover_min': 5.0,
            'turnover_max': 25.0,
            'turnover_high': 40.0,
            'max_amplitude': 8.0,
            'shadow_threshold': 3.0
        }
    )
    print("[OK] DecisionMakerEnhanced initialized successfully")
    
    # Test decision
    if df is not None and ((isinstance(df, list) and len(df) > 0) or (not isinstance(df, list) and len(df) > 0)):
        print("\nTesting decision (first limit-up stock)...")
        try:
            # Get first stock
            if isinstance(df, list):
                first_stock = df[0]
                code = first_stock['code']
            else:
                code = df.iloc[0]['code']
            
            decision = decision_maker.make_decision(code)
            
            print(f"[OK] Successfully made decision for {code}")
            print(f"   Decision: {decision['decision']}")
            print(f"   Reason: {decision['reason']}")
            
            if 'chip_quality' in decision:
                print(f"   Chip quality exists: {decision['chip_quality']['pass_risk_filter']}")
        except Exception as e:
            print(f"[FAIL] Decision failed: {e}")
            traceback.print_exc()
    
except Exception as e:
    print(f"[FAIL] DecisionMakerEnhanced initialization failed: {e}")
    traceback.print_exc()
    sys.exit(1)

print("\n" + "=" * 80)
print("[SUCCESS] All tests completed!")
print("=" * 80)
