import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf
import os
from streamlit_autorefresh import st_autorefresh

# Health rating function
def rate_health(score):
    if pd.isna(score):
        return "⚪ No Data"
    elif score > 0.7:
        return "🟢 Good"
    elif score > 0.4:
        return "🟡 Moderate"
    else:
        return "🔴 Weak"

# Load CSV with sector and ticker info
csv_file = "EQUITY_L_with_sector.csv"
df_constituents = pd.read_csv(csv_file)

# Initialize sector history persistence
history_file = "sector_health_history.csv"
if "sector_history" not in st.session_state:
    if os.path.exists(history_file):
        st.session_state["sector_history"] = pd.read_csv(history_file, parse_dates=["time"])
    else:
        st.session_state["sector_history"] = pd.DataFrame(columns=["time", "Sector", "health_score_norm"])

# At the top of your script
def show_last_refresh(label):
    st.caption(f"🕒 {label} — Last refreshed: {pd.Timestamp.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
# Midcap index
@st.cache_data(ttl=300)
def fetch_midcap_data():
    try:
        data = yf.download("MIDCAP.NS", period="1d", interval="5m")
        if data.empty:
            return pd.DataFrame()
        latest = data.iloc[-1]
        stocks = pd.DataFrame([{
            "symbol": "NIFTY MIDCAP 100",
            "lastPrice": latest["Close"],
            "dayHigh": latest["High"],
            "dayLow": latest["Low"],
            "totalTradedVolume": latest["Volume"]
        }])
        stocks["volatility"] = (stocks["dayHigh"] - stocks["dayLow"]) / stocks["lastPrice"]
        stocks["momentum"] = 0
        stocks["health_score"] = (
            (1 - stocks["volatility"]) * 0.4 +
            (stocks["momentum"] / 100) * 0.3 +
            (stocks["totalTradedVolume"] / stocks["totalTradedVolume"].max()) * 0.3
        )
        stocks["health_rating"] = stocks["health_score"].apply(rate_health)
        return stocks
    except Exception:
        st.warning("⚠️ Rate limited by Yahoo Finance. Please wait and refresh.")
        return pd.DataFrame()

@st.cache_data(ttl=300)
def fetch_sector_stocks(sector_name):
    # Normalize sector name to match CSV
    sector_name_norm = sector_name.strip().upper()
    tickers = df_constituents[
        df_constituents["Sector"].str.strip().str.upper() == sector_name_norm
    ]["Yahoo Ticker"].dropna().tolist()

    if not tickers:
        return pd.DataFrame()

    results = []

    for ticker in tickers:
        try:
            # Try intraday first
            data = yf.download(ticker, period="1d", interval="5m")
            if data.empty:
                # Fallback to daily
                data = yf.download(ticker, period="5d", interval="1d")

            if data.empty:
                results.append({
                    "symbol": ticker,
                    "Sector": sector_name,
                    "lastPrice": None,
                    "dayHigh": None,
                    "dayLow": None,
                    "totalTradedVolume": None,
                    "volatility": None,
                    "momentum": None,
                    "health_score": None,
                    "health_rating": "⚪ No Data"
                })
                continue

            latest = data.iloc[-1]
            
   
            stock = {
                "symbol": ticker,
                "Sector": sector_name,
                "lastPrice": safe_scalar(latest["Close"]),
                "dayHigh": safe_scalar(latest["High"]),
                "dayLow": safe_scalar(latest["Low"]),
                "totalTradedVolume": safe_scalar(latest["Volume"])
            }

            # Calculate volatility
            if stock["lastPrice"] is not None and stock["dayHigh"] is not None and stock["dayLow"] is not None:
                stock["volatility"] = (stock["dayHigh"] - stock["dayLow"]) / stock["lastPrice"]
            else:
                stock["volatility"] = None


            # Momentum placeholder
            stock["momentum"] = 0

            # Health score
            if stock["lastPrice"] is not None and stock["totalTradedVolume"] is not None and stock["volatility"] is not None:
                stock["health_score"] = (
                    (1 - stock["volatility"]) * 0.4 +
                    (stock["momentum"] / 100) * 0.3 +
                    0.3  # simplified volume factor
                )
            else:
                stock["health_score"] = None

            stock["health_rating"] = rate_health(stock["health_score"])
            results.append(stock)

        except Exception as e:
            st.warning(f"⚠️ Error fetching {ticker}: {e}")
            results.append({
                "symbol": ticker,
                "Sector": sector_name,
                "lastPrice": None,
                "dayHigh": None,
                "dayLow": None,
                "totalTradedVolume": None,
                "volatility": None,
                "momentum": None,
                "health_score": None,
                "health_rating": "⚪ No Data"
            })

    return pd.DataFrame(results)
    
def safe_scalar(val):
    if isinstance(val, (pd.Series, pd.DataFrame)):
        return val.iloc[0] if not val.empty else None
    return val


@st.cache_data(ttl=300)
def fetch_sector_data(selected_sectors):
    tickers = []
    sector_map = {}
    for sector in selected_sectors:
        ticker_list = df_constituents[df_constituents["Sector"] == sector]["Yahoo Ticker"].dropna().unique().tolist()
        if ticker_list:
            tickers.append(ticker_list[0])
            sector_map[ticker_list[0]] = sector
        else:
            sector_map[None] = sector
    if not tickers:
        return pd.DataFrame()
    try:
        data = yf.download(tickers, period="1d", interval="5m", group_by="ticker")
    except Exception:
        st.warning("⚠️ Rate limited while fetching sector indices. Please wait and refresh.")
        return pd.DataFrame()
    results = []
    for ticker in tickers:
        sector = sector_map[ticker]
        if ticker not in data or data[ticker].empty:
            results.append({"symbol": sector, "lastPrice": None, "perChange": None})
            continue
        latest = data[ticker].iloc[-1]
        first = data[ticker].iloc[0]
        last_price = latest["Close"]
        open_price = first["Open"]
        per_change = ((last_price - open_price) / open_price) * 100 if open_price else None
        results.append({"symbol": sector, "lastPrice": last_price, "perChange": per_change})
    for sector in selected_sectors:
        if sector not in [r["symbol"] for r in results]:
            results.append({"symbol": sector, "lastPrice": None, "perChange": None})
    return pd.DataFrame(results)

def normalize_health_scores(df):
    if df.empty:
        df["health_score_norm"] = None
        return df

    if "health_score" not in df.columns or df["health_score"].isna().all():
        df["health_score_norm"] = None
        return df

    min_score = df["health_score"].min()
    max_score = df["health_score"].max()
    if min_score == max_score:
        df["health_score_norm"] = 0.5
    else:
        df["health_score_norm"] = (df["health_score"] - min_score) / (max_score - min_score)

    df["health_rating"] = df["health_score_norm"].apply(rate_health)
    return df

# Streamlit UI
st.set_page_config(page_title="NSE Midcap Dashboard (Yahoo)", layout="wide")
st.title("📈 NSE Midcap Dashboard (Yahoo Finance Data)")

# Auto-refresh every 15 minutes
st_autorefresh(interval=900000, limit=None, key="refresh")

sector_options = sorted(df_constituents["Sector"].dropna().unique())
default_sectors = sector_options[:2] if len(sector_options) >= 2 else sector_options
selected_sectors = st.multiselect("Select sectors to track:", sector_options, default=default_sectors)

# Main dashboard
stocks = fetch_midcap_data()
sectors = fetch_sector_data(selected_sectors)

st.subheader("📊 Market Health Snapshot")
st.dataframe(stocks)
show_last_refresh("Market Health Snapshot")


st.subheader("Sector Movements")
st.dataframe(sectors)
show_last_refresh("Sector Movements")


st.subheader("📊 Sector Price Change (%)")
fig_sector = px.bar(sectors, x="symbol", y="perChange",
                    title="Sectoral % Change",
                    color="perChange", color_continuous_scale="RdYlGn")
st.plotly_chart(fig_sector, use_container_width=True)
show_last_refresh("Sector Price Change")


combined = pd.DataFrame()
for sector in selected_sectors:
    st.subheader(f"📊 {sector}")
    sector_stocks = fetch_sector_stocks(sector)
    st.dataframe(sector_stocks)
    show_last_refresh(f"{sector}")
    combined = pd.concat([combined, sector_stocks])

if not combined.empty:
    combined = normalize_health_scores(combined)
    st.subheader("📋 Combined Summary of All Selected Sectors (Normalized Health)")
    st.dataframe(combined)

    st.subheader("🔥 Normalized Health Scores Across Sectors")
    fig_health = px.bar(combined, x="symbol", y="health_score_norm",
                        color="health_score_norm", color_continuous_scale="RdYlGn",
                        title="Stock Health (Normalized Across Selected Sectors)")
    st.plotly_chart(fig_health, use_container_width=True)

    st.subheader("🏆 Average Sector Health (Normalized)")
    sector_avg = combined.groupby("Sector", as_index=False)["health_score_norm"].mean()
    fig_sector_health = px.bar(sector_avg, x="Sector", y="health_score_norm",
                               color="health_score_norm", color_continuous_scale="RdYlGn",
                               title="Average Normalized Health by Sector")
    st.plotly_chart(fig_sector_health, use_container_width=True)

    # Save snapshot to history
    timestamp = pd.Timestamp.now()
    for _, row in sector_avg.iterrows():
        st.session_state["sector_history"] = pd.concat([
            st.session_state["sector_history"],
            pd.DataFrame([{
                "time": timestamp,
                "Sector": row["Sector"],
                "health_score_norm": row["health_score_norm"]
            }])
        ])
    st.session_state["sector_history"].to_csv(history_file, index=False)

       # Date filter widget
    st.subheader("📅 Filter Sector Health History by Date")
    if not st.session_state["sector_history"].empty:
        min_date = st.session_state["sector_history"]["time"].min()
        max_date = st.session_state["sector_history"]["time"].max()

        date_range = st.date_input(
            "Select date range:",
            value=(min_date.date(), max_date.date()),
            min_value=min_date.date(),
            max_value=max_date.date()
        )

        if len(date_range) == 2:
            start_date, end_date = date_range
            filtered_history = st.session_state["sector_history"][
                (st.session_state["sector_history"]["time"].dt.date >= start_date) &
                (st.session_state["sector_history"]["time"].dt.date <= end_date)
            ]
        else:
            filtered_history = st.session_state["sector_history"]

        # Show filtered trend chart
        st.subheader("⏳ Sector Health Trend (Filtered)")
        fig_trend_filtered = px.line(
            filtered_history,
            x="time",
            y="health_score_norm",
            color="Sector",
            markers=True,
            title="Sector Health Trend (Filtered by Date Range)"
        )
        st.plotly_chart(fig_trend_filtered, use_container_width=True)

        # Download filtered data
        csv_filtered = filtered_history.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="Download Filtered Sector Health History CSV",
            data=csv_filtered,
            file_name="sector_health_history_filtered.csv",
            mime="text/csv"
        )   