"""测试逆势英雄扫描器是否能正常导入和初始化（临时调试脚本）"""

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

try:
    print("1. 正在导入模块...")
    from counter_trend_hero import CounterTrendHeroScanner
    print("   ✅ 模块导入成功")

    print("2. 正在初始化扫描器...")
    scanner = CounterTrendHeroScanner()
    print("   ✅ 扫描器初始化成功")

    print("3. 检查缓存目录...")
    print(f"   缓存目录: {scanner.cache_dir}")
    print(f"   目录存在: {scanner.cache_dir.exists()}")

    print("\n✅ 所有测试通过！代码没有问题。")

except Exception as e:
    print(f"\n❌ 错误: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
