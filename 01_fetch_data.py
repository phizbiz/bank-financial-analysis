"""
01_fetch_data.py
----------------
Pulls year-end financial data for all FDIC-insured commercial banks
(2019-2023) from the FDIC BankFind API and loads it into a local
SQLite database for analysis.

Run this first before 02_analyze.py.

Data sources:
  FDIC BankFind Suite — https://banks.fdic.gov/
  No API key required. Public data.
"""

import requests
import pandas as pd
import sqlite3
import time

DB_PATH = "bank_data.db"
FDIC_BASE = "https://banks.fdic.gov/api"

YEARS = [2019, 2020, 2021, 2022, 2023]

FINANCIAL_FIELDS = ",".join([
    "REPDTE",   # Report date (YYYYMMDD)
    "CERT",     # FDIC certificate number (unique bank ID)
    "ASSET",    # Total assets (thousands)
    "ROA",      # Return on assets (%)
    "ROE",      # Return on equity (%)
    "NIM",      # Net interest margin (%)
    "LNLSNET",  # Net loans and leases (thousands)
    "DEP",      # Total deposits (thousands)
    "NETINC",   # Net income (thousands)
    "EQTOT",    # Total equity capital (thousands)
    "INTINC",   # Total interest income (thousands)
    "NONII",    # Total noninterest income (thousands)
])

INSTITUTION_FIELDS = ",".join([
    "CERT",     # FDIC certificate number
    "NAME",     # Institution name
    "STALP",    # State abbreviation
    "CITY",     # City
    "INSTCAT",  # Institution category (1 = commercial bank)
    "ACTIVE",   # Active flag
])


def fetch_financials_for_year(year):
    """Fetch year-end call report financials for all FDIC-insured banks."""
    report_date = f"{year}1231"
    all_records = []
    offset = 0
    limit = 10000

    print(f"  Fetching {year} financials...", end="", flush=True)

    while True:
        resp = requests.get(f"{FDIC_BASE}/financials", params={
            "filters": f"REPDTE:{report_date}",
            "fields": FINANCIAL_FIELDS,
            "limit": limit,
            "offset": offset,
            "sort_by": "ASSET",
            "sort_order": "DESC",
        })
        resp.raise_for_status()
        payload = resp.json()
        records = payload.get("data", [])

        if not records:
            break

        for r in records:
            row = r.get("data", r)
            row["REPDTE"] = str(report_date)
            all_records.append(row)

        print(f".", end="", flush=True)

        if len(records) < limit:
            break
        offset += limit
        time.sleep(0.2)  # polite pacing

    print(f" {len(all_records):,} records")
    return pd.DataFrame(all_records)


def fetch_institutions():
    """Fetch institution metadata (name, state, category) for all active banks."""
    print("  Fetching institution metadata...", end="", flush=True)
    all_records = []
    offset = 0
    limit = 10000

    while True:
        resp = requests.get(f"{FDIC_BASE}/institutions", params={
            "filters": "ACTIVE:1",
            "fields": INSTITUTION_FIELDS,
            "limit": limit,
            "offset": offset,
        })
        resp.raise_for_status()
        payload = resp.json()
        records = payload.get("data", [])

        if not records:
            break

        for r in records:
            all_records.append(r.get("data", r))

        print(f".", end="", flush=True)

        if len(records) < limit:
            break
        offset += limit
        time.sleep(0.2)

    print(f" {len(all_records):,} records")
    return pd.DataFrame(all_records)


def load_to_sqlite(financials_df, institutions_df):
    """Write DataFrames to SQLite tables."""
    conn = sqlite3.connect(DB_PATH)

    # Normalize column names to lowercase for SQL consistency
    financials_df.columns = [c.lower() for c in financials_df.columns]
    institutions_df.columns = [c.lower() for c in institutions_df.columns]

    # Coerce numeric columns
    numeric_cols = ["asset", "roa", "roe", "nim", "lnlsnet", "dep",
                    "netinc", "eqtot", "intinc", "nonii"]
    for col in numeric_cols:
        if col in financials_df.columns:
            financials_df[col] = pd.to_numeric(financials_df[col], errors="coerce")

    financials_df.to_sql("bank_financials", conn, if_exists="replace", index=False)
    institutions_df.to_sql("institutions", conn, if_exists="replace", index=False)

    # Basic indexes for query performance
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_repdte ON bank_financials(repdte)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fin_cert  ON bank_financials(cert)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_inst_cert ON institutions(cert)")
    conn.commit()
    conn.close()
    print(f"\n  Saved to {DB_PATH}")


def main():
    print("=== FDIC Bank Data Fetch ===\n")

    all_financials = []
    for year in YEARS:
        df = fetch_financials_for_year(year)
        all_financials.append(df)

    financials = pd.concat(all_financials, ignore_index=True)
    print(f"\n  Total financial records: {len(financials):,}")

    print()
    institutions = fetch_institutions()

    print("\nLoading to SQLite...")
    load_to_sqlite(financials, institutions)

    print("\nDone. Run 02_analyze.py next.")


if __name__ == "__main__":
    main()
