import sys
sys.path.insert(0, r'C:\new_tdx64\PYPlugins')
from TQ import TQcenter

tq = TQcenter()
tq.initialize(r'C:\new_tdx64\PYPlugins\user')

# SC42 = 沪深港通成交金额
df = tq.get_index_bars(
    index_code='SC42',
    freq='d',
    start_time='2026-05-20',
    end_time='2026-05-30',
    fields=['date', 'amount']
)
print(df)
tq.close()
