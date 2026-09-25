# L1 数据层运维脚本 — 部署说明

> 交付对象：**家里 Hermes**（24h 常驻，负责日常定时运维）
> 编制方：办公室 Hermes（负责建库 + 验证 + 编脚本 + 随时辅助）
> 版本：2026-09-25 v1.0（已在办公室实测双模式全绿）

---

## 1. 这个脚本干什么

把 L1 宏观的 **18 个指标**从各数据源增量拉取，校验后写入 **NAS PostgreSQL 主库**（`quant-pg:100.76.208.125:5432`）。

**它不做的事**：不重写历史（只 append）、不做因子计算（那是 L2/L3 的事）、不碰办公室的 L0 CSV（pg 模式下）。

### 18 个指标 × 来源

| 指标 | 来源 | 频率 |
|---|---|---|
| `hs300_pe_ttm` | akshare 中证官方 `stock_zh_index_hist_csindex('000300')` | 日 |
| `treasury_y1` / `treasury_y10` | 星耀 `get_treasury_yield`（中债） | 日 |
| `us10y` | akshare `bond_zh_us_rate`（东财） | 日 |
| `usdcny` | akshare `currency_boc_safe`（SAFE 官方中间价） | 日 |
| `oil` | **FRED** `DCOILBRENTEU`（EIA 布伦特，**需代理**） | 日 |
| `margin_balance` / `margin_purchase` | 星耀 `get_margin_summary`（三所两融） | 日 |
| `float_cap` | 星耀 `get_industry_daily(['801003.SI'])`（申万A指流通市值） | 日 |
| `pmi` | akshare `macro_china_pmi`（东财转载统计局） | 月 |
| `cpi_yoy` / `cpi_mom` / `cpi_ytd` | akshare `macro_china_cpi` | 月 |
| `ppi_yoy` / `ppi_ytd` | akshare `macro_china_ppi` | 月 |
| `m1_yoy` / `m2_yoy` | akshare `macro_china_money_supply` | 月 |
| `shrzgm` | akshare `macro_china_shrzgm`（**2026-04 后停更**，见 §6） | 月 |

---

## 2. 部署步骤

### 2.1 目录

```
l1_ops/
├── pit_init.py       # 必须同目录！指标注册表(单一事实源, 从办公室同步)
├── l1_update.py      # 运维脚本
└── README.md
```

> ⚠️ `pit_init.py` 是**唯一的指标注册表**（18 指标的 freq/lag/值域/源定义），运维脚本 import 它取发布日映射。**两份文件必须同版本**——办公室更新 `pit_init.py` 后，家里需同步。

### 2.2 依赖

```bash
# Python 3.12+
pip install akshare pandas psycopg2-binary tgw AmazingData
# 星耀 SDK (若 pip 源无): 从 https://gitee.com/cgs2026/xysz clone 后
#   pip install xysz_tools/AmazingData-*.whl xysz_tools/tgw-*.whl
```

### 2.3 环境变量（建议写进 `~/.bashrc` 或 cron 的 env）

```bash
export L1_PG_DSN="host=100.76.208.125 port=5432 user=postgres password=<从wiki获取> dbname=quant connect_timeout=20"
export AD_USERNAME="<从wiki获取>"
export AD_PASSWORD="<从wiki获取>"
export AD_HOST="101.230.159.235"
export AD_PORT="8600"
# FRED(oil) 直连 —— 办公室无代理实测可达, 家里/NAS 更没问题; 勿配 http_proxy/https_proxy(会影响 akshare 直连)
```

### 2.4 首次连通性验证（**部署后必做，逐条确认**）

```bash
# ① NAS PG (Tailscale)
psql "host=100.76.208.125 port=5432 user=postgres password=<从wiki获取> dbname=quant" \
     -c "SELECT count(*) FROM l1_observation;"
# 期望: 47085 行 (2026-09-25 基线)

# ② 星耀 AmazingData (单点登录, 注意别和办公室同时在线)
python -c "import AmazingData as ad; ad.login(username='<从wiki获取>',password='<从wiki获取>',host='101.230.159.235',port=8600); print('星耀 OK')"

# ③ akshare 国内源
python -c "import akshare as ak; print(ak.macro_china_pmi().head(2))"

# ④ FRED (直连)
python -c "import urllib.request; print(urllib.request.urlopen('https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU&cosd=2026-09-01',timeout=60).read(200))"

# ⑤ 全指标 dry-run (只拉不写, 验证 18 个采集器)
python l1_update.py --all --state-from pg --dry-run --pit-init ./pit_init.py
# 期望: 完成: 成功 12 文件 / 失败 0
```

