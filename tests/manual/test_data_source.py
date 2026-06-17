import sys
sys.path.insert(0, '.')
from data_fetcher import DataFetcher

print('Testing multi-source data fetching...')
print('')

fetcher = DataFetcher()
result = fetcher.get_index_realtime()

print('')
print('Result:')
for k, v in result.items():
    print(f'  {k}: {v}')
    
print('')
print('Test completed!')
