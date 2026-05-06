"""
generate_sample_data.py
-----------------------
Generates a realistic synthetic dataset for testing 02_analyze.py
without hitting the FDIC API.

NOT intended for production use — use 01_fetch_data.py for real data.
Distributions are modeled on actual FDIC industry averages.
"""

import sqlite3
import pandas as pd
import numpy as np

DB_PATH = "bank_data.db"
YEARS = [2019, 2020, 2021, 2022, 2023]
N_BANKS = 4_500
SEED = 42

rng = np.random.default_rng(SEED)

STATES = [
    "TX", "CA", "IL", "NY", "FL", "OH", "PA", "MO", "KS", "IA",
    "MN", "WI", "IN", "GA", "TN", "NC", "OK", "NE", "CO", "KY",
    "VA", "AL", "MS", "AR", "LA", "MI", "WA", "OR", "AZ", "SC",
    "ND", "SD", "MT", "WY", "ID", "NM", "NV", "UT", "WV", "MD",
    "CT", "MA", "NH", "VT", "ME", "RI", "DE", "NJ", "AK", "HI",
]

# NIM by year — rises 2022-2023 as Fed raised rates aggressively
NIM_BY_YEAR = {2019: 3.35, 2020: 2.95, 2021: 2.75, 2022: 3.10, 2023: 3.55}

# ROA by year — dip in 2020 (COVID provisions), recovery after
ROA_BY_YEAR = {2019: 1.10, 2020: 0.70, 2021: 1.20, 2022: 1.25, 2023: 1.15}


def generate_institutions():
    certs = list(range(10000, 10000 + N_BANKS))
    states = rng.choice(STATES, size=N_BANKS)

    # Asset distribution in actual dollars — log-normal, median ~$100M
    # Matches real US bank distribution: mostly community banks with a
    # long right tail of large institutions.
    # exp(18.4) ≈ $100M, scale=1.8 gives spread from ~$5M to ~$500B
    log_assets = rng.normal(loc=18.4, scale=1.8, size=N_BANKS)
    assets_dollars = np.exp(log_assets).clip(5_000_000, 3_000_000_000_000)

    return pd.DataFrame({
        "cert": certs,
        "name": [f"First National Bank of City {i}" for i in range(N_BANKS)],
        "stalp": states,
        "city": [f"City {i}" for i in range(N_BANKS)],
        "instcat": 1,
        "active": 1,
        "asset_dollars": assets_dollars,
    })


def generate_financials(institutions):
    rows = []

    for _, bank in institutions.iterrows():
        asset_dollars = bank["asset_dollars"]
        is_large = asset_dollars > 10_000_000_000   # >$10B
        is_stressed = rng.random() < 0.08           # ~8% of banks show stress

        for year in YEARS:
            # Modest year-over-year asset growth with noise
            growth = rng.normal(1.04, 0.05)
            asset_yr = asset_dollars * (growth ** (year - 2019))

            nim_base = NIM_BY_YEAR[year]
            roa_base = ROA_BY_YEAR[year]

            # Larger banks compress NIM (more wholesale/market-rate funding)
            size_adj = -0.30 if is_large else 0.0

            if is_stressed:
                # Stressed banks: below-average NIM, negative or near-zero ROA
                nim = max(0.5, rng.normal(nim_base + size_adj - 0.8, 0.4))
                roa = rng.normal(-0.20, 0.35)
            else:
                nim = max(0.5, rng.normal(nim_base + size_adj, 0.45))
                roa = rng.normal(roa_base, 0.35)

            roe = roa * rng.uniform(8, 12)

            dep      = asset_yr * rng.uniform(0.70, 0.85)
            lnlsnet  = dep * rng.uniform(0.55, 0.80)
            eqtot    = asset_yr * rng.uniform(0.08, 0.14)
            netinc   = asset_yr * roa / 100
            intinc   = asset_yr * nim / 100
            nonii    = asset_yr * rng.uniform(0.003, 0.012)

            # Store all monetary values in thousands (matches FDIC convention)
            rows.append({
                "repdte":   f"{year}1231",
                "cert":     int(bank["cert"]),
                "asset":    round(asset_yr / 1_000),
                "roa":      round(roa, 4),
                "roe":      round(roe, 4),
                "nim":      round(nim, 4),
                "lnlsnet":  round(lnlsnet / 1_000),
                "dep":      round(dep / 1_000),
                "netinc":   round(netinc / 1_000),
                "eqtot":    round(eqtot / 1_000),
                "intinc":   round(intinc / 1_000),
                "nonii":    round(nonii / 1_000),
            })

    return pd.DataFrame(rows)


def main():
    print("Generating synthetic bank data...")

    institutions = generate_institutions()
    financials = generate_financials(institutions)

    # Show tier breakdown so we can confirm the distribution looks right
    fin_2023 = financials[financials["repdte"] == "20231231"]
    tiers = pd.cut(
        fin_2023["asset"],
        bins=[0, 100_000, 1_000_000, 10_000_000, float("inf")],
        labels=["Community (<$100M)", "Regional ($100M-$1B)",
                "Mid-Size ($1B-$10B)", "Large (>$10B)"],
    ).value_counts().sort_index()
    print("\n  2023 asset tier distribution:")
    for tier, count in tiers.items():
        print(f"    {tier}: {count:,} banks")

    institutions = institutions.drop(columns=["asset_dollars"])

    conn = sqlite3.connect(DB_PATH)
    financials.to_sql("bank_financials", conn, if_exists="replace", index=False)
    institutions.to_sql("institutions", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_repdte ON bank_financials(repdte)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_cert  ON bank_financials(cert)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_cert ON institutions(cert)")
    conn.commit()
    conn.close()

    print(f"\n  {len(institutions):,} banks | {len(financials):,} financial records")
    print(f"  Saved to {DB_PATH}")
    print("\nDone. Run 02_analyze.py next.")


if __name__ == "__main__":
    main()
