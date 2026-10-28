"""ETL: load raw CSVs into staging, run sql/transform.sql, export marts.

Usage: python3 src/etl.py
Writes: data/saas.sqlite (staging + dims + facts + marts),
        data/dashboard_ready.csv (monthly KPI table, BI-ready)
Prints row counts at each stage so the run is auditable.
"""
import sqlite3
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "saas.sqlite"


def main():
    if DB.exists():
        DB.unlink()
    con = sqlite3.connect(DB)

    counts = {}
    for table in ("customers", "subscriptions", "payments"):
        df = pd.read_csv(ROOT / "data" / f"{table}_raw.csv", dtype=str,
                         keep_default_na=False)
        # payments.amount must stay numeric
        if table == "payments":
            df["amount"] = pd.to_numeric(df["amount"])
        df.to_sql(f"stg_{table}", con, index=False)
        counts[f"stg_{table}"] = len(df)

    sql = (ROOT / "sql" / "transform.sql").read_text()
    con.executescript(sql)
    con.commit()

    for table in ("dim_customers", "dim_subscriptions", "fact_payments",
                  "mart_monthly_kpis", "mart_plan_monthly",
                  "mart_churn_by_channel"):
        counts[table] = con.execute(
            f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    # Dashboard-ready export: the monthly KPI table a BI tool would read.
    kpis = pd.read_sql("SELECT * FROM mart_monthly_kpis ORDER BY month", con)
    kpis.to_csv(ROOT / "data" / "dashboard_ready.csv", index=False)

    # Cross-checks (fail loudly instead of shipping wrong numbers)
    raw_payments = counts["stg_payments"]
    fact_rows = counts["fact_payments"]
    dupes_removed = con.execute(
        "SELECT COUNT(*) - COUNT(DISTINCT payment_id) FROM stg_payments"
    ).fetchone()[0]
    failed = con.execute(
        "SELECT COUNT(*) FROM stg_payments WHERE status='failed'"
    ).fetchone()[0]
    assert fact_rows == raw_payments - dupes_removed - failed, (
        f"fact_payments {fact_rows} != raw {raw_payments} "
        f"- dupes {dupes_removed} - failed {failed}")
    assert kpis["month"].is_unique, "duplicate months in KPI mart"
    assert (kpis["active_subs"] > 0).all(), "a month has zero active subs"

    con.close()
    for k, v in counts.items():
        print(f"{k}: {v}")
    print(f"cross-checks passed: {dupes_removed} duplicate payment rows "
          f"removed, {failed} failed payments excluded from revenue")
    print(f"dashboard_ready.csv: {len(kpis)} monthly rows")


if __name__ == "__main__":
    main()
