"""
Speciale Incept — Listed Equity Portfolio · IC Dashboard
Data source: Google Sheets — All Trades tab
"""
import os
from datetime import date, datetime, timedelta
from collections import defaultdict

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Speciale Incept · IC Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SPREADSHEET_ID = "14zSRp_Q8bOU6w9Z3gz6csV9FFNTC37jitur7I_Egeqg"
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]

ABFRL_DEMERGE_DATE = date(2025, 5, 22)
ABFRL              = "Aditya Birla Fashion and Retail Ltd"
ABLBL              = "Aditya Birla Lifestyle Brands Ltd"

# Keys must match Security Name in All Trades exactly
TICKERS = {
    "Aditya Birla Fashion and Retail Ltd": "ABFRL.NS",
    "Aditya Birla Lifestyle Brands Ltd":   "ABLBL.NS",
    "Federal Bank Ltd":                    "FEDERALBNK.NS",
    "FSN E-Commerce Ventures Ltd":         "NYKAA.NS",
    "Newgen Software Technologies Ltd":    "NEWGEN.NS",
    "Indegene Ltd":                        "INDGN.NS",
    "EID Parry (India) Ltd":               "EIDPARRY.NS",
    "Gujarat Fluorochemicals Ltd":         "FLUOROCHEM.NS",
    "Greenlam Industries Ltd":             "GREENLAM.NS",
    "Sundaram Clayton Ltd":                "SUNCLAY.NS",
    "Aether Industries Ltd":               "AETHER.NS",
    "HDFC Bank Ltd":                       "HDFCBANK.NS",
    "Sansera Engineering Ltd":             "SANSERA.NS",
}

FALLBACK = {
    "Aditya Birla Fashion and Retail Ltd": 67.41,
    "Aditya Birla Lifestyle Brands Ltd":   102.30,
    "Federal Bank Ltd":                    288.85,
    "FSN E-Commerce Ventures Ltd":         269.85,
    "Newgen Software Technologies Ltd":    439.00,
    "Indegene Ltd":                        514.00,
    "EID Parry (India) Ltd":               793.00,
    "Gujarat Fluorochemicals Ltd":         3838.00,
    "Greenlam Industries Ltd":             254.00,
    "Sundaram Clayton Ltd":                1327.00,
    "Aether Industries Ltd":               1077.00,
    "HDFC Bank Ltd":                       783.00,
    "Sansera Engineering Ltd":             550.00,
}

DISPLAY = {
    "Aditya Birla Fashion and Retail Ltd": "ABFRL",
    "Aditya Birla Lifestyle Brands Ltd":   "ABLBL",
    "Federal Bank Ltd":                    "Federal Bank",
    "FSN E-Commerce Ventures Ltd":         "Nykaa",
    "Newgen Software Technologies Ltd":    "Newgen",
    "Indegene Ltd":                        "Indegene",
    "EID Parry (India) Ltd":               "EID Parry",
    "Gujarat Fluorochemicals Ltd":         "Guj. Fluorochem",
    "Greenlam Industries Ltd":             "Greenlam",
    "Sundaram Clayton Ltd":                "Sundaram Clayton",
    "Aether Industries Ltd":               "Aether",
    "HDFC Bank Ltd":                       "HDFC Bank",
    "Sansera Engineering Ltd":             "Sansera",
}

# Sector mapping — TheWrap sourced + manual overrides
# (sub-industry, broad sector)
SECTORS = {
    "Aditya Birla Fashion and Retail Ltd": ("Retail Chain",         "Retail & Hospitality"),
    "Aditya Birla Lifestyle Brands Ltd":   ("Retail Chain",         "Retail & Hospitality"),
    "Federal Bank Ltd":                    ("Private Bank",         "BFSI"),
    "FSN E-Commerce Ventures Ltd":         ("Ecommerce",            "Technology"),
    "Newgen Software Technologies Ltd":    ("IT Products",          "Technology"),
    "Indegene Ltd":                        ("Healthcare Services",  "Healthcare"),
    "EID Parry (India) Ltd":               ("Sugar",                "Food & Agri"),
    "Gujarat Fluorochemicals Ltd":         ("Speciality Chemicals", "Chemicals"),
    "Greenlam Industries Ltd":             ("Building Materials",   "Building Materials"),
    "Sundaram Clayton Ltd":                ("Auto Ancillary",       "Auto"),
    "Aether Industries Ltd":               ("Speciality Chemicals", "Chemicals"),
    "HDFC Bank Ltd":                       ("Private Bank",         "BFSI"),
    "Sansera Engineering Ltd":             ("Auto Ancillary",       "Auto"),
}

# Consistent palette for broad sectors
SECTOR_PALETTE = {
    "BFSI":                 "#4a9eff",
    "Technology":           "#a78bfa",
    "Healthcare":           "#34d399",
    "Chemicals":            "#f59e0b",
    "Auto":                 "#fb923c",
    "Retail & Hospitality": "#f472b6",
    "Building Materials":   "#60a5fa",
    "Food & Agri":          "#4ade80",
}

