# kong_dashboard_app.py

import requests
import pandas as pd
import streamlit as st
import plotly.express as px

# ========= Secrets =========
# .streamlit/secrets.toml should contain:
# KONG_API_URL = "https://kong-token-api.cyberkongz.com/leaderboard/export"
# KONG_SUMMARY_URL = "https://kong-token-api.cyberkongz.com/staking-summary"
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

# ========= Page setup =========
st.set_page_config(page_title="KONG Staking Dashboard", layout="wide")

# Card-style + metric-tile styling (do NOT wrap st.metric in custom divs)
st.markdown("""
<style>
/* Page background */
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
.stDataFrame {
  background-color:#1C1F2E !important;
  border-radius:8px;
  padding:0.4rem;
}

/* Cleaner Plotly (hide toolbar) */
.js-plotly-plot .plotly .modebar{ display:none !important; }
</style>
""", unsafe_allow_html=True)

# ========= Fetch data =========
df = fetch_leaderboard(API_URL)
summary = fetch_summary(SUMMARY_URL)
if df.empty or not summary:
    st.info("No data returned from the API yet.")
    st.stop()

# ========= Top: KPIs as tiles =========
st.title("KONG Staking Dashboard")

c1, c2, c3, c4, c5, c6 = st.columns(6)
# NOTE: Wallets staking shown as NORMAL comma-formatted number (not k/M)
c1.metric("Wallets staking", f"{summary['totalStakers']:,}")
c2.metric("Total KONG staked", format_kong(summary["totalStaked"]))
c3.metric("Median per wallet", format_kong(df["stakedAmount"].median()))
c4.metric("Max per wallet", format_kong(df["stakedAmount"].max()))
c5.metric("TVL", f"${summary['tvlUsd']:,.0f}")
c6.metric("Percentage of circulating supply staked", f"{summary['percentageOfCurrentSupply']:.2f}%")

# ========= Tier quick glance =========
tier_counts = (
    df.groupby("tier", as_index=False)
      .agg(wallets=("user", "nunique"), total_kong=("stakedAmount", "sum"))
      .sort_values("tier")
)

st.subheader("Wallets per Tier — quick glance")
t0, t1, t2, t3, t4 = st.columns(5)
tc = dict(zip(tier_counts["tier"], tier_counts["wallets"]))
t0.metric("Tier 0", format_kong(tc.get(0, 0)))
t1.metric("Tier 1", format_kong(tc.get(1, 0)))
t2.metric("Tier 2", format_kong(tc.get(2, 0)))
t3.metric("Tier 3", format_kong(tc.get(3, 0)))
t4.metric("Tier 4", format_kong(tc.get(4, 0)))

# ========= Tier charts (card) =========
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
    st.plotly_chart(fig_bar, use_container_width=True)

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
    st.plotly_chart(fig_pie, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ========= Distribution: rice / retail / whales (card) =========
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
        st.plotly_chart(fig_rice, use_container_width=True)
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
        st.plotly_chart(fig_retail, use_container_width=True)
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
        st.plotly_chart(fig_whales, use_container_width=True)
    else:
        st.info("No whales above this cutoff.")
st.markdown('</div>', unsafe_allow_html=True)

# ========= Tables side-by-side (card) =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
st.subheader("Wallets overview")

left, right = st.columns([1, 2])

with left:
    st.markdown("#### Top 20 whales")
    top_whales = whale_df.nlargest(20, "stakedAmount")[["user", "stakedAmount"]].copy()
    top_whales["stakedAmount"] = top_whales["stakedAmount"].apply(format_kong)
    st.dataframe(top_whales, use_container_width=True)

with right:
    st.markdown("#### All staking wallets")
    df_display = df[["user", "stakedAmount", "tier"]].copy()
    # sort by raw value THEN format
    df_display = df_display.sort_values("stakedAmount", ascending=False)
    df_display["stakedAmount"] = df_display["stakedAmount"].apply(format_kong)
    st.dataframe(df_display, use_container_width=True)
st.markdown('</div>', unsafe_allow_html=True)

# ========= Downloads (card) =========
st.markdown('<div class="stCard">', unsafe_allow_html=True)
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
st.markdown('</div>', unsafe_allow_html=True)
