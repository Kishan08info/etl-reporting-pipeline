# ETL-to-Report Pipeline — SaaS Subscription Revenue Reporting

A Data Analyst's end-to-end ETL pipeline: messy billing exports in,
a clean SQLite warehouse and a dashboard-ready reporting dataset out,
with MRR, churn and growth computed in SQL.

## Business question

A growing SaaS company keeps its billing data in three CSV exports —
customers, subscriptions, payments. The CFO wants one monthly revenue
report she can trust: **how fast is MRR growing, how much cash was
actually collected, and where is churn coming from?** The catch: the
exports contain duplicate payment rows, failed charges, refunds, and
annual lump-sum payments mixed in with monthly ones.

## Approach

1. **Data** (`src/generate_data.py`): 1,200 customers, 1,200 subscriptions
   and 6,269 payment rows of synthetic but realistic SaaS billing data
   (fixed seed `20261028`, fully reproducible), Jan 2025–Jun 2026, with
   defects injected deliberately: 30 duplicate payment rows, 148 failed
   charges, 22 refunds, monthly + annual (10% discount) billing cycles,
   and plan-dependent churn. Ground truth is recorded in
   `data/ground_truth.json`.
   > The data is **synthetic** — no real customers. Every number below is
   > the real output of running the included code — nothing hand-written.
2. **ETL** (`src/etl.py` + `sql/transform.sql`): raw CSVs → staging tables
   → warehouse (`dim_customers`, `dim_subscriptions`, `fact_payments`)
   → reporting marts, all in SQLite (`data/saas.sqlite`). The transform
   dedupes payments by `payment_id`, excludes failed payments from
   revenue (they move no money), and treats refunds as negative amounts.
   MRR, churn rate, MoM growth and running revenue are computed in SQL
   with window functions (`LAG`, `SUM OVER`). The pipeline is idempotent
   — marts are rebuilt from staging on every run — and it asserts its own
   cross-checks (fact rows = raw − duplicates − failed) instead of
   silently shipping wrong numbers.
3. **Reporting** (`src/report.py`): reads the marts and writes
   `results/kpi_report.json`, `results/kpi_report.md`, three charts, and
   `data/dashboard_ready.csv` — the 18-row monthly KPI table a BI tool
   (Tableau / Looker / Power BI) would connect to directly.
4. **Dashboard queries** (`sql/kpi_queries.sql`): six ready-to-run queries
   — monthly KPI trend, revenue by plan, churn by channel, top-10
   customers, failed-payment rate, and plan mix in the latest month.

## Results (real run output, `results/kpi_report.json`)

### Headline KPIs, Jan 2025 – Jun 2026

| Metric | Value |
|---|---:|
| MRR, first month → last month | $11,050 → $163,506 (+1,379.6%) |
| Avg MoM MRR growth | 17.52% |
| Active subscriptions (first → last month) | 48 → 894 |
| Total revenue collected | $1,624,082.60 |
| Total refunds | $4,088.00 |
| Avg monthly churn rate | 5.16% |
| Best revenue month | 2026-06 ($176,963.60) |
| Worst revenue month | 2025-03 ($24,413.60) |
| Top-10 customers' share of revenue | 10.8% |

### What the ETL caught

| Stage | Rows |
|---|---:|
| Raw payment rows | 6,269 |
| Duplicate payment rows removed | 30 |
| Failed payments excluded from revenue | 148 |
| Clean fact rows | 6,091 |

### Revenue by plan (whole period)

| Plan | Revenue | Share |
|---|---:|---:|
| Enterprise ($999/mo) | $726,073.20 | 44.7% |
| Pro ($249/mo) | $484,454.40 | 29.8% |
| Growth ($99/mo) | $298,564.20 | 18.4% |
| Starter ($29/mo) | $114,990.80 | 7.1% |

### Churn by acquisition channel

| Channel | Customers | Churned | Churn share | Lifetime revenue |
|---|---:|---:|---:|---:|
| Organic | 504 | 148 | 29.4% | $644,605.00 |
| Referral | 210 | 60 | 28.6% | $272,239.60 |
| Partner | 124 | 35 | 28.2% | $168,434.60 |
| Paid search | 362 | 93 | 25.7% | $538,803.40 |

## Findings worth saying in an interview

- **Cash collected is lumpy; MRR is the smooth metric.** Monthly revenue
  swings from $24k to $177k because annual plans pay 12 months upfront
  (25% of subscriptions) — the worst month, Mar 2025, had almost no
  annual renewals land. MRR normalises annual plans to their monthly
  equivalent, which is why the MRR trend, not the cash trend, is the
  growth story.
- **Enterprise is 7% of subscriptions and 44.7% of revenue.** The top-10
  customers alone are 10.8% of all revenue — the business is
  concentrated, so losing one enterprise account moves the numbers.
- **Churn barely differs by channel (25.7–29.4%).** Paid search, the
  channel you'd suspect of bringing low-intent signups, actually has the
  *lowest* churn share — so acquisition channel is not the churn lever
  here; plan is (starter churns ~6%/month vs enterprise ~1%).
- **Failed payments are a small, steady leak.** 148 failed charges out
  of 6,269 attempts (2.4%) — excluded from revenue by design, and tracked
  as its own KPI so billing health is visible instead of silently
  understating revenue.

## How to run

```bash
python3 src/run_pipeline.py   # generate -> ETL -> report (one command)
# or step by step:
python3 src/generate_data.py
python3 src/etl.py
python3 src/report.py
sqlite3 data/saas.sqlite < sql/kpi_queries.sql   # dashboard queries
```

Requires: Python 3, `pandas`, `numpy`, `matplotlib` (SQLite is built in).

## Files

| Path | What |
|---|---|
| `src/generate_data.py` | Synthetic billing-data generator (seeded, reproducible) |
| `src/etl.py` | Staging load, transform runner, cross-checks, dashboard export |
| `src/report.py` | KPI report (JSON/MD) + charts from the marts |
| `src/run_pipeline.py` | One-command end-to-end run |
| `sql/transform.sql` | Staging → warehouse → marts (CTEs + window functions) |
| `sql/kpi_queries.sql` | Six dashboard-ready queries |
| `data/` | `*_raw.csv`, `ground_truth.json`, `saas.sqlite`, `dashboard_ready.csv` |
| `results/` | `kpi_report.json`, `kpi_report.md`, `charts/*.png` |
