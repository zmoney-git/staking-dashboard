# kong_dashboard_app.py

import requests
import pandas as pd
import streamlit as st
import plotly.express as px
from pathlib import Path

# ========= Secrets =========
API_URL = st.secrets["KONG_API_URL"]
SUMMARY_URL = st.secrets["KONG_SUMMARY_URL"]

# ========= Helpers =========
def classify_tier(x: float) -> int:
    if x < 25_000:
        return 0
    if x < 62_500:
        return 1
    if x < 125_000:
        return 2
    if x < 250_000:
        return 3
    return 4

def format_kong(x):
    """Short number formatting: 1k, 1.2M. Used everywhere EXCEPT 'Wallets staking' KPI."""
    try:
        x = float(x)
    except Exception:
        return str(x)
    if x >= 1_000_000:
        return f"{x/1_000_000:.1f}M"
    if x >= 1_000:
        return f"{x/1_000:.0f}k"
    return str(int(round(x)))

@st.cache_data(ttl=120)
def fetch_leaderboard(url: str) -> pd.DataFrame:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data = r.json().get("leaderboard", [])
    df = pd.DataFrame(data)
    if df.empty:
        return df
    df["stakedAmount"] = pd.to_numeric(df["stakedAmount"], errors="coerce").fillna(0.0)
    df["tier"] = df["stakedAmount"].apply(classify_tier)
    return df

@st.cache_data(ttl=120)
def fetch_summary(url: str) -> dict:
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    return r.json()

def show_plotly(fig, height: int | None = None):
    st.plotly_chart(
        fig,
        height=height,                # optional
        config={                      # explicit Plotly config (no deprecated kwargs)
            "displayModeBar": False,  # you were hiding it via CSS; this is the supported way
            "responsive": True,
            # add other plotly config here if you ever need it
        },
    )


# ========= History loader for time series =========
@st.cache_data(ttl=60)
def load_daily_history(path: str = "data/summaries/daily.csv") -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame()
    hist = pd.read_csv(p)
    if hist.empty:
        return hist
    hist["snapshot_date"] = pd.to_datetime(hist["snapshot_date"])
    hist = hist.sort_values("snapshot_date").reset_index(drop=True)

    # derived changes
    for col in ["total_staked", "tvl_usd", "active_wallets", "percentage_supply", "median_stake", "max_stake"]:
        hist[f"{col}_dod"] = hist[col].diff()

    # smoothers
    hist["total_staked_7dma"] = hist["total_staked"].rolling(7).mean()
    hist["active_wallets_7dma"] = hist["active_wallets"].rolling(7).mean()
    hist["tvl_usd_7dma"] = hist["tvl_usd"].rolling(7).mean()
    return hist

# ========= Page setup =========
st.set_page_config(page_title="KONG Staking Dashboard", layout="wide")

# === debug plotly version ===

import plotly, inspect
with st.expander("Debug (versions)"):
    st.write("Streamlit:", st.__version__)
    st.write("Plotly:", plotly.__version__)
    st.write("plotly_chart signature:", str(inspect.signature(st.plotly_chart)))

# === end debug plotly version ===

# Card-style + metric-tile styling (do NOT wrap st.metric in custom divs)
st.markdown("""
<style>
.stApp { background-color: #0E1117; }
/* Metric tiles */
div[data-testid="stMetric"]{
  background-color:#1C1F2E;
  padding:16px 18px;
  border-radius:12px;
  box-shadow:0 4px 6px rgba(0,0,0,.35);
  border:1px solid rgba(255,255,255,.05);
}
div[data-testid="stMetricLabel"]{ color:#9AA4B2; font-size:0.9rem; }
div[data-testid="stMetricValue"]{ color:#F1F5F9; font-weight:700; }
/* Big card containers for charts/tables */
.stCard {
  background-color:#1C1F2E;
  padding:1.2rem;
  border-radius:12px;
  box-shadow:0 4px 6px rgba(0,0,0,.4);
  border:1px solid rgba(255,255,255,.05);
  margin-bottom:1.2rem;
}
/* DataFrame container feel */
.stDataFrame { background-color:#1C1F2E !important; border-radius:8px; padding:0.4rem; }
/* Cleaner Plotly (hide toolbar) */
.js-plotly-plot .plotly .modebar{ display:none !important; }
</style>
""", unsafe_allow_html=True)