# Shared chart layout (dark theme)
_CL = dict(
    paper_bgcolor="#111827",
    plot_bgcolor="#111827",
    font=dict(color="#8a9ab5", size=11),
    margin=dict(t=30, b=20, l=20, r=20),
    xaxis=dict(gridcolor="#1a2540", zeroline=True, zerolinecolor="#1e3a6e"),
    yaxis=dict(gridcolor="#1a2540"),
)

# ── Custom CSS ─────────────────────────────────────────────────────────────────
_CSS = """
<style>
/* ══ IC Dashboard polish ════════════════════════════════════════════════════ */

/* Metric cards */
[data-testid="stMetric"] {
    background: #111827;
    border: 1px solid #1e2d4d;
    border-radius: 12px;
    padding: 18px 22px !important;
}
[data-testid="stMetricLabel"] p {
    color: #4a6080 !important;
    font-size: 10px !important;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.2px;
}
[data-testid="stMetricValue"] {
    color: #f0f4ff !important;
    font-size: 24px !important;
    font-weight: 700;
}

/* Buttons */
[data-testid="baseButton-secondary"] {
    background: #141c2f !important;
    color: #4a9eff !important;
    border: 1px solid #1e3a6e !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 12px !important;
}
[data-testid="baseButton-secondary"]:hover {
    background: #1e2d4d !important;
    border-color: #4a9eff !important;
}

/* DataFrames */
[data-testid="stDataFrame"] {
    border: 1px solid #1e2d4d;
    border-radius: 10px;
    overflow: hidden;
}

/* Dividers */
hr { border-color: #1a2540 !important; }

/* Expanders */
details {
    background: #111827 !important;
    border: 1px solid #1e2d4d !important;
    border-radius: 10px !important;
    padding: 4px 0 !important;
}
summary { color: #6b82a8 !important; font-weight: 600; font-size: 13px; }

/* Multiselect tags */
[data-baseweb="tag"] { background: #1e3a6e !important; }

/* Captions */
.stCaption p { color: #2d3f5e !important; }

/* Section label helper */
.ic-label {
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #2d4a7a;
    margin-bottom: 16px;
    margin-top: 8px;
}

/* Stress card */
.stress-card {
    background: #111827;
    border: 1px solid #1e2d4d;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
}
.stress-label { font-size: 10px; color: #4a6080; font-weight: 700; letter-spacing: 1px; text-transform: uppercase; margin-bottom: 6px; }
.stress-val   { font-size: 22px; font-weight: 700; color: #f0f4ff; }
.stress-chg   { font-size: 12px; font-weight: 600; margin-top: 4px; }
</style>
"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def section_label(text):
    st.markdown(f'<div class="ic-label">{text}</div>', unsafe_allow_html=True)


def inr(val):
    sign = "-" if val < 0 else ""
    v = abs(val)
    if v >= 1e7: return f"{sign}₹{v/1e7:.2f} Cr"
    if v >= 1e5: return f"{sign}₹{v/1e5:.2f} L"
    return f"{sign}₹{v:,.0f}"


# ── Data loading ───────────────────────────────────────────────────────────────
def _parse_date(val):
    if isinstance(val, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(val))
    try:
        return datetime.strptime(str(val).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


@st.cache_data(ttl=3600)
def load_ticker_map():
    creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    gc    = gspread.authorize(creds)
    try:
        ws   = gc.open_by_key(SPREADSHEET_ID).worksheet("SI_Portfolio")
        rows = ws.get("A1:B200", value_render_option="FORMATTED_VALUE")
        tickers = {}
        for r in rows:
            if len(r) < 2:
                continue
            company = r[0].strip()
            ticker  = r[1].strip()
            if not company or not ticker or ticker.upper() != ticker:
                continue
            tickers[company] = ticker + ".NS"
        return tickers, {}
    except Exception:
        return {}, {}


@st.cache_data(ttl=900)
def load_watchlist():
    creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    gc    = gspread.authorize(creds)
    ws    = gc.open_by_key(SPREADSHEET_ID).worksheet("Watchlist")
    rows  = ws.get("B4:O1000", value_render_option="FORMATTED_VALUE")
    result = []
    for r in rows:
        r = r + [""] * (14 - len(r))
        ticker = str(r[0]).strip()
        if not ticker:
            continue
        result.append({
            "Ticker":               ticker,
            "Company":              r[1],
            "Analyst":              r[2],
            "Sector":               r[3],
            "CMP (₹)":              r[4],
            "52W High (₹)":         r[5],
            "52W Low (₹)":          r[6],
            "P/E":                  r[8],
            "Last Disc. Date":      r[9],
            "Last Disc. Price (₹)": r[10],
            "Chg since LDP %":      r[11],
            "Status":               r[12],
            "Notes":                r[13],
        })
    return result


@st.cache_data(ttl=3600)
def load_raw_transactions():
    creds  = Credentials.from_service_account_info(
                 dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    gc     = gspread.authorize(creds)
    ws     = gc.open_by_key(SPREADSHEET_ID).worksheet("All Trades")
    rows   = ws.get("A2:M10000", value_render_option="UNFORMATTED_VALUE")
    result = []
    for r in rows:
        if len(r) < 11:
            continue
        d    = _parse_date(r[1])
        name = r[4].strip()  if isinstance(r[4], str) else str(r[4])
        txn  = r[8].strip()  if isinstance(r[8], str) else str(r[8])
        prod = r[9].strip()  if isinstance(r[9], str) else str(r[9])
        if not d or not name or not txn:
            continue
        try:
            qty   = abs(float(str(r[10]).replace(",", ""))) if r[10] != "" else 0.0
            price = float(str(r[11]).replace(",", ""))      if len(r) > 11 and r[11] != "" else 0.0
            value = abs(float(str(r[12]).replace(",", ""))) if len(r) > 12 and r[12] != "" else 0.0
        except (ValueError, TypeError):
            continue
        if qty == 0:
            continue
        result.append({
            "date": d, "company": name, "qty": qty, "price": price,
            "value": value, "type": txn.upper(), "product_type": prod, "note": "",
        })
    return result


def apply_corporate_actions(raw):
    adjusted   = []
    abfrl_lots = []
    for t in raw:
        t = dict(t)
        co, d, ttype, prod = t["company"], t["date"], t["type"], t["product_type"]
        if co == ABLBL and prod == "Demerger":
            continue
        if co == ABFRL and ttype == "BUY" and d < ABFRL_DEMERGE_DATE:
            orig_price = t["price"]
            orig_value = t["value"]
            t["orig_value"] = orig_value
            t["price"]      = orig_price / 2
            t["value"]      = orig_value / 2
            t["note"]       = f"Demerger adj ÷2 (orig ₹{orig_price:,.2f})"
            abfrl_lots.append(dict(t))
        else:
            t["orig_value"] = t["value"]
        adjusted.append(t)
    for lot in abfrl_lots:
        ablbl = dict(lot)
        ablbl["company"]      = ABLBL
        ablbl["type"]         = "BUY"
        ablbl["product_type"] = "DEMERGER"
        ablbl["note"]         = "1:1 demerger from ABFRL"
        adjusted.append(ablbl)
    adjusted.sort(key=lambda x: x["date"])
    return adjusted


def build_positions(txns):
    pos = defaultdict(lambda: {"qty": 0.0, "total_cost": 0.0, "first_buy": None, "sells": []})
    for t in txns:
        co, ttype = t["company"], t["type"]
        p = pos[co]
        if ttype == "BUY":
            p["qty"]        += t["qty"]
            p["total_cost"] += t["value"]
            if p["first_buy"] is None or t["date"] < p["first_buy"]:
                p["first_buy"] = t["date"]
        elif ttype == "SELL":
            if p["qty"] > 0:
                p["total_cost"] -= (p["total_cost"] / p["qty"]) * t["qty"]
            p["qty"]   -= t["qty"]
            p["sells"].append({"date": t["date"], "qty": t["qty"], "proceeds": t["value"]})
    return dict(pos)


@st.cache_data(ttl=900)
def fetch_prices(companies: tuple):
    sheet_tickers, _ = load_ticker_map()
    all_tickers = {**TICKERS, **sheet_tickers}
    prices, sources = {}, {}
    for co in companies:
        ticker = all_tickers.get(co)
        if ticker:
            try:
                px_val = yf.Ticker(ticker).fast_info.last_price
                if px_val and px_val > 0:
                    prices[co]  = round(float(px_val), 2)
                    sources[co] = "live"
                    continue
            except Exception:
                pass
        if co in FALLBACK:
            prices[co]  = FALLBACK[co]
            sources[co] = "fallback"
    return prices, sources


def _xirr(cashflows):
    if len(cashflows) < 2:
        return None
    t0    = min(cf[0] for cf in cashflows)
    times = [(cf[0] - t0).days / 365.0 for cf in cashflows]
    amts  = [cf[1] for cf in cashflows]
    def npv(r):
        return sum(a / (1 + r) ** t for a, t in zip(amts, times))
    try:
        from scipy.optimize import brentq
        if npv(-0.9999) * npv(100) > 0:
            return None
        return brentq(npv, -0.9999, 100, xtol=1e-8)
    except Exception:
        return None


def get_xirr_cashflows(co, txns, positions, prices):
    combined = {ABFRL, ABLBL}
    group    = combined if co in combined else {co}
    cfs, rows = [], []
    for t in txns:
        if t["company"] not in group:
            continue
        if t["product_type"] == "DEMERGER":
            continue
        if t["type"] == "BUY":
            val = t.get("orig_value", t["value"])
            cfs.append((t["date"], -val))
            rows.append({"Date": t["date"],
                         "Event": f"BUY — {DISPLAY.get(t['company'], t['company'])}",
                         "Qty": int(round(t["qty"])), "Cash Flow": -val})
        elif t["type"] == "SELL":
            cfs.append((t["date"], t["value"]))
            rows.append({"Date": t["date"],
                         "Event": f"SELL — {DISPLAY.get(t['company'], t['company'])}",
                         "Qty": -int(round(t["qty"])), "Cash Flow": t["value"]})
    terminal = sum(positions.get(c, {}).get("qty", 0) * prices.get(c, 0) for c in group)
    cfs.append((date.today(), terminal))
    rows.append({"Date": date.today(), "Event": "Current Value (terminal)",
                 "Qty": int(round(sum(positions.get(c, {}).get("qty", 0) for c in group))),
                 "Cash Flow": terminal})
    return _xirr(cfs), rows


def compute_xirr_all(txns, positions, prices):
    combined  = {ABFRL, ABLBL}
    xirr_map  = {}
    cfs = []
    for t in txns:
        if t["product_type"] == "DEMERGER":
            continue
        if t["company"] == ABFRL and t["type"] == "BUY":
            cfs.append((t["date"], -t.get("orig_value", t["value"])))
        elif t["company"] in combined and t["type"] == "SELL":
            cfs.append((t["date"], t["value"]))
    terminal = sum(positions.get(co, {}).get("qty", 0) * prices.get(co, 0) for co in combined)
    if terminal > 0:
        cfs.append((date.today(), terminal))
    x = _xirr(cfs)
    for co in combined:
        xirr_map[co] = x
    for co, pos in positions.items():
        if co in combined:
            continue
        cfs = []
        for t in txns:
            if t["company"] != co:
                continue
            if t["type"] == "BUY":
                cfs.append((t["date"], -t["value"]))
            elif t["type"] == "SELL":
                cfs.append((t["date"], t["value"]))
        cur_val = pos["qty"] * prices.get(co, 0)
        if cur_val > 0:
            cfs.append((date.today(), cur_val))
        xirr_map[co] = _xirr(cfs)
    return xirr_map


# ── App ────────────────────────────────────────────────────────────────────────
def main():
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr_l, hdr_r = st.columns([4, 1])
    with hdr_l:
        st.markdown(
            f"<h1 style='margin:0;padding:0;color:#f0f4ff;font-size:22px;font-weight:800;letter-spacing:-0.3px;'>"
            f"SPECIALE INCEPT</h1>"
            f"<div style='font-size:10px;color:#2d4a7a;letter-spacing:2px;text-transform:uppercase;"
            f"margin-top:3px;'>Listed Equity Portfolio &nbsp;·&nbsp; IC Dashboard &nbsp;·&nbsp; "
            f"{datetime.now().strftime('%d %b %Y')}</div>",
            unsafe_allow_html=True,
        )
    with hdr_r:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("⟳  Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Load & compute ────────────────────────────────────────────────────────
    _, sheet_display = load_ticker_map()
    active_display   = {**DISPLAY, **sheet_display}

    raw   = load_raw_transactions()
    txns  = apply_corporate_actions(raw)
    pos   = build_positions(txns)

    with st.spinner("Fetching live prices…"):
        prices, sources = fetch_prices(tuple(pos.keys()))

    xirr_map = compute_xirr_all(txns, pos, prices)

    rows_open, rows_closed = [], []
    for co, p in pos.items():
        qty      = p["qty"]
        cost     = p["total_cost"]
        price    = prices.get(co, 0)
        cur_val  = qty * price
        sell_val = sum(s["proceeds"] for s in p["sells"])
        pnl      = cur_val - cost
        pnl_pct  = (pnl / cost * 100) if cost > 0 else 0
        avg_cost = (cost / qty) if qty > 0 else 0
        days     = (date.today() - p["first_buy"]).days if p["first_buy"] else 0
        xi       = xirr_map.get(co)
        sub, broad = SECTORS.get(co, ("—", "Other"))
        row = {
            "Company":       active_display.get(co, co),
            "_key":          co,
            "Sector":        broad,
            "Sub-Industry":  sub,
            "Qty":           int(round(qty)),
            "Avg Cost (₹)":  round(avg_cost, 2),
            "Total Cost":    cost,
            "Price (₹)":     price,
            "Cur. Value":    cur_val,
            "P&L (₹)":       pnl,
            "P&L %":         pnl_pct,
            "Days Held":     days,
            "XIRR %":        round(xi * 100, 1) if xi is not None else None,
            "Price Source":  sources.get(co, "—"),
        }
        if qty > 0.5:
            rows_open.append(row)
        else:
            tot_cost_paid  = sum(t["value"] for t in txns if t["company"] == co and t["type"] == "BUY")
            sell_txns      = [t for t in txns if t["company"] == co and t["type"] == "SELL"]
            total_sold_qty = sum(t["qty"] for t in sell_txns)
            avg_sell_price = sell_val / total_sold_qty if total_sold_qty else 0
            row["Qty"]          = int(round(total_sold_qty))
            row["Total Cost"]   = tot_cost_paid
            row["Cur. Value"]   = sell_val
            row["P&L (₹)"]      = sell_val - tot_cost_paid
            row["P&L %"]        = (sell_val - tot_cost_paid) / tot_cost_paid * 100 if tot_cost_paid else 0
            row["Price (₹)"]    = avg_sell_price
            row["Avg Cost (₹)"] = tot_cost_paid / total_sold_qty if total_sold_qty else 0
            rows_closed.append(row)

    df_open   = pd.DataFrame(rows_open).sort_values("Cur. Value", ascending=False).reset_index(drop=True)
    df_closed = pd.DataFrame(rows_closed).reset_index(drop=True) if rows_closed else pd.DataFrame()

    total_cost    = df_open["Total Cost"].sum()
    total_val     = df_open["Cur. Value"].sum()
    total_pnl     = df_open["P&L (₹)"].sum()
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0

    total_realized_pnl = df_closed["P&L (₹)"].sum() if not df_closed.empty else 0.0
    win_rate = (
        len(df_closed[df_closed["P&L (₹)"] > 0]) / len(df_closed) * 100
        if not df_closed.empty else None
    )

    port_cfs = []
    for t in txns:
        if t["product_type"] == "DEMERGER":
            continue
        if t["type"] == "BUY":
            port_cfs.append((t["date"], -t.get("orig_value", t["value"])))
        elif t["type"] == "SELL":
            port_cfs.append((t["date"], t["value"]))
    port_cfs.append((date.today(), total_val))
    port_xirr = _xirr(port_cfs)

    df_open["Weight %"] = df_open["Cur. Value"] / total_val * 100 if total_val else 0

    # ── KPI Strip ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Invested",  inr(total_cost))
    k2.metric("Current Value",   inr(total_val))
    k3.metric("Unrealised P&L",  inr(total_pnl),  f"{total_pnl_pct:+.1f}%")
    k4.metric("Portfolio XIRR",  f"{port_xirr*100:.1f}%" if port_xirr else "—")
    k5.metric("Open Positions",  str(len(df_open)))
    k6.metric(
        "Realised P&L",
        inr(total_realized_pnl),
        f"Win rate {win_rate:.0f}%" if win_rate is not None else "—",
    )

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── Portfolio Composition ─────────────────────────────────────────────────
    section_label("Portfolio Composition")

    comp_l, comp_r = st.columns([6, 4])

    with comp_l:
        # Sector treemap: size = value, colour = P&L%
        tm_df = df_open[["Company", "Sector", "Sub-Industry", "Cur. Value", "P&L %", "Weight %"]].copy()
        tm_df["Sector"] = tm_df["Sector"].fillna("Other")
        fig_tm = px.treemap(
            tm_df,
            path=[px.Constant("Portfolio"), "Sector", "Company"],
            values="Cur. Value",
            color="P&L %",
            color_continuous_scale=["#ef4444", "#1a2d4d", "#22c55e"],
            color_continuous_midpoint=0,
            custom_data=["Sub-Industry", "Weight %", "P&L %"],
        )
        fig_tm.update_traces(
            texttemplate="<b>%{label}</b><br>%{percentRoot:.1%}",
            hovertemplate=(
                "<b>%{label}</b><br>"
                "Value: ₹%{value:,.0f}<br>"
                "Weight: %{customdata[1]:.1f}%<br>"
                "P&L: %{customdata[2]:+.1f}%<extra></extra>"
            ),
            textfont=dict(size=12),
        )
        fig_tm.update_layout(
            **{k: v for k, v in _CL.items() if k not in ("xaxis", "yaxis")},
            height=380,
            margin=dict(t=10, b=10, l=10, r=10),
            coloraxis_showscale=False,
        )
        st.plotly_chart(fig_tm, use_container_width=True)

    with comp_r:
        # Sector allocation donut
        sect_df = (
            df_open.groupby("Sector")["Cur. Value"]
            .sum()
            .reset_index()
            .sort_values("Cur. Value", ascending=False)
        )
        sect_df["Weight %"] = sect_df["Cur. Value"] / total_val * 100
        sect_colors = [SECTOR_PALETTE.get(s, "#4a9eff") for s in sect_df["Sector"]]

        fig_donut = go.Figure(go.Pie(
            labels=sect_df["Sector"],
            values=sect_df["Cur. Value"],
            hole=0.58,
            marker=dict(colors=sect_colors, line=dict(color="#0b0f1a", width=2)),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>₹%{value:,.0f}<br>%{percent}<extra></extra>",
        ))
        fig_donut.add_annotation(
            text=f"<b>{len(sect_df)}</b><br><span style='font-size:10px'>Sectors</span>",
            x=0.5, y=0.5, showarrow=False, font=dict(size=18, color="#e0e6f0"),
            align="center",
        )
        fig_donut.update_layout(
            **{k: v for k, v in _CL.items() if k not in ("xaxis", "yaxis")},
            height=200,
            margin=dict(t=0, b=0, l=0, r=0),
            showlegend=False,
        )
        st.plotly_chart(fig_donut, use_container_width=True)

        # Sector weight table
        for _, row in sect_df.iterrows():
            bar_w = int(row["Weight %"] / sect_df["Weight %"].max() * 100)
            color = SECTOR_PALETTE.get(row["Sector"], "#4a9eff")
            st.markdown(
                f"<div style='display:flex;justify-content:space-between;align-items:center;"
                f"margin:4px 0;font-size:12px;'>"
                f"<span style='color:#c8d4f0;min-width:140px'>{row['Sector']}</span>"
                f"<div style='flex:1;margin:0 10px;background:#1a2540;border-radius:4px;height:6px;'>"
                f"<div style='width:{bar_w}%;background:{color};height:6px;border-radius:4px;'></div></div>"
                f"<span style='color:#6b82a8;font-weight:700;min-width:40px;text-align:right'>"
                f"{row['Weight %']:.1f}%</span></div>",
                unsafe_allow_html=True,
            )

    st.markdown("<br>", unsafe_allow_html=True)

    # Concentration strip
    top3_w    = df_open.nlargest(3, "Cur. Value")["Weight %"].sum()
    top1_row  = df_open.nlargest(1, "Cur. Value").iloc[0]
    top_sect  = sect_df.iloc[0]
    hhi       = (df_open["Weight %"] ** 2).sum()   # Herfindahl index (higher = more concentrated)

    cn1, cn2, cn3, cn4 = st.columns(4)
    cn1.metric("Top Stock Weight",   f"{top1_row['Weight %']:.1f}%",   top1_row["Company"])
    cn2.metric("Top 3 Weight",       f"{top3_w:.1f}%",                 "of portfolio")
    cn3.metric("Top Sector",         f"{top_sect['Weight %']:.1f}%",   top_sect["Sector"])
    cn4.metric("Concentration (HHI)", f"{hhi:.0f}",
               "Low" if hhi < 1500 else ("Moderate" if hhi < 2500 else "High"))

    st.divider()

    # ── Performance ────────────────────────────────────────────────────────────
    section_label("Performance")

    perf_l, perf_r = st.columns(2)

    with perf_l:
        xi_df = (
            df_open[["Company", "XIRR %"]]
            .dropna()
            .sort_values("XIRR %")
        )
        xi_colors = ["#ef4444" if v < 0 else "#22c55e" for v in xi_df["XIRR %"]]
        fig_xi = go.Figure(go.Bar(
            x=xi_df["XIRR %"],
            y=xi_df["Company"],
            orientation="h",
            marker_color=xi_colors,
            text=[f"{v:+.1f}%" for v in xi_df["XIRR %"]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11),
        ))
        fig_xi.update_layout(
            **_CL,
            title=dict(text="XIRR by Stock", font=dict(size=12, color="#6b82a8"), x=0),
            height=380,
            xaxis=dict(title="XIRR %", gridcolor="#1a2540", zeroline=True, zerolinecolor="#2d4a7a"),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", automargin=True),
            margin=dict(t=40, b=20, l=20, r=80),
        )
        st.plotly_chart(fig_xi, use_container_width=True)

    with perf_r:
        pnl_df = df_open.sort_values("P&L %")
        pnl_colors = ["#ef4444" if v < 0 else "#4a9eff" for v in pnl_df["P&L %"]]
        fig_pnl = go.Figure(go.Bar(
            x=pnl_df["P&L %"],
            y=pnl_df["Company"],
            orientation="h",
            marker_color=pnl_colors,
            text=[f"{v:+.1f}%" for v in pnl_df["P&L %"]],
            textposition="outside",
            cliponaxis=False,
            textfont=dict(size=11),
        ))
        fig_pnl.update_layout(
            **_CL,
            title=dict(text="Unrealised P&L % by Stock", font=dict(size=12, color="#6b82a8"), x=0),
            height=380,
            xaxis=dict(title="P&L %", gridcolor="#1a2540", zeroline=True, zerolinecolor="#2d4a7a"),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", automargin=True),
            margin=dict(t=40, b=20, l=20, r=80),
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

    # Holding period distribution
    hold_df = df_open[["Company", "Days Held"]].copy()
    hold_df["Bucket"] = hold_df["Days Held"].apply(
        lambda d: "< 6 Months" if d < 180
        else "6M – 1 Year" if d < 365
        else "1 – 2 Years" if d < 730
        else "> 2 Years"
    )
    bucket_colors = {
        "< 6 Months":  "#f59e0b",
        "6M – 1 Year": "#4a9eff",
        "1 – 2 Years": "#a78bfa",
        "> 2 Years":   "#22c55e",
    }
    hold_df = hold_df.sort_values("Days Held")
    h_colors = [bucket_colors[b] for b in hold_df["Bucket"]]
    fig_hold = go.Figure(go.Bar(
        x=hold_df["Company"],
        y=hold_df["Days Held"],
        marker_color=h_colors,
        text=hold_df["Days Held"].apply(lambda d: f"{d}d"),
        textposition="outside",
        textfont=dict(size=10),
    ))
    fig_hold.update_layout(
        **_CL,
        title=dict(text="Holding Period by Stock (days)", font=dict(size=12, color="#6b82a8"), x=0),
        height=280,
        xaxis=dict(gridcolor="rgba(0,0,0,0)"),
        yaxis=dict(title="Days", gridcolor="#1a2540"),
        margin=dict(t=40, b=20, l=60, r=20),
    )
    # Legend for buckets
    for bucket, color in bucket_colors.items():
        fig_hold.add_trace(go.Scatter(
            x=[None], y=[None], mode="markers",
            marker=dict(size=8, color=color, symbol="square"),
            name=bucket, showlegend=True,
        ))
    fig_hold.update_layout(
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1,
                    font=dict(color="#6b82a8", size=10)),
    )
    st.plotly_chart(fig_hold, use_container_width=True)

    st.divider()

    # ── Holdings Detail ────────────────────────────────────────────────────────
    section_label("Open Positions")

    disp_cols = [
        "Company", "Sector", "Sub-Industry",
        "Qty", "Avg Cost (₹)", "Price (₹)",
        "Cur. Value", "Weight %",
        "P&L (₹)", "P&L %", "XIRR %", "Days Held",
    ]

    def _pnl_color(v):
        if isinstance(v, (int, float)) and pd.notna(v):
            if v < 0:   return "color:#ef4444;font-weight:600"
            if v > 0:   return "color:#22c55e;font-weight:600"
        return ""

    styled_open = (
        df_open[disp_cols].style
        .format({
            "Avg Cost (₹)": "₹{:,.2f}",
            "Price (₹)":    "₹{:,.2f}",
            "Cur. Value":   lambda x: inr(x),
            "P&L (₹)":      lambda x: inr(x),
            "P&L %":        "{:+.2f}%",
            "Weight %":     "{:.1f}%",
            "XIRR %":       lambda x: f"{x:+.1f}%" if pd.notna(x) else "—",
        })
        .map(_pnl_color, subset=["P&L (₹)", "P&L %", "XIRR %"])
    )
    st.dataframe(styled_open, use_container_width=True, hide_index=True)

    if not df_closed.empty:
        section_label("Closed Positions")
        closed_cols = ["Company", "Sector", "Qty", "Avg Cost (₹)", "Price (₹)",
                       "Cur. Value", "P&L (₹)", "P&L %", "Days Held", "XIRR %"]
        st.dataframe(
            df_closed[closed_cols].style
            .format({
                "Avg Cost (₹)": "₹{:,.2f}",
                "Price (₹)":    "₹{:,.2f}",
                "Cur. Value":   lambda x: inr(x),
                "P&L (₹)":      lambda x: inr(x),
                "P&L %":        "{:+.2f}%",
                "XIRR %":       lambda x: f"{x:+.1f}%" if pd.notna(x) else "—",
            })
            .map(_pnl_color, subset=["P&L (₹)", "P&L %", "XIRR %"]),
            use_container_width=True, hide_index=True,
        )

    st.divider()

    # ── Stress Scenarios ───────────────────────────────────────────────────────
    section_label("Stress Scenarios — Portfolio Value")

    scenarios = [
        ("Correction −10%",   -10),
        ("Bear Market −25%",  -25),
        ("Severe Crash −40%", -40),
        ("Black Swan −55%",   -55),
    ]
    sc_cols = st.columns(4)
    for col, (label, drop) in zip(sc_cols, scenarios):
        stressed = total_val * (1 + drop / 100)
        vs_cost  = (stressed - total_cost) / total_cost * 100
        chg_color = "#ef4444" if vs_cost < 0 else "#22c55e"
        col.markdown(
            f"<div class='stress-card'>"
            f"<div class='stress-label'>{label}</div>"
            f"<div class='stress-val'>{inr(stressed)}</div>"
            f"<div class='stress-chg' style='color:{chg_color}'>{vs_cost:+.1f}% vs cost</div>"
            f"</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── XIRR Drill-Down ───────────────────────────────────────────────────────
    section_label("XIRR Drill-Down")

    xirr_options  = []
    seen_combined = False
    combined_keys = {ABFRL, ABLBL}
    for co in sorted(pos.keys(), key=lambda c: active_display.get(c, c)):
        if co in combined_keys:
            if not seen_combined:
                xirr_options.append("ABFRL + ABLBL (combined)")
                seen_combined = True
        else:
            xirr_options.append(active_display.get(co, co))

    selected = st.selectbox("Select company:", xirr_options)

    if selected == "ABFRL + ABLBL (combined)":
        lookup = ABFRL
    else:
        lookup = next((k for k, v in active_display.items() if v == selected), selected)

    xi, cf_rows = get_xirr_cashflows(lookup, txns, pos, prices)

    m1, m2, m3 = st.columns(3)
    m1.metric("XIRR", f"{xi*100:.2f}%" if xi is not None else "—")
    total_inv_co = (
        sum(pos.get(c, {}).get("total_cost", 0) for c in combined_keys)
        if selected == "ABFRL + ABLBL (combined)"
        else pos.get(lookup, {}).get("total_cost", 0)
    )
    cur_val_co = cf_rows[-1]["Cash Flow"] if cf_rows else 0
    m2.metric("Invested", inr(total_inv_co))
    m3.metric("Current Value", inr(cur_val_co))

    cf_df = pd.DataFrame(cf_rows)
    cf_df["Cash Flow (₹)"] = cf_df["Cash Flow"].apply(inr)
    cf_df["Date"] = cf_df["Date"].astype(str)
    st.dataframe(cf_df[["Date", "Event", "Qty", "Cash Flow (₹)"]], use_container_width=True, hide_index=True)

    fig_wf = go.Figure(go.Waterfall(
        orientation="v",
        x=[f"{r['Date']}\n{r['Event'].split('—')[0].strip()}" for r in cf_rows],
        y=[r["Cash Flow"] for r in cf_rows],
        text=[inr(r["Cash Flow"]) for r in cf_rows],
        textposition="outside",
        connector={"line": {"color": "#1e2d4d"}},
        increasing={"marker": {"color": "#22c55e"}},
        decreasing={"marker": {"color": "#ef4444"}},
        totals={"marker":    {"color": "#4a9eff"}},
    ))
    fig_wf.update_layout(
        **_CL,
        title=dict(text=f"Cash Flow Timeline — {selected}", font=dict(size=12, color="#6b82a8"), x=0),
        yaxis=dict(title="₹", gridcolor="#1a2540"),
        height=400,
        margin=dict(t=50, b=40, l=70, r=60),
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # ── Transaction History ────────────────────────────────────────────────────
    with st.expander("Transaction History (corporate-action adjusted)"):
        hist = pd.DataFrame([{
            "Date":      t["date"],
            "Company":   DISPLAY.get(t["company"], t["company"]),
            "Type":      t["type"],
            "Product":   t["product_type"],
            "Qty":       int(round(t["qty"])),
            "Adj Price": f"₹{t['price']:,.2f}",
            "Value":     inr(t["value"]),
            "Note":      t.get("note", ""),
        } for t in txns]).sort_values("Date", ascending=False)
        st.dataframe(hist, use_container_width=True, hide_index=True)

    st.divider()

    # ── Watchlist Intelligence ─────────────────────────────────────────────────
    section_label("Research Pipeline · Watchlist")

    watchlist = load_watchlist()
    if not watchlist:
        st.info("No entries in Watchlist yet.")
    else:
        df_wl = pd.DataFrame(watchlist)

        # Pipeline status summary
        status_counts = df_wl["Status"].value_counts()
        if len(status_counts):
            wl_cols = st.columns(min(len(status_counts), 5))
            for col, (status, count) in zip(wl_cols, status_counts.items()):
                if status:
                    col.metric(status or "Unknown", str(count), "companies")

        st.markdown("<br>", unsafe_allow_html=True)

        wl_l, wl_r = st.columns([4, 6])

        with wl_l:
            # Watchlist sector distribution
            wl_sect = (
                df_wl[df_wl["Sector"] != ""]["Sector"]
                .value_counts()
                .reset_index()
            )
            wl_sect.columns = ["Sector", "Count"]
            fig_wls = go.Figure(go.Bar(
                x=wl_sect["Count"],
                y=wl_sect["Sector"],
                orientation="h",
                marker_color="#4a9eff",
                text=wl_sect["Count"],
                textposition="outside",
            ))
            fig_wls.update_layout(
                **_CL,
                title=dict(text="Watchlist by Sector", font=dict(size=12, color="#6b82a8"), x=0),
                height=max(280, len(wl_sect) * 28 + 60),
                xaxis=dict(gridcolor="#1a2540", title=""),
                yaxis=dict(gridcolor="rgba(0,0,0,0)", automargin=True),
                margin=dict(t=40, b=20, l=20, r=40),
            )
            st.plotly_chart(fig_wls, use_container_width=True)

        with wl_r:
            # Filtered watchlist table
            f1, f2, f3 = st.columns(3)
            statuses    = sorted(s for s in df_wl["Status"].unique() if s)
            sel_status  = f1.multiselect("Status",  statuses, default=statuses)
            analysts    = sorted(a for a in df_wl["Analyst"].unique() if a)
            sel_analyst = f2.multiselect("Analyst", analysts, default=analysts) if analysts else []
            sectors_wl  = sorted(s for s in df_wl["Sector"].unique() if s)
            sel_sector  = f3.multiselect("Sector",  sectors_wl, default=sectors_wl) if sectors_wl else []

            mask = df_wl["Status"].isin(sel_status) | ~df_wl["Status"].isin(statuses)
            if sel_analyst:
                mask &= df_wl["Analyst"].isin(sel_analyst) | ~df_wl["Analyst"].isin(analysts)
            if sel_sector:
                mask &= df_wl["Sector"].isin(sel_sector) | ~df_wl["Sector"].isin(sectors_wl)
            df_show = df_wl[mask].reset_index(drop=True)

            show_cols = [
                "Company", "Analyst", "Sector",
                "CMP (₹)", "52W High (₹)", "52W Low (₹)", "P/E",
                "Last Disc. Date", "Last Disc. Price (₹)", "Chg since LDP %",
                "Status", "Notes",
            ]

            def _color_chg(val):
                if isinstance(val, str) and val.startswith("+"):
                    return "color:#22c55e;font-weight:600"
                if isinstance(val, str) and val.startswith("-"):
                    return "color:#ef4444;font-weight:600"
                return ""

            st.dataframe(
                df_show[show_cols].style.map(_color_chg, subset=["Chg since LDP %"]),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(f"{len(df_show)} of {len(df_wl)} companies shown")

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        f"As of {datetime.now().strftime('%d %b %Y, %I:%M %p')}  ·  "
        "Prices: NSE live via yfinance (15-min delay), manual fallback where unavailable  ·  "
        "ABFRL XIRR = ABFRL + ABLBL combined  ·  "
        "Cost basis: Qty × Price, no charges  ·  "
        "Sectors: TheWrap Market Map"
    )


if __name__ == "__main__":
    main()
