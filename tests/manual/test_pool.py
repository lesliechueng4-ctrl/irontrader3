from data_fetcher import DataFetcher

df = DataFetcher()
pool = df.get_limit_up_pool(force_refresh=True)
print(f'涨停股数量: {len(pool)}')
print(f'前5只:')
for s in pool[:5]:
    print(f"{s['code']} {s['name']} 封单:{s['seal_amount']/100000000:.2f}亿 连板:{s['limit_count']} 板块:{s['sector']}")
