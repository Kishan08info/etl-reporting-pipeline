-- ETL transforms: staging -> warehouse facts/dims -> reporting marts.
-- Run by src/etl.py against data/saas.sqlite. All marts are rebuilt from
-- staging each run, so the pipeline is idempotent.
--
-- Conventions:
--   * A subscription is ACTIVE in month M when start_date <= M and
--     (end_date IS NULL OR end_date >= M). end_date is the LAST active
--     month (a subscription that churns in M paid for M, then stopped).
--   * MRR in month M = sum of the monthly-equivalent price of subscriptions
--     active in M. Annual plans pay 12 x price x 0.9 upfront, so their
--     monthly equivalent is price x 0.9.
--   * Revenue collected in month M = paid amounts minus refunds in M.
--     Failed payments move no money and are excluded (counted separately).
--   * Churn rate in month M = subs whose end_date = M / subs active in M-1
--     (the base at the start of the month), via LAG().

-- ---- dims & facts -------------------------------------------------------
DROP TABLE IF EXISTS dim_customers;
CREATE TABLE dim_customers AS
SELECT customer_id, signup_date, acquisition_channel, country
FROM stg_customers;

DROP TABLE IF EXISTS dim_subscriptions;
CREATE TABLE dim_subscriptions AS
SELECT
    subscription_id,
    customer_id,
    plan,
    billing_cycle,
    start_date,
    NULLIF(end_date, '') AS end_date,
    monthly_price,
    CASE WHEN billing_cycle = 'annual' THEN ROUND(monthly_price * 0.9, 2)
         ELSE monthly_price END AS mrr_contribution
FROM stg_subscriptions;

DROP TABLE IF EXISTS fact_payments;
CREATE TABLE fact_payments AS
SELECT payment_id, subscription_id, customer_id, payment_date,
       amount, currency, status, payment_type
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY payment_id ORDER BY payment_date) AS rn
    FROM stg_payments
)
WHERE rn = 1                      -- dedupe: billing exports repeat rows
  AND status IN ('paid', 'refunded');  -- failed payments move no money

-- ---- monthly KPI mart ---------------------------------------------------
DROP TABLE IF EXISTS mart_monthly_kpis;
CREATE TABLE mart_monthly_kpis AS
WITH months AS (
    SELECT DISTINCT strftime('%Y-%m', payment_date) AS month
    FROM stg_payments
    UNION
    SELECT DISTINCT substr(start_date, 1, 7) FROM stg_subscriptions
),
monthly AS (
    SELECT
        m.month,
        -- subscriptions active during the month
        (SELECT COUNT(*) FROM dim_subscriptions s
          WHERE substr(s.start_date, 1, 7) <= m.month
            AND (s.end_date IS NULL OR substr(s.end_date, 1, 7) >= m.month)) AS active_subs,
        (SELECT COUNT(*) FROM dim_subscriptions s
          WHERE substr(s.start_date, 1, 7) = m.month) AS new_subs,
        (SELECT COUNT(*) FROM dim_subscriptions s
          WHERE s.end_date IS NOT NULL AND substr(s.end_date, 1, 7) = m.month) AS churned_subs,
        -- MRR: monthly-equivalent price of active subs
        (SELECT ROUND(SUM(s.mrr_contribution), 2) FROM dim_subscriptions s
          WHERE substr(s.start_date, 1, 7) <= m.month
            AND (s.end_date IS NULL OR substr(s.end_date, 1, 7) >= m.month)) AS mrr,
        -- cash collected that month (paid - refunds)
        (SELECT ROUND(COALESCE(SUM(amount), 0), 2) FROM fact_payments p
          WHERE strftime('%Y-%m', p.payment_date) = m.month) AS revenue_collected,
        (SELECT ROUND(COALESCE(SUM(-amount), 0), 2) FROM fact_payments p
          WHERE strftime('%Y-%m', p.payment_date) = m.month
            AND p.status = 'refunded') AS refunds,
        (SELECT COUNT(*) FROM stg_payments p
          WHERE strftime('%Y-%m', p.payment_date) = m.month
            AND p.status = 'failed') AS failed_payments,
        (SELECT COUNT(*) FROM stg_payments p
          WHERE strftime('%Y-%m', p.payment_date) = m.month) AS payment_attempts
    FROM months m
)
SELECT
    month,
    active_subs,
    new_subs,
    churned_subs,
    mrr,
    revenue_collected,
    refunds,
    failed_payments,
    payment_attempts,
    ROUND(100.0 * failed_payments / NULLIF(payment_attempts, 0), 2) AS failed_payment_rate_pct,
    ROUND(100.0 * churned_subs / NULLIF(LAG(active_subs) OVER (ORDER BY month), 0), 2)
        AS churn_rate_pct,
    ROUND(100.0 * (mrr - LAG(mrr) OVER (ORDER BY month))
        / NULLIF(LAG(mrr) OVER (ORDER BY month), 0), 2) AS mom_mrr_growth_pct,
    ROUND(SUM(revenue_collected) OVER (ORDER BY month), 2) AS running_revenue
FROM monthly
ORDER BY month;

-- ---- revenue by plan per month ------------------------------------------
DROP TABLE IF EXISTS mart_plan_monthly;
CREATE TABLE mart_plan_monthly AS
SELECT
    strftime('%Y-%m', p.payment_date) AS month,
    s.plan,
    COUNT(*) AS n_payments,
    ROUND(SUM(p.amount), 2) AS revenue
FROM fact_payments p
JOIN dim_subscriptions s USING (subscription_id)
GROUP BY 1, 2
ORDER BY 1, 2;

-- ---- churn & revenue by acquisition channel (whole period) --------------
DROP TABLE IF EXISTS mart_churn_by_channel;
CREATE TABLE mart_churn_by_channel AS
SELECT
    c.acquisition_channel AS channel,
    COUNT(DISTINCT c.customer_id) AS customers,
    COUNT(DISTINCT s.subscription_id) AS subscriptions,
    COUNT(DISTINCT CASE WHEN s.end_date IS NOT NULL THEN s.subscription_id END) AS churned_subs,
    ROUND(100.0 * COUNT(DISTINCT CASE WHEN s.end_date IS NOT NULL THEN s.subscription_id END)
        / NULLIF(COUNT(DISTINCT s.subscription_id), 0), 1) AS churn_share_pct,
    ROUND(COALESCE(SUM(p.amount), 0), 2) AS lifetime_revenue
FROM dim_customers c
LEFT JOIN dim_subscriptions s USING (customer_id)
LEFT JOIN fact_payments p USING (subscription_id)
GROUP BY 1
ORDER BY lifetime_revenue DESC;
