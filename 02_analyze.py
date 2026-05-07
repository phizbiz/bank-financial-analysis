"""
02_analyze.py
-------------
Runs SQL-based analysis against the FDIC bank financial database
and produces visualizations saved to output/.

Requires bank_data.db — run 01_fetch_data.py first (real data)
or generate_sample_data.py (synthetic data for testing).

Analytical questions:
  1. How do ROA and NIM differ across bank size tiers?
  2. How did net interest margins shift 2019-2023?
  3. Which states have the strongest concentration of profitable banks?
  4. Which banks show stress signals (negative ROA)?
  5. Within-tier performance ranking using SQL window functions.
"""

import sqlite3
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import seaborn as sns
from pathlib import Path

DB_PATH = "bank_data.db"
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

# Consistent style across all charts
sns.set_theme(style="whitegrid", palette="Blues_d")
plt.rcParams.update({
    "font.family": "sans-serif",
    "axes.titlesize": 13,
    "axes.titleweight": "bold",
    "axes.labelsize": 11,
})

TIER_ORDER = [
    "Community (<$100M)",
    "Regional ($100M–$1B)",
    "Mid-Size ($1B–$10B)",
    "Large (>$10B)",
]


def run_query(conn, sql):
    return pd.read_sql_query(sql, conn)


# ── Query 1 ─────────────────────────────────────────────────────────────────
# Performance metrics by asset tier (2023 snapshot)
QUERY_TIER_PERFORMANCE = """
SELECT
    CASE
        WHEN asset < 100000       THEN 'Community (<$100M)'
        WHEN asset < 1000000      THEN 'Regional ($100M–$1B)'
        WHEN asset < 10000000     THEN 'Mid-Size ($1B–$10B)'
        ELSE                           'Large (>$10B)'
    END                             AS tier,
    COUNT(*)                        AS bank_count,
    ROUND(AVG(roa), 4)              AS avg_roa,
    ROUND(AVG(CAST(nim AS REAL) / NULLIF(asset, 0) * 100), 4) AS avg_nim,
    ROUND(AVG(roe), 4)              AS avg_roe,
    ROUND(
        AVG(CAST(lnlsnet AS REAL) / NULLIF(dep, 0)), 4
    )                               AS avg_loan_to_deposit
FROM bank_financials
WHERE repdte = '20231231'
GROUP BY tier
ORDER BY MIN(asset);
"""

# ── Query 2 ─────────────────────────────────────────────────────────────────
# Industry-wide NIM and ROA trend 2019-2023
QUERY_YEARLY_TREND = """
SELECT
    repdte                          AS report_date,
    ROUND(AVG(CAST(nim AS REAL) / NULLIF(asset, 0) * 100), 4) AS avg_nim,
    ROUND(AVG(roa), 4)              AS avg_roa,
    COUNT(*)                        AS bank_count
FROM bank_financials
GROUP BY repdte
ORDER BY repdte;
"""

# ── Query 3 ─────────────────────────────────────────────────────────────────
# Top 15 states by average ROA (2023, min 10 banks)
QUERY_STATE_PERFORMANCE = """
SELECT
    i.stalp                         AS state,
    COUNT(*)                        AS bank_count,
    ROUND(AVG(f.roa), 4)            AS avg_roa,
    ROUND(AVG(CAST(f.nim AS REAL) / NULLIF(f.asset, 0) * 100), 4) AS avg_nim
FROM bank_financials f
JOIN institutions i ON f.cert = i.cert
WHERE f.repdte = '20231231'
GROUP BY i.stalp
HAVING COUNT(*) >= 10
ORDER BY avg_roa DESC
LIMIT 15;
"""

# ── Query 4 ─────────────────────────────────────────────────────────────────
# Stress signals: banks with negative ROA in 2023
# Ordered by severity; limited to banks with >$100M assets
QUERY_STRESS = """
SELECT
    i.name,
    i.stalp                         AS state,
    ROUND(f.asset / 1000.0, 1)      AS assets_millions,
    ROUND(f.roa, 4)                 AS roa,
    ROUND(CAST(f.nim AS REAL) / NULLIF(f.asset, 0) * 100, 4) AS nim,
    ROUND(
        CAST(f.lnlsnet AS REAL) / NULLIF(f.dep, 0), 4
    )                               AS loan_to_deposit
FROM bank_financials f
JOIN institutions i ON f.cert = i.cert
WHERE f.repdte = '20231231'
  AND f.roa < 0
  AND f.asset > 100000
ORDER BY f.roa ASC
LIMIT 20;
"""

# ── Query 5 ─────────────────────────────────────────────────────────────────
# Within-tier ROA ranking using SQL window function (top 5 per tier, 2023)
QUERY_TIER_RANKING = """
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
        ROUND(CAST(f.nim AS REAL) / NULLIF(f.asset, 0) * 100, 4) AS nim,
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
      AND f.roa IS NOT NULL
)
SELECT *
FROM ranked
WHERE roa_rank <= 5
ORDER BY tier, roa_rank;
"""