---

## 3. 运行

```bash
python l1_update.py --all   --state-from pg    # 全部 18 指标
python l1_update.py --daily  --state-from pg   # 只日频 9 指标
python l1_update.py --monthly --state-from pg  # 只月频 9 指标
python l1_update.py --only us10y,usdcny --state-from pg   # 指定指标
```

**两种模式**（同一份代码）：

| 模式 | 增量起点 | 是否写 CSV | 谁用 |
|---|---|---|---|
| `--state-from local` | 本地 L0 CSV | ✅ 维护 CSV | 办公室 |
| `--state-from pg` | **NAS PG** | ❌ 不碰 CSV | **家里** |

> 家里用 `pg` 模式：起点从 NAS PG 查 `max(period_date)`，新数据只 UPSERT 到 PG。**不需要本地 CSV**。

**退出码**：`0`=全成功；`1`=有指标失败（其它指标仍已落库，看日志定位）。

---

## 4. 定时（推荐配置）

**每交易日 17:30 跑一次全量**（收盘 + 星耀两融数据发布后）：

```cron
# crontab -e   (家里 Hermes 的 WSL)
30 17 * * 1-5 cd /root/l1_ops && /usr/bin/python3 l1_update.py --all --state-from pg --pit-init ./pit_init.py >> logs/l1_update.log 2>&1
```

> 月频指标也在这次运行里检查（无新数据自动跳过）。月频发布窗口是月初（PMI 月末当日、CPI/PPI 次月 14 日内、M1/M2/社融次月 17 日内），每日检查即可覆盖。
>
> 若想省一次 akshare 调用，可拆两条 cron：日频每交易日 17:30，月频每月 1–20 日 18:30。

**日志**：建议 `mkdir -p /root/l1_ops/logs`，`logrotate` 或定期清理。

**可选：结果推送飞书**（脚本退出码 + 新增行数摘要），如需请告知办公室 Hermes 加。

---

## 5. 故障处理

| 现象 | 原因 | 处理 |
|---|---|---|
| 某个指标 `!! FAILED` | 源结构变了 / 网络 / 星耀掉线 | 看 `traceback`；**其它指标已落库，不受影响**；修好后**直接重跑**（幂等，不会重复） |
| `星耀` 报错 | 单点登录被踢（办公室同时在用） | 串行等待；或错峰运行 |
| `oil` 失败 | 偶发网络 | 重试；确认未配代理环境变量 |
| PG 连不上 | Tailscale 掉线 | `tailscale status`；重连后重跑 |
| 全部"无新数据" | 正常（源未更新/非交易日） | 无需处理 |

**安全性**：脚本只 `INSERT ... ON CONFLICT DO NOTHING`，**永不 UPDATE/DELETE**。跑 100 遍和跑 1 遍结果相同（幂等）。

---

## 6. 已知限制（需人工介入）

1. **`shrzgm`（社融）akshare 已停更**（最后 2026-04）。之后月份的补数需**央行《金融统计数据报告》**（官网前 N 月累计差分）。脚本目前**只告警不自动补**——若看到 `shrzgm` 长期无新数据，需人工核对央行报告后补 CSV/PG。
2. **`oil` 源（FRED）通常滞后 1–3 个工作日**，"无新数据"是正常的。
3. **星耀单点登录**：同一账号同时只能一个连接。办公室与家里**不要同时跑**。
4. **值域护栏**：新增值超出登记值域会**拒绝写入**（防源污染）。若确认是真实值变化（如汇率破 9.0），需先在 `pit_init.py` 更新值域并经复检流程，再跑。

---

## 7. 数据现状基线（2026-09-25）

- NAS PG `quant-pg` 表：`l1_indicator_meta`(18) / `l1_observation`(47085) / `l1_methodology_version`(14)
- 日频最新期：**2026-09-24**；月频最新期：**2026-08-31**（pmi 2026-08-01）
- 库大小 ~13 MB，建连 ~3.3s

## 8. 变更纪律

- **改代码 → 必须复检**（qucoder 审逻辑 + infomana 验执行）→ 用户终检
- **改 `pit_init.py` 注册表 → 家里必须同步**，否则发布日/值域口径分叉
- 任何改动（补数/新指标/值域调整）都会使既有验证结论失效，需重走流程
