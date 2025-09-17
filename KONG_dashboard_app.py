# kong_dashboard_app.py

import os
import requests
import pandas as pd
import streamlit as st
import plotly.express as px

API_URL = st.secrets["KONG_API_URL"]

def classify_tier(x: float) -> int:
    if x < 25_000: return 0
    if x < 62_500: return 1
    if x < 125_000: return 2
    if x < 250_000: return 3
    return 4

@st.cache_data(ttl=120)
def fetch_data(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json().get("leaderboard", [])
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["stakedAmount"] = pd.to_numeric(df["stakedAmount"], errors="coerce").fillna(0.0)
    df["tier"] = df["stakedAmount"].apply(classify_tier)
    return df

st.set_page_config(page_title="KONG Staking Tiers", layout="wide")
st.title("KONG Staking — Wallets by Tier")

df = fetch_data(API_URL)
if df.empty:
    st.info("No data returned from the API yet.")
    st.stop()

# ---- KPIs ----
c1, c2, c3, c4 = st.columns(4)
c1.metric("Wallets staking", f"{df['user'].nunique():,}")
c2.metric("Total KONG staked", f"{df['stakedAmount'].sum():,.0f}")
c3.metric("Median per wallet", f"{df['stakedAmount'].median():,.0f}")
c4.metric("Max per wallet", f"{df['stakedAmount'].max():,.0f}")

# ---- Tier counts ----
tier_counts = (
    df.groupby("tier", as_index=False)
      .agg(wallets=("user", "nunique"), total_kong=("stakedAmount", "sum"))
      .sort_values("tier")
)

# ---- KPIs per tier ----
st.subheader("Wallets per Tier — quick glance")
metric_cols = st.columns(5)
for i, t in enumerate([0, 1, 2, 3, 4]):
    count = int(tier_counts.loc[tier_counts["tier"] == t, "wallets"].sum())
    metric_cols[i].metric(f"Tier {t}", f"{count:,}")

# ---- Charts ----
st.subheader("Wallets per Tier — Charts")
left, right = st.columns(2)

# Build a labeled copy once
plot_df = tier_counts.copy()
plot_df["tier_label"] = plot_df["tier"].map({0: "Tier 0", 1: "Tier 1", 2: "Tier 2", 3: "Tier 3", 4: "Tier 4"})
plot_df = plot_df.sort_values("tier")  # ensure order 0..4

with left:
    st.caption("Bar chart")
    fig_bar = px.bar(
        plot_df,
        x="tier_label",
        y="wallets",
        text="wallets"
    )
    # Always put the numbers above the bars
    fig_bar.update_traces(textposition="outside")

    fig_bar.update_layout(
        xaxis_title=None,  # remove "Tier" axis label
        yaxis_title="Wallets",
        xaxis_tickangle=0,  # keep labels horizontal
        bargap=0.25,
        margin=dict(t=30, l=40, r=20, b=80)
    )
    st.plotly_chart(fig_bar, use_container_width=True)

with right:
    st.caption("Donut chart")
    fig_pie = px.pie(
        plot_df,
        names="tier_label",
        values="wallets",
        hole=0.4
    )
    fig_pie.update_traces(
        textinfo="percent+label",
        hovertemplate="%{label}<br>%{value} wallets<extra></extra>"
    )
    st.plotly_chart(fig_pie, use_container_width=True)

# ---- All staking wallets table ----
st.subheader("All staking wallets")
st.dataframe(df[["user", "stakedAmount", "tier"]], width="stretch")

# ---- Downloads ----
st.download_button(
    "Download tiers (CSV)",
    tier_counts.to_csv(index=False).encode(),
    file_name="kong_tiers.csv",
    mime="text/csv"
)
st.download_button(
    "Download wallets (CSV)",
    df.to_csv(index=False).encode(),
    file_name="kong_wallets.csv",
    mime="text/csv"
)