# ========= Fetch data =========
df_all = fetch_leaderboard(API_URL)   # raw list (may include zero-stake rows)
summary = fetch_summary(SUMMARY_URL)  # official totals

if df_all.empty or not summary:
    st.info("No data returned from the API yet.")
    st.stop()

# ---- ACTIVE VIEW (exclude zero-stake) ----
df = df_all[df_all["stakedAmount"] > 0].copy()

# ========= Top: KPIs as tiles =========
st.title("KONG Staking Dashboard")

c1, c2, c3, c4, c5, c6 = st.columns(6)
# Wallets staking → based on ACTIVE wallets only (exclude stakedAmount == 0), normal comma formatting
active_wallets_count = df["user"].nunique()
c1.metric("Wallets staking", f"{active_wallets_count:,}")

# The rest use summary (official) or fall back to active data
total_staked = summary.get("totalStaked", float(df["stakedAmount"].sum()))
tvl_usd = summary.get("tvlUsd", 0)
perc_supply = summary.get("percentageOfCurrentSupply", 0.0)

c2.metric("Total KONG staked", format_kong(total_staked))
c3.metric("Median per wallet", format_kong(df["stakedAmount"].median() if not df.empty else 0))
c4.metric("Max per wallet", format_kong(df["stakedAmount"].max() if not df.empty else 0))
c5.metric("TVL", f"${tvl_usd:,.0f}")
c6.metric("Percentage of circulating supply staked", f"{perc_supply:.2f}%")

# ---- Tier quick glance (active only) + zero-stake metric ----
st.subheader("Wallets per Tier")

# Active tiers (stakedAmount > 0)
tier_counts = (
    df.groupby("tier", as_index=False)
      .agg(wallets=("user", "nunique"), total_kong=("stakedAmount", "sum"))
      .sort_values("tier")
)

# Map for quick lookup
tc = dict(zip(tier_counts["tier"], tier_counts["wallets"]))

# Wallets currently staking 0 KONG (API set still has KP, but zero KONG now)
zero_stake_wallets = df_all.loc[df_all["stakedAmount"] <= 0, "user"].nunique()

# 6 tiles: Tier 0..4 + zero-stake metric at the far right
t0, t1, t2, t3, t4, t5 = st.columns(6)
t0.metric("Tier 0", f"{tc.get(0, 0):,}")
t1.metric("Tier 1", f"{tc.get(1, 0):,}")
t2.metric("Tier 2", f"{tc.get(2, 0):,}")
t3.metric("Tier 3", f"{tc.get(3, 0):,}")
t4.metric("Tier 4", f"{tc.get(4, 0):,}")
t5.metric("Wallets with KP but 0 KONG staked", f"{zero_stake_wallets:,}")

# ========= Tier charts (active only) =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.subheader("Wallets per Tier — Charts")
left, right = st.columns(2)

plot_df = tier_counts.copy()
plot_df["tier_label"] = plot_df["tier"].map({0:"Tier 0",1:"Tier 1",2:"Tier 2",3:"Tier 3",4:"Tier 4"})
plot_df = plot_df.sort_values("tier")
palette = ["#636EFA", "#00CC96", "#AB63FA", "#FFA15A", "#EF553B"]

with left:
    st.caption("Bar chart")
    fig_bar = px.bar(
        plot_df, x="tier_label", y="wallets", text="wallets",
        color="tier_label", color_discrete_sequence=palette
    )
    fig_bar.update_traces(textposition="outside")
    fig_bar.update_layout(
        xaxis_title=None, yaxis_title="Wallets",
        xaxis_tickformat="~s", yaxis_tickformat="~s",
        bargap=0.25, showlegend=False,
        margin=dict(t=30, l=40, r=20, b=80),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
    )
    show_plotly(fig_bar)

with right:
    st.caption("Donut chart")
    fig_pie = px.pie(
        plot_df, names="tier_label", values="wallets", hole=0.45,
        color="tier_label", color_discrete_sequence=palette
    )
    fig_pie.update_traces(textinfo="percent+label",
                          hovertemplate="%{label}<br>%{value} wallets<extra></extra>")
    fig_pie.update_layout(
        margin=dict(t=30, l=40, r=20, b=40),
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
    )
    show_plotly(fig_pie)
