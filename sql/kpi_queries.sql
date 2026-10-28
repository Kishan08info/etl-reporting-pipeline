-- Dashboard-ready queries for the SaaS reporting warehouse (data/saas.sqlite).
-- Each query is what a BI tool (Tableau / Looker / Power BI) would run
-- against the marts. Run them with:  sqlite3 data/saas.sqlite < sql/kpi_queries.sql

-- Q1. Monthly KPI trend (the executive dashboard table)
SELECT month, active_subs, new_subs, churned_subs, churn_rate_pct,
       mrr, mom_mrr_growth_pct, revenue_collected, running_revenue
FROM mart_monthly_kpis
ORDER BY month;

-- Q2. Revenue by plan per month (stacked-bar source)
SELECT month, plan, revenue
FROM mart_plan_monthly
ORDER BY month, plan;

-- Q3. Churn and lifetime revenue by acquisition channel
SELECT channel, customers, subscriptions, churned_subs,
       churn_share_pct, lifetime_revenue
FROM mart_churn_by_channel
ORDER BY lifetime_revenue DESC;

-- Q4. Top 10 customers by lifetime revenue
SELECT c.customer_id, c.acquisition_channel, c.country,
       COUNT(DISTINCT s.subscription_id) AS n_subscriptions,
       ROUND(SUM(p.amount), 2) AS lifetime_revenue
FROM dim_customers c
JOIN dim_subscriptions s USING (customer_id)
JOIN fact_payments p USING (subscription_id)
GROUP BY c.customer_id, c.acquisition_channel, c.country
ORDER BY lifetime_revenue DESC
LIMIT 10;

-- Q5. Failed-payment rate by month (billing-health monitor)
SELECT month, payment_attempts, failed_payments, failed_payment_rate_pct
FROM mart_monthly_kpis
ORDER BY month;

-- Q6. Plan mix: share of MRR by plan in the latest month
WITH latest AS (SELECT MAX(month) AS month FROM mart_monthly_kpis),
active_now AS (
    SELECT s.plan, s.mrr_contribution
    FROM dim_subscriptions s, latest l
    WHERE substr(s.start_date, 1, 7) <= l.month
      AND (s.end_date IS NULL OR substr(s.end_date, 1, 7) >= l.month)
)
SELECT plan,
       COUNT(*) AS active_subs,
       ROUND(SUM(mrr_contribution), 2) AS mrr,
       ROUND(100.0 * SUM(mrr_contribution)
             / (SELECT SUM(mrr_contribution) FROM active_now), 1) AS mrr_share_pct
FROM active_now
GROUP BY plan
ORDER BY mrr DESC;