def chart_tier_performance(df):
    fig, axes = plt.subplots(1, 3, figsize=(14, 5))
    fig.suptitle("2023 Performance Metrics by Bank Asset Tier", y=1.01)

    tiers = [t for t in TIER_ORDER if t in df["tier"].values]
    colors = sns.color_palette("Blues_d", len(tiers))

    for ax, metric, label, fmt in zip(
        axes,
        ["avg_roa", "avg_nim", "avg_loan_to_deposit"],
        ["Avg Return on Assets (%)", "Avg Net Interest Margin (%)", "Avg Loan-to-Deposit Ratio"],
        ["{:.2f}%", "{:.2f}%", "{:.2f}"],
    ):
        vals = df.set_index("tier").reindex(tiers)[metric]
        bars = ax.bar(range(len(tiers)), vals, color=colors)
        ax.set_xticks(range(len(tiers)))
        ax.set_xticklabels(tiers, rotation=30, ha="right", fontsize=9)
        ax.set_ylabel(label)
        ax.set_title(label)
        for bar, val in zip(bars, vals):
            ax.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height() + 0.01,
                fmt.format(val),
                ha="center", va="bottom", fontsize=9,
            )

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "01_tier_performance.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 01_tier_performance.png")


def chart_yearly_trend(df):
    fig, ax1 = plt.subplots(figsize=(10, 5))

    years = df["report_date"].str[:4].astype(int)
    color_nim = "#1f4e79"
    color_roa = "#c0392b"

    ax1.plot(years, df["avg_nim"], marker="o", linewidth=2.5,
             color=color_nim, label="Net Interest Margin (NIM)")
    ax1.set_ylabel("Net Interest Margin (%)", color=color_nim)
    ax1.tick_params(axis="y", labelcolor=color_nim)
    ax1.set_ylim(0, df["avg_nim"].max() * 1.4)

    ax2 = ax1.twinx()
    ax2.plot(years, df["avg_roa"], marker="s", linewidth=2.5,
             linestyle="--", color=color_roa, label="Return on Assets (ROA)")
    ax2.set_ylabel("Return on Assets (%)", color=color_roa)
    ax2.tick_params(axis="y", labelcolor=color_roa)
    ax2.set_ylim(0, df["avg_roa"].max() * 1.8)

    ax1.set_xlabel("Year")
    ax1.set_title("Industry-Wide NIM and ROA Trend (2019–2023)\nImpact of COVID (2020) and Federal Reserve Rate Hikes (2022–2023)")
    ax1.set_xticks(years)

    # Annotate rate hike period
    ax1.axvspan(2021.5, 2023.5, alpha=0.07, color="orange", label="Fed rate hike cycle")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left")

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "02_nim_roa_trend.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 02_nim_roa_trend.png")


def chart_state_performance(df):
    fig, ax = plt.subplots(figsize=(12, 6))

    colors = ["#1f4e79" if roa == df["avg_roa"].max() else "#4472c4"
              for roa in df["avg_roa"]]

    bars = ax.barh(df["state"], df["avg_roa"], color=colors)
    ax.set_xlabel("Average Return on Assets (%)")
    ax.set_title("Top 15 States by Average Bank ROA (2023)\nMin. 10 FDIC-insured institutions")
    ax.invert_yaxis()

    for bar, count in zip(bars, df["bank_count"]):
        ax.text(
            bar.get_width() + 0.01,
            bar.get_y() + bar.get_height() / 2,
            f"n={count}",
            va="center", fontsize=9, color="#555",
        )

    plt.tight_layout()
    plt.savefig(OUTPUT_DIR / "03_state_performance.png", dpi=150, bbox_inches="tight")
    plt.close()
    print("  Saved: 03_state_performance.png")


def main():
    print("=== FDIC Bank Financial Analysis ===\n")
    conn = sqlite3.connect(DB_PATH)

    print("Running SQL queries...\n")

    print("Query 1: Performance by asset tier (2023)")
    tier_df = run_query(conn, QUERY_TIER_PERFORMANCE)
    print(tier_df.to_string(index=False))

    print("\nQuery 2: Industry NIM and ROA trend (2019-2023)")
    trend_df = run_query(conn, QUERY_YEARLY_TREND)
    print(trend_df.to_string(index=False))

    print("\nQuery 3: Top states by average ROA (2023)")
    state_df = run_query(conn, QUERY_STATE_PERFORMANCE)
    print(state_df.to_string(index=False))

    print("\nQuery 4: Stress signals — banks with negative ROA (2023, >$100M assets)")
    stress_df = run_query(conn, QUERY_STRESS)
    print(stress_df.head(10).to_string(index=False))

    print("\nQuery 5: Top 5 per tier by ROA — window function ranking (2023)")
    ranking_df = run_query(conn, QUERY_TIER_RANKING)
    print(ranking_df.to_string(index=False))

    conn.close()

    print("\nGenerating charts...")
    chart_tier_performance(tier_df)
    chart_yearly_trend(trend_df)
    chart_state_performance(state_df)

    print("\nDone. Charts saved to output/")


if __name__ == "__main__":
    main()