st.markdown('</div>', unsafe_allow_html=True)

# ========= Distribution: rice / retail / whales (active only) =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.subheader("Distribution of KONG staked — Rice, Retail, and Whales")

rice_cutoff = st.slider("Define the cutoff between rice and retail (KONG staked)",
                        min_value=1_000, max_value=100_000, value=10_000, step=1_000)
whale_cutoff = st.slider("Define the cutoff between retail and whales (KONG staked)",
                         min_value=100_000, max_value=int(df["stakedAmount"].max()),
                         value=1_000_000, step=50_000)
if rice_cutoff >= whale_cutoff:
    st.error("Rice cutoff must be lower than whale cutoff.")
    st.stop()

rice_df   = df[df["stakedAmount"] < rice_cutoff]
retail_df = df[(df["stakedAmount"] >= rice_cutoff) & (df["stakedAmount"] <= whale_cutoff)]
whale_df  = df[df["stakedAmount"] > whale_cutoff]

c1, c2, c3 = st.columns(3)
with c1:
    st.caption(f"🍚 Rice stakers (< {format_kong(rice_cutoff)} KONG)")
    if not rice_df.empty:
        fig_rice = px.histogram(rice_df, x="stakedAmount", nbins=30,
                                title="Rice distribution",
                                color_discrete_sequence=["#636EFA"])
        fig_rice.update_layout(
            xaxis_title="Staked KONG", yaxis_title="Wallets",
            xaxis_tickformat="~s", yaxis_tickformat="~s",
            bargap=0.1, margin=dict(t=30, l=40, r=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
        )
        show_plotly(fig_rice)
    else:
        st.info("No rice stakers.")

with c2:
    st.caption(f"Retail wallets ({format_kong(rice_cutoff)} – {format_kong(whale_cutoff)} KONG)")
    if not retail_df.empty:
        fig_retail = px.histogram(retail_df, x="stakedAmount", nbins=50,
                                  title="Retail distribution",
                                  color_discrete_sequence=["#00CC96"])
        fig_retail.update_layout(
            xaxis_title="Staked KONG", yaxis_title="Wallets",
            xaxis_tickformat="~s", yaxis_tickformat="~s",
            bargap=0.05, margin=dict(t=30, l=40, r=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
        )
        show_plotly(fig_retail)
    else:
        st.info("No retail wallets in this range.")

with c3:
    st.caption(f"Whales (> {format_kong(whale_cutoff)} KONG)")
    if not whale_df.empty:
        fig_whales = px.histogram(whale_df, x="stakedAmount", nbins=20,
                                  title="Whale distribution",
                                  color_discrete_sequence=["#EF553B"])
        fig_whales.update_layout(
            xaxis_title="Staked KONG", yaxis_title="Wallets",
            xaxis_tickformat="~s", yaxis_tickformat="~s",
            bargap=0.2, margin=dict(t=30, l=40, r=20, b=40),
            plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)"
        )
        show_plotly(fig_whales)
    else:
        st.info("No whales above this cutoff.")
st.markdown('</div>', unsafe_allow_html=True)

# ========= Tables side-by-side =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.subheader("Wallets overview")

left, right = st.columns([1, 2])

with left:
    st.markdown("#### Top 20 whales (active wallets)")
    top_whales = whale_df.nlargest(20, "stakedAmount")[["user", "stakedAmount"]].copy()
    top_whales["stakedAmount"] = top_whales["stakedAmount"].apply(format_kong)
    st.dataframe(top_whales, width='stretch')

with right:
    st.markdown("#### All staking wallets (raw, may include 0)")
    df_display = df_all[["user", "stakedAmount", "tier"]].copy()  # full list incl. zeros
    df_display = df_display.sort_values("stakedAmount", ascending=False)
    st.dataframe(df_display, width='stretch')
st.markdown('</div>', unsafe_allow_html=True)

# ========= Downloads =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.caption("Downloads (wallets CSV includes zero-stake wallets)")
st.download_button(
    "Download tiers (CSV, active wallets only)",
    tier_counts.to_csv(index=False).encode(),
    file_name="kong_tiers_active.csv",
    mime="text/csv"
)
st.download_button(
    "Download wallets (CSV, all wallets)",
    df_all.to_csv(index=False).encode(),
    file_name="kong_wallets_all.csv",
    mime="text/csv"
)
st.markdown('</div>', unsafe_allow_html=True)

# ========= Time series =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.subheader("Time-series & Growth")

hist = load_daily_history()
if hist.empty:
    st.info("No historical summaries yet. Once the daily job runs at least once, charts will appear here.")
else:
    period = st.radio("Window", ["30d", "90d", "All"], horizontal=True, index=0)
    if period == "30d":
        start = hist["snapshot_date"].max() - pd.Timedelta(days=30)
        view = hist[hist["snapshot_date"] >= start]
    elif period == "90d":
        start = hist["snapshot_date"].max() - pd.Timedelta(days=90)
        view = hist[hist["snapshot_date"] >= start]
    else:
        view = hist

    c1, c2 = st.columns(2)
    with c1:
        st.caption("Total KONG staked")
        fig_ts = px.line(view, x="snapshot_date", y=["total_staked", "total_staked_7dma"],
                         labels={"value": "KONG", "snapshot_date": ""})
        fig_ts.update_layout(margin=dict(t=30, l=40, r=20, b=40),
                             plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        show_plotly(fig_ts)

    with c2:
        st.caption("Active wallets")
        fig_aw = px.line(view, x="snapshot_date", y=["active_wallets", "active_wallets_7dma"],
                         labels={"value": "Wallets", "snapshot_date": ""})
        fig_aw.update_layout(margin=dict(t=30, l=40, r=20, b=40),
                             plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        show_plotly(fig_aw)

    c3, c4 = st.columns(2)
    with c3:
        st.caption("TVL (USD)")
        fig_tvl = px.line(view, x="snapshot_date", y=["tvl_usd", "tvl_usd_7dma"],
                          labels={"value": "USD", "snapshot_date": ""})
        fig_tvl.update_layout(margin=dict(t=30, l=40, r=20, b=40),
                              plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        show_plotly(fig_tvl)

    with c4:
        st.caption("Tier counts over time (stacked)")
        tiers = view.melt(id_vars="snapshot_date", value_vars=["tier0", "tier1", "tier2", "tier3", "tier4"],
                          var_name="tier", value_name="wallets")
        tiers["tier"] = tiers["tier"].map({"tier0": "Tier 0", "tier1": "Tier 1", "tier2": "Tier 2", "tier3": "Tier 3", "tier4": "Tier 4"})
        fig_tiers = px.area(tiers, x="snapshot_date", y="wallets", color="tier",
                            labels={"wallets": "Wallets", "snapshot_date": ""})
        fig_tiers.update_layout(margin=dict(t=30, l=40, r=20, b=40),
                                plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)")
        show_plotly(fig_tiers)

    # --- DoD deltas (latest) [robust to short histories] ---
    core_cols = ["snapshot_date", "total_staked", "active_wallets", "tvl_usd"]
    valid = view.dropna(subset=[c for c in core_cols if c in view.columns])

    if not valid.empty:
        latest_row = valid.iloc[-1]
        if len(valid) >= 2:
            prev_row = valid.iloc[-2]
            delta_total = latest_row["total_staked"] - prev_row["total_staked"]
            delta_wallets = int(latest_row["active_wallets"] - prev_row["active_wallets"])
            delta_tvl = latest_row["tvl_usd"] - prev_row["tvl_usd"]
        else:
            delta_total = 0.0
            delta_wallets = 0
            delta_tvl = 0.0

        m1, m2, m3 = st.columns(3)
        m1.metric("Δ Total staked (DoD)", format_kong(delta_total))
        m2.metric("Δ Active wallets (DoD)", f"{delta_wallets:,}")
        m3.metric("Δ TVL USD (DoD)", f"${delta_tvl:,.0f}")
    else:
        st.caption("No valid rows yet for DoD metrics.")

st.markdown('</div>', unsafe_allow_html=True)
