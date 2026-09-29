"""xtquant 快速测试脚本"""
from xtquant import xtdata

import xtquant; print('xtquant 版本:', xtquant.__version__)

# 测试实时行情
print('\n=== 实时行情测试 ===')
quotes = xtdata.get_full_tick(['600519.SH'])
if quotes:
    stock = list(quotes.keys())[0]
    print(f'✅ {stock}')
    print(f'   最新价: {quotes[stock]["lastPrice"]}')
    print(f'   涨跌幅: {quotes[stock]["pctChanged"]}')
else:
    print('❌ 实时行情为空')

# 测试日线
print('\n=== 日线测试 ===')
data = xtdata.get_market_data_ex(
    field_list=['open','high','low','close','volume'],
    stock_list=['600519.SH'],
    period='1d',
    start_time='20260801',
    end_time='20260824',
    fill_data=True,
    dividend_type='front'
)
if '600519.SH' in data and data['600519.SH'] is not None:
    df = data['600519.SH']
    print(f'✅ 日线数据: {len(df)}条')
    print(f'   范围: {df.index[0]} ~ {df.index[-1]}')
    print(f'   最新收盘: {df["close"].iloc[-1]}')
else:
    print('❌ 日线数据为空')

# 测试板块
print('\n=== 板块数据测试 ===')
sectors = xtdata.get_sector_list()
hs300 = [s for s in sectors if '沪深300' in s]
if hs300:
    stocks = xtdata.get_stock_list_in_sector(hs300[0])
    print(f'✅ {hs300[0]}: {len(stocks)}支成分股')
    print(f'   前5: {stocks[:5]}')
else:
    print('❌ 板块数据为空')

# 测试交易日历
print('\n=== 交易日历测试 ===')
dates = xtdata.get_trading_dates('SH', start_time='20260801', end_time='20260824')
print(f'✅ 交易日: {len(dates)}天, {dates[:3]}...{dates[-3:]}')