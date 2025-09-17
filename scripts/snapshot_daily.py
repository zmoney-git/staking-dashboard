# scripts/snapshot_daily.py
import os
import csv
import datetime as dt
from pathlib import Path
import requests
import pandas as pd

API_URL = os.environ.get("KONG_API_URL", "https://kong-token-api.cyberkongz.com/leaderboard/export")
SUMMARY_URL = os.environ.get("KONG_SUMMARY_URL", "https://kong-token-api.cyberkongz.com/staking-summary")

# ---- same tier logic as the app
def classify_tier(x: float) -> int:
    if x < 25_000: return 0
    if x < 62_500: return 1
    if x < 125_000: return 2
    if x < 250_000: return 3
    return 4

today = dt.date.today().isoformat()
out_dir = Path("data/summaries")
out_dir.mkdir(parents=True, exist_ok=True)
out_csv = out_dir / "daily.csv"

# ---- fetch
lb = requests.get(API_URL, timeout=30); lb.raise_for_status()
sm = requests.get(SUMMARY_URL, timeout=30); sm.raise_for_status()

leaderboard = lb.json().get("leaderboard", [])
summary = sm.json()

df = pd.DataFrame(leaderboard)
if df.empty:
    # still produce a row with whatever the summary says
    active_wallets = 0
    median_stake = 0
    max_stake = 0
    zero_stake_wallets = 0
    tier_counts = {f"tier{i}": 0 for i in range(5)}
else:
    df["stakedAmount"] = pd.to_numeric(df["stakedAmount"], errors="coerce").fillna(0.0)
    active_df = df[df["stakedAmount"] > 0]
    active_wallets = int(active_df["user"].nunique())
    median_stake = float(active_df["stakedAmount"].median() if not active_df.empty else 0)
    max_stake = float(active_df["stakedAmount"].max() if not active_df.empty else 0)
    zero_stake_wallets = int(df.loc[df["stakedAmount"] <= 0, "user"].nunique())
    # tiers
    if not active_df.empty:
        active_df = active_df.assign(tier=active_df["stakedAmount"].apply(classify_tier))
        tier_counts_series = active_df.groupby("tier")["user"].nunique()
    else:
        tier_counts_series = pd.Series(dtype=int)
    tier_counts = {f"tier{i}": int(tier_counts_series.get(i, 0)) for i in range(5)}

total_staked = float(summary.get("totalStaked", float(df["stakedAmount"].sum()) if not df.empty else 0))
tvl_usd = float(summary.get("tvlUsd", 0))
perc_supply = float(summary.get("percentageOfCurrentSupply", 0.0))

row = {
    "snapshot_date": today,
    "total_staked": total_staked,
    "tvl_usd": tvl_usd,
    "percentage_supply": perc_supply,
    "active_wallets": active_wallets,
    "median_stake": median_stake,
    "max_stake": max_stake,
    "zero_stake_wallets": zero_stake_wallets,
    **tier_counts,  # tier0..tier4
}

# ---- upsert into daily.csv (one row per date)
cols = [
    "snapshot_date","total_staked","tvl_usd","percentage_supply",
    "active_wallets","median_stake","max_stake","zero_stake_wallets",
    "tier0","tier1","tier2","tier3","tier4"
]

if out_csv.exists():
    hist = pd.read_csv(out_csv)
    hist = hist[hist["snapshot_date"] != today]
    hist = pd.concat([hist, pd.DataFrame([row], columns=cols)], ignore_index=True)
    hist = hist.sort_values("snapshot_date")
    hist.to_csv(out_csv, index=False)
else:
    with open(out_csv, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerow(row)
