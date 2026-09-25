# dicquant

**L1~L3 框架量化** — 数据层 / 因子层 / 策略层代码库。

## 目录

| 目录 | 内容 |
|---|---|
| `l1_ops/` | **L1 宏观数据层运维** —— 18 指标增量采集 → 护栏校验 → NAS PostgreSQL 主库 |

## l1_ops 快速上手

```bash
# 家里 Hermes (增量起点从 NAS PG 取, 只写 PG)
python l1_ops/l1_update.py --all --state-from pg

# 办公室 (增量起点从本地 L0 CSV 取, 同时维护 CSV)
python l1_ops/l1_update.py --all --state-from local --raw-dir /path/to/raw_data

# 试跑(不落盘不入库)
python l1_ops/l1_update.py --all --state-from pg --dry-run
```

详细部署步骤见 [`l1_ops/README.md`](l1_ops/README.md)。

## 架构要点

- **主库**：NAS PostgreSQL（`quant` 库，三表 `l1_indicator_meta` / `l1_observation` / `l1_methodology_version`）
- **L0 原始层**：一源一文件 CSV，办公室维护；家里模式零 CSV 依赖
- **PIT 语义**：每行带 `period_date` / `announcement_date` / `vintage_date` 三时间轴，禁 bfill/ffill
- **分工**：办公室 Hermes 负责建库 / 验证 / 编脚本；家里 Hermes 负责日常定时执行

## 相关文档

设计文档与状态台账不在本库，见本地 wiki `量化开发/`（`状态.md` / `框架.md` / `数据源/`）。
