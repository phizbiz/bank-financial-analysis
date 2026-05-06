-- ============================================================================
-- U.S. Bank Financial Health Analysis
-- Standalone SQL reference — queries run against bank_data.db (SQLite)
-- Data source: FDIC BankFind Suite API (https://banks.fdic.gov/api/)
--
-- All monetary fields stored in thousands of dollars (FDIC convention).
-- Asset tier thresholds: <$100M | $100M-$1B | $1B-$10B | >$10B
-- ============================================================================


-- ── Query 1 ─────────────────────────────────────────────────────────────────
-- Performance metrics by asset tier — 2023 snapshot
-- Demonstrates: CASE WHEN tiering, GROUP BY aggregation, computed ratio
-- ────────────────────────────────────────────────────────────────────────────

SELECT
    CASE
        WHEN asset < 100000       THEN 'Community (<$100M)'
        WHEN asset < 1000000      THEN 'Regional ($100M–$1B)'
        WHEN asset < 10000000     THEN 'Mid-Size ($1B–$10B)'
        ELSE                           'Large (>$10B)'
    END                             AS tier,
    COUNT(*)                        AS bank_count,
    ROUND(AVG(roa), 4)              AS avg_roa,
    ROUND(AVG(nim), 4)              AS avg_nim,
    ROUND(AVG(roe), 4)              AS avg_roe,
    ROUND(
        AVG(CAST(lnlsnet AS REAL) / NULLIF(dep, 0)), 4
    )                               AS avg_loan_to_deposit
FROM bank_financials
WHERE repdte = '20231231'
GROUP BY tier
ORDER BY MIN(asset);


-- ── Query 2 ─────────────────────────────────────────────────────────────────
-- Industry-wide NIM and ROA trend 2019–2023
-- Shows NIM compression in 2020–2021, recovery after Fed rate hikes in 2022
-- Demonstrates: GROUP BY time period, multi-metric aggregation
-- ────────────────────────────────────────────────────────────────────────────

SELECT
    repdte                          AS report_date,
    ROUND(AVG(nim), 4)              AS avg_nim,
    ROUND(AVG(roa), 4)              AS avg_roa,
    COUNT(*)                        AS bank_count
FROM bank_financials
GROUP BY repdte
ORDER BY repdte;


-- ── Query 3 ─────────────────────────────────────────────────────────────────
-- Top 15 states by average ROA — 2023 (min 10 banks)
-- Demonstrates: JOIN across tables, HAVING filter, ORDER BY metric
-- ────────────────────────────────────────────────────────────────────────────

SELECT
    i.stalp                         AS state,
    COUNT(*)                        AS bank_count,
    ROUND(AVG(f.roa), 4)            AS avg_roa,
    ROUND(AVG(f.nim), 4)            AS avg_nim
FROM bank_financials f
JOIN institutions i ON f.cert = i.cert
WHERE f.repdte = '20231231'
GROUP BY i.stalp
HAVING COUNT(*) >= 10
ORDER BY avg_roa DESC
LIMIT 15;


-- ── Query 4 ─────────────────────────────────────────────────────────────────
-- Stress signals: banks with negative ROA in 2023
-- Includes loan-to-deposit ratio as secondary risk indicator
-- Filtered to institutions >$100M (community banks excluded for materiality)
-- Demonstrates: multi-condition WHERE, computed column, JOIN
-- ────────────────────────────────────────────────────────────────────────────

SELECT
    i.name,
    i.stalp                         AS state,
    ROUND(f.asset / 1000.0, 1)      AS assets_millions,
    ROUND(f.roa, 4)                 AS roa,
    ROUND(f.nim, 4)                 AS nim,
    ROUND(
        CAST(f.lnlsnet AS REAL) / NULLIF(f.dep, 0), 4
    )                               AS loan_to_deposit
FROM bank_financials f
JOIN institutions i ON f.cert = i.cert
WHERE f.repdte   = '20231231'
  AND f.roa      < 0
  AND f.asset    > 100000
ORDER BY f.roa ASC
LIMIT 20;


-- ── Query 5 ─────────────────────────────────────────────────────────────────
-- Top 5 performers by ROA within each asset tier — 2023
-- Demonstrates: window function (RANK OVER PARTITION BY), CTE
-- ────────────────────────────────────────────────────────────────────────────

WITH ranked AS (
    SELECT
        i.name,
        i.stalp                                         AS state,
        CASE
            WHEN f.asset < 100000    THEN 'Community (<$100M)'
            WHEN f.asset < 1000000   THEN 'Regional ($100M–$1B)'
            WHEN f.asset < 10000000  THEN 'Mid-Size ($1B–$10B)'
            ELSE                          'Large (>$10B)'
        END                                             AS tier,
        ROUND(f.roa, 4)                                 AS roa,
        ROUND(f.nim, 4)                                 AS nim,
        RANK() OVER (
            PARTITION BY CASE
                WHEN f.asset < 100000    THEN 'Community (<$100M)'
                WHEN f.asset < 1000000   THEN 'Regional ($100M–$1B)'
                WHEN f.asset < 10000000  THEN 'Mid-Size ($1B–$10B)'
                ELSE                          'Large (>$10B)'
            END
            ORDER BY f.roa DESC
        )                                               AS roa_rank
    FROM bank_financials f
    JOIN institutions i ON f.cert = i.cert
    WHERE f.repdte = '20231231'
      AND f.roa    IS NOT NULL
)
SELECT *
FROM ranked
WHERE roa_rank <= 5
ORDER BY tier, roa_rank;
