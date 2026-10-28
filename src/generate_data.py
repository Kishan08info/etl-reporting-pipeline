"""Generate synthetic SaaS billing data: customers, subscriptions, payments.

Deterministic (seed 20261028). Deliberately messy in the ways billing
exports are messy: duplicate payment rows, failed payments, refunds,
annual lump-sum payments, and subscriptions that churn mid-stream.

Outputs (data/):
  customers_raw.csv, subscriptions_raw.csv, payments_raw.csv,
  ground_truth.json (defect counts, for cross-checking the ETL)
"""
import json
import random
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

SEED = 20261028
OUT = Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(parents=True, exist_ok=True)

rng = random.Random(SEED)
np_rng = np.random.default_rng(SEED)

PLANS = {"starter": 29.0, "growth": 99.0, "pro": 249.0, "enterprise": 999.0}
PLAN_W = {"starter": 0.45, "growth": 0.30, "pro": 0.18, "enterprise": 0.07}
CHANNELS = {"organic": 0.40, "paid_search": 0.30, "referral": 0.20, "partner": 0.10}
# Monthly churn probability by plan (applied per active month)
CHURN_P = {"starter": 0.060, "growth": 0.040, "pro": 0.025, "enterprise": 0.010}

MONTHS = pd.period_range("2025-01", "2026-06", freq="M")  # 18 months
MONTH_IDX = {m: i for i, m in enumerate(MONTHS)}


def month_add(period, n):
    return period + n


def main():
    # ---- customers ------------------------------------------------------
    n_customers = 1200
    # Signups weighted toward later months (company is growing)
    signup_weights = np.linspace(1.0, 2.2, len(MONTHS))
    signup_weights /= signup_weights.sum()
    signup_months = np_rng.choice(MONTHS, size=n_customers, p=signup_weights)
    channels = np_rng.choice(
        list(CHANNELS), size=n_customers, p=list(CHANNELS.values())
    )
    customers = pd.DataFrame(
        {
            "customer_id": [f"C{i:05d}" for i in range(1, n_customers + 1)],
            "signup_date": [str(m.start_time.date()) for m in signup_months],
            "acquisition_channel": channels,
            "country": np_rng.choice(
                ["US", "CA", "GB", "DE", "AU"], size=n_customers, p=[0.6, 0.15, 0.1, 0.08, 0.07]
            ),
        }
    )

    # ---- subscriptions --------------------------------------------------
    subs_rows = []
    sub_id = 0
    for _, c in customers.iterrows():
        sub_id += 1
        plan = np_rng.choice(list(PLANS), p=list(PLAN_W.values()))
        cycle = "annual" if rng.random() < 0.25 else "monthly"
        start = pd.Period(c["signup_date"][:7], freq="M")
        # churn: walk month by month from start
        end = None
        m = start
        while m <= MONTHS[-1]:
            if rng.random() < CHURN_P[plan]:
                end = m  # churns during this month: last active month is m-1
                break
            m += 1
        # a subscription that churns in its start month never really started
        if end is not None and end == start:
            end = start  # keep it: 1-month subscription, still real
        subs_rows.append(
            {
                "subscription_id": f"S{sub_id:05d}",
                "customer_id": c["customer_id"],
                "plan": plan,
                "billing_cycle": cycle,
                "start_date": str(start.start_time.date()),
                "end_date": "" if end is None else str(end.start_time.date()),
                "monthly_price": PLANS[plan],
            }
        )
    subs = pd.DataFrame(subs_rows)

    # ---- payments -------------------------------------------------------
    pay_rows = []
    pay_id = 0
    n_failed = 0
    n_refunds = 0
    for _, s in subs.iterrows():
        start = pd.Period(s["start_date"][:7], freq="M")
        end = (
            pd.Period(s["end_date"][:7], freq="M")
            if s["end_date"]
            else MONTHS[-1]
        )
        price = s["monthly_price"]
        if s["billing_cycle"] == "monthly":
            months = pd.period_range(start, end, freq="M")
            for m in months:
                pay_id += 1
                status = "paid"
                if rng.random() < 0.02:  # failed card charge
                    status = "failed"
                    n_failed += 1
                pay_rows.append(
                    {
                        "payment_id": f"P{pay_id:06d}",
                        "subscription_id": s["subscription_id"],
                        "customer_id": s["customer_id"],
                        "payment_date": str(m.start_time.date() + pd.Timedelta(days=2)),
                        "amount": 0.0 if status == "failed" else price,
                        "currency": "USD",
                        "status": status,
                        "payment_type": "subscription",
                    }
                )
                if status == "paid" and rng.random() < 0.005:  # refund
                    pay_id += 1
                    n_refunds += 1
                    pay_rows.append(
                        {
                            "payment_id": f"P{pay_id:06d}",
                            "subscription_id": s["subscription_id"],
                            "customer_id": s["customer_id"],
                            "payment_date": str(m.start_time.date() + pd.Timedelta(days=12)),
                            "amount": -price,
                            "currency": "USD",
                            "status": "refunded",
                            "payment_type": "refund",
                        }
                    )
        else:  # annual: one lump payment per 12-month block, 10% discount
            m = start
            while m <= end:
                pay_id += 1
                status = "paid"
                if rng.random() < 0.02:
                    status = "failed"
                    n_failed += 1
                pay_rows.append(
                    {
                        "payment_id": f"P{pay_id:06d}",
                        "subscription_id": s["subscription_id"],
                        "customer_id": s["customer_id"],
                        "payment_date": str(m.start_time.date() + pd.Timedelta(days=2)),
                        "amount": 0.0 if status == "failed" else round(price * 12 * 0.9, 2),
                        "currency": "USD",
                        "status": status,
                        "payment_type": "annual_subscription",
                    }
                )
                m += 12

    payments = pd.DataFrame(pay_rows)

    # Inject exact-duplicate payment rows (billing exports do this)
    n_dup = 30
    dup_idx = np_rng.choice(payments.index, size=n_dup, replace=False)
    payments = pd.concat([payments, payments.loc[dup_idx]], ignore_index=True)
    payments = payments.sample(frac=1.0, random_state=SEED).reset_index(drop=True)

    customers.to_csv(OUT / "customers_raw.csv", index=False)
    subs.to_csv(OUT / "subscriptions_raw.csv", index=False)
    payments.to_csv(OUT / "payments_raw.csv", index=False)

    ground_truth = {
        "seed": SEED,
        "months": [str(m) for m in MONTHS],
        "n_customers": len(customers),
        "n_subscriptions": len(subs),
        "n_payment_rows_raw": len(payments),
        "n_duplicate_payment_rows_injected": n_dup,
        "n_failed_payments": n_failed,
        "n_refund_rows": n_refunds,
        "plans": PLANS,
        "annual_share": 0.25,
        "monthly_churn_probability": CHURN_P,
    }
    (OUT / "ground_truth.json").write_text(json.dumps(ground_truth, indent=2))
    print(f"customers: {len(customers)}, subscriptions: {len(subs)}, "
          f"payment rows: {len(payments)} (incl. {n_dup} injected duplicates)")
    print(f"failed payments: {n_failed}, refunds: {n_refunds}")


if __name__ == "__main__":
    main()
