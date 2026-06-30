"""
Speciale Incept — Listed Equity Portfolio · IC Dashboard
Data source: Google Sheets — All Trades tab
"""
import sys
sys.stdout.reconfigure(encoding="utf-8")

from datetime import date, datetime, timedelta
from collections import defaultdict
import urllib.parse

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
from streamlit_plotly_events import plotly_events

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Speciale Incept · IC Dashboard",
    page_icon="S",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SPREADSHEET_ID = "14zSRp_Q8bOU6w9Z3gz6csV9FFNTC37jitur7I_Egeqg"
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]

ABFRL_DEMERGE_DATE = date(2025, 5, 22)
ABFRL              = "Aditya Birla Fashion and Retail Ltd"
ABLBL              = "Aditya Birla Lifestyle Brands Ltd"

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

# Sector mapping — TheWrap sourced + overrides  (sub-industry, broad sector)
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

SECTOR_PALETTE = {
    "BFSI":                 "#818cf8",
    "Technology":           "#a78bfa",
    "Healthcare":           "#10b981",
    "Chemicals":            "#fbbf24",
    "Auto":                 "#f97316",
    "Retail & Hospitality": "#ec4899",
    "Building Materials":   "#38bdf8",
    "Food & Agri":          "#4ade80",
    "Other":                "#94a3b8",
}

# Market-cap classification (SEBI: Large=top 100, Mid=101-250, Small=251+)
CAP_CLASS = {
    "HDFC Bank":        "Large",
    "Federal Bank":     "Mid",
    "Nykaa":            "Mid",
    "Guj. Fluorochem":  "Mid",
    "EID Parry":        "Mid",
    "Indegene":         "Mid",
    "ABFRL":            "Mid",
    "Sundaram Clayton": "Small",
    "Greenlam":         "Small",
    "ABLBL":            "Small",
    "Aether":           "Small",
    "Sansera":          "Small",
}
CAP_COLOR = {"Large": "#818cf8", "Mid": "#fbbf24", "Small": "#34d399"}

# ── Theme constants ────────────────────────────────────────────────────────────
BG     = "#18181b"   # zinc-900  dark grey page background
CARD   = "#27272a"   # zinc-800  card / chart background
BORDER = "#3f3f46"   # zinc-700  borders, gridlines
T1     = "#fafafa"   # zinc-50   primary text (near-white)
T2     = "#d4d4d8"   # zinc-300  secondary text (light grey)
T3     = "#71717a"   # zinc-500  muted text
POS    = "#22c55e"   # green-500
NEG    = "#ef4444"   # red-500
ACC    = "#818cf8"   # indigo-400
GOLD   = "#fbbf24"   # amber-400
FONT   = "'Aptos Display', 'Segoe UI Variable Display', 'Segoe UI', system-ui, sans-serif"

# Base chart layout — NO xaxis/yaxis here (each chart sets those individually)
def _chart_base(height=380, t=40, b=20, l=20, r=20):
    return dict(
        paper_bgcolor=CARD,
        plot_bgcolor=BG,
        font=dict(color=T2, size=11, family=FONT),
        height=height,
        margin=dict(t=t, b=b, l=l, r=r),
    )


# ── CSS ────────────────────────────────────────────────────────────────────────
_CSS = f"""
<style>
@font-face {{
    font-family: 'Aptos Display';
    src: local('Aptos Display'), local('Aptos-Display');
}}

html, body, * {{
    font-family: {FONT} !important;
}}
/* Restore Material Symbols for Streamlit UI icons */
[data-testid="stIconMaterial"] {{
    font-family: 'Material Symbols Rounded', 'Material Icons' !important;
}}

/* Metric cards */
[data-testid="stMetric"] {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 18px 22px !important;
    box-shadow: 0 4px 14px rgba(0,0,0,0.55), 0 0 0 1px {BORDER};
}}
[data-testid="stMetricLabel"] p {{
    color: {T3} !important;
    font-size: 10px !important;
    font-weight: 700 !important;
    text-transform: uppercase;
    letter-spacing: 1.4px;
}}
[data-testid="stMetricValue"] {{
    color: {T1} !important;
    font-size: 24px !important;
    font-weight: 700 !important;
}}
[data-testid="stMetricDelta"] > div {{
    font-size: 12px !important;
    font-weight: 600 !important;
}}

/* Buttons */
[data-testid="baseButton-secondary"] {{
    background: {CARD} !important;
    color: {ACC} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 8px !important;
    font-weight: 600 !important;
    font-size: 12px !important;
}}
[data-testid="baseButton-secondary"]:hover {{
    border-color: {ACC} !important;
    background: rgba(129,140,248,0.18) !important;
}}

/* DataFrames */
[data-testid="stDataFrame"] {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    overflow: hidden;
}}

/* Expanders */
details {{
    background: {CARD} !important;
    border: 1px solid {BORDER} !important;
    border-radius: 10px !important;
}}
summary {{ color: {T2} !important; font-weight: 600; font-size: 13px; }}

/* Multiselect */
[data-baseweb="tag"] {{ background: #e0e7ff !important; color: #18181b !important; }}
[data-baseweb="tag"] span {{ color: #18181b !important; }}
[data-baseweb="tag"] svg {{ fill: #18181b !important; }}
[data-baseweb="menu"] li {{ color: #18181b !important; }}
[data-baseweb="select"] [data-testid="stMarkdownContainer"] {{ color: #18181b !important; }}

/* Dividers */
hr {{ border-color: {BORDER} !important; }}

/* Caption */
.stCaption p {{ color: {T3} !important; font-size: 11px !important; }}

/* Selectbox */
[data-baseweb="select"] > div {{
    background: {CARD} !important;
    border-color: {BORDER} !important;
}}

.ic-label {{
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: {T2};
    margin-bottom: 14px;
    margin-top: 6px;
    display: block;
}}

/* Treemap expanded company card */
@keyframes expandCard {{
    from {{ opacity: 0; transform: scale(0.82) translateY(16px); }}
    to   {{ opacity: 1; transform: scale(1)    translateY(0);     }}
}}
@keyframes fadeChart {{
    from {{ opacity: 0; }}
    to   {{ opacity: 1; }}
}}
.company-expanded {{
    background: linear-gradient(145deg, #2d2d35 0%, #1e1e28 100%);
    border: 1px solid {BORDER};
    border-radius: 16px;
    padding: 32px 28px 24px 28px;
    min-height: 340px;
    animation: expandCard 0.38s cubic-bezier(0.34,1.56,0.64,1) forwards;
    display: flex;
    flex-direction: column;
    gap: 20px;
    font-family: {FONT};
}}
.company-exp-name {{
    font-size: 26px; font-weight: 800; color: {T1};
    letter-spacing: -0.5px; line-height: 1.1;
}}
.company-exp-sector {{
    font-size: 11px; color: {T3};
    text-transform: uppercase; letter-spacing: 1.8px; margin-top: -12px;
}}
.company-exp-grid {{
    display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; margin-top: 4px;
}}
.exp-metric {{
    background: rgba(255,255,255,0.04); border: 1px solid {BORDER};
    border-radius: 10px; padding: 14px 16px;
}}
.exp-label {{
    font-size: 9px; font-weight: 700; letter-spacing: 1.6px;
    text-transform: uppercase; color: {T3}; margin-bottom: 8px;
}}
.exp-val {{ font-size: 18px; font-weight: 700; color: {T1}; line-height: 1.2; }}
.exp-delta {{ font-size: 12px; font-weight: 600; margin-top: 3px; }}
.back-hint {{ font-size: 11px; color: {T3}; margin-top: 8px; text-align: center; }}

[data-testid="stPlotlyChart"] {{ animation: fadeChart 0.35s ease; }}

/* Portfolio card grid */
.port-card {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 12px;
    padding: 18px 18px 16px 22px;
    position: relative;
    overflow: hidden;
    display: block;
    cursor: pointer;
    transition: border-color 0.18s ease, box-shadow 0.18s ease;
    margin-bottom: 0;
}}
.port-card:hover {{
    border-color: #52525b;
    box-shadow: 0 6px 20px rgba(0,0,0,0.5);
}}
.port-accent {{
    position: absolute; left: 0; top: 0; bottom: 0; width: 4px;
    border-radius: 12px 0 0 12px;
}}
.port-name {{ font-size: 13px; font-weight: 700; color: {T1}; margin-bottom: 3px; }}
.port-sec {{
    font-size: 9px; color: {T3};
    text-transform: uppercase; letter-spacing: 1px;
    margin-bottom: 14px;
}}
.port-metrics {{ display: flex; gap: 18px; }}
.pm {{ display: flex; flex-direction: column; gap: 2px; }}
.pm-label {{ font-size: 9px; color: {T3}; text-transform: uppercase; letter-spacing: 0.7px; }}
.pm-val {{ font-size: 14px; font-weight: 700; color: {T1}; line-height: 1.2; }}
/* Cap chip */
.cap-chip {{
    display: inline-block; font-size: 8px; font-weight: 700;
    letter-spacing: 0.7px; text-transform: uppercase;
    padding: 2px 6px; border-radius: 4px; margin-left: 7px;
    vertical-align: middle; line-height: 1.6;
}}
.cap-large {{ background: rgba(129,140,248,0.18); color: #818cf8; }}
.cap-mid   {{ background: rgba(251,191,36,0.18);  color: #fbbf24; }}
.cap-small {{ background: rgba(52,211,153,0.18);  color: #34d399; }}
</style>
"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def lbl(text):
    st.markdown(f'<span class="ic-label">{text}</span>', unsafe_allow_html=True)


def inr(val):
    sign = "-" if val < 0 else ""
    v = abs(val)
    if v >= 1e7: return f"{sign}\u20b9{v/1e7:.2f} Cr"
    if v >= 1e5: return f"{sign}\u20b9{v/1e5:.2f} L"
    return f"{sign}\u20b9{v:,.0f}"


def pnl_style(v):
    if isinstance(v, (int, float)) and pd.notna(v):
        if v < 0: return f"color:{NEG};font-weight:600"
        if v > 0: return f"color:{POS};font-weight:600"
    return ""


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
    gc = gspread.authorize(creds)
    try:
        ws   = gc.open_by_key(SPREADSHEET_ID).worksheet("SI_Portfolio")
        rows = ws.get("A1:B200", value_render_option="FORMATTED_VALUE")
        tickers = {}
        for r in rows:
            if len(r) < 2:
                continue
            co, tk = r[0].strip(), r[1].strip()
            if co and tk and tk.upper() == tk:
                tickers[co] = tk + ".NS"
        return tickers, {}
    except Exception:
        return {}, {}


@st.cache_data(ttl=900)
def load_watchlist():
    creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet("Watchlist")
    rows = ws.get("B4:O1000", value_render_option="FORMATTED_VALUE")
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
            "CMP (Rs)":             r[4],
            "52W High (Rs)":        r[5],
            "52W Low (Rs)":         r[6],
            "P/E":                  r[8],
            "Last Disc. Date":      r[9],
            "Last Disc. Price (Rs)":r[10],
            "Chg since LDP %":      r[11],
            "Status":               r[12],
            "Notes":                r[13],
        })
    return result


@st.cache_data(ttl=3600)
def load_raw_transactions():
    creds = Credentials.from_service_account_info(
                dict(st.secrets["gcp_service_account"]), scopes=SCOPES)
    gc = gspread.authorize(creds)
    ws = gc.open_by_key(SPREADSHEET_ID).worksheet("All Trades")
    rows = ws.get("A2:M10000", value_render_option="UNFORMATTED_VALUE")
    result = []
    for r in rows:
        if len(r) < 11:
            continue
        d    = _parse_date(r[1])
        name = r[4].strip() if isinstance(r[4], str) else str(r[4])
        txn  = r[8].strip() if isinstance(r[8], str) else str(r[8])
        prod = r[9].strip() if isinstance(r[9], str) else str(r[9])
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
    adjusted, abfrl_lots = [], []
    for t in raw:
        t = dict(t)
        co, d, ttype, prod = t["company"], t["date"], t["type"], t["product_type"]
        if co == ABLBL and prod == "Demerger":
            continue
        if co == ABFRL and ttype == "BUY" and d < ABFRL_DEMERGE_DATE:
            orig_price, orig_value = t["price"], t["value"]
            t["orig_value"] = orig_value
            t["price"]      = orig_price / 2
            t["value"]      = orig_value / 2
            t["note"]       = f"Demerger adj /2 (orig {orig_price:,.2f})"
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
        if t["company"] not in group or t["product_type"] == "DEMERGER":
            continue
        if t["type"] == "BUY":
            val = t.get("orig_value", t["value"])
            cfs.append((t["date"], -val))
            rows.append({"Date": t["date"],
                         "Event": f"BUY  {DISPLAY.get(t['company'], t['company'])}",
                         "Qty": int(round(t["qty"])), "Cash Flow": -val})
        elif t["type"] == "SELL":
            cfs.append((t["date"], t["value"]))
            rows.append({"Date": t["date"],
                         "Event": f"SELL {DISPLAY.get(t['company'], t['company'])}",
                         "Qty": -int(round(t["qty"])), "Cash Flow": t["value"]})
    terminal = sum(positions.get(c, {}).get("qty", 0) * prices.get(c, 0) for c in group)
    cfs.append((date.today(), terminal))
    rows.append({"Date": date.today(), "Event": "Current Value (terminal)",
                 "Qty": int(round(sum(positions.get(c, {}).get("qty", 0) for c in group))),
                 "Cash Flow": terminal})
    return _xirr(cfs), rows


def compute_xirr_all(txns, positions, prices):
    combined = {ABFRL, ABLBL}
    xirr_map = {}
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
    for co, p in positions.items():
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
        cur_val = p["qty"] * prices.get(co, 0)
        if cur_val > 0:
            cfs.append((date.today(), cur_val))
        xirr_map[co] = _xirr(cfs)
    return xirr_map


# ── Popup dialogs ─────────────────────────────────────────────────────────────
@st.dialog("Sector Breakdown")
def _sector_popup(sector, rows):
    st.markdown(
        f"<div style='font-size:15px;font-weight:700;color:{T1};"
        f"font-family:{FONT};margin-bottom:14px;'>{sector}</div>",
        unsafe_allow_html=True,
    )
    for r in rows:
        c1, c2, c3, c4 = st.columns([5, 3, 2, 2])
        c1.write(r["Company"])
        c2.write(r["_val_str"])
        c3.write(f"{r['Weight %']:.1f}%")
        c4.markdown(
            f"<span style='color:{'#059669' if r['P&L %'] >= 0 else '#dc2626'};font-weight:600'>"
            f"{r['P&L %']:+.1f}%</span>",
            unsafe_allow_html=True,
        )


def _cap_popup(cap_label, rows):
    cap_color = CAP_COLOR.get(cap_label, ACC)
    st.markdown(
        f"<div style='font-size:15px;font-weight:700;color:{cap_color};"
        f"font-family:{FONT};margin-bottom:14px;'>{cap_label} Cap</div>",
        unsafe_allow_html=True,
    )
    for r in rows:
        c1, c2, c3, c4 = st.columns([5, 3, 2, 2])
        c1.write(r["Company"])
        c2.write(r["_val_str"])
        c3.write(f"{r['Weight %']:.1f}%")
        c4.markdown(
            f"<span style='color:{'#059669' if r['P&L %'] >= 0 else '#dc2626'};font-weight:600'>"
            f"{r['P&L %']:+.1f}%</span>",
            unsafe_allow_html=True,
        )


# ── App ────────────────────────────────────────────────────────────────────────
def main():
    st.markdown(_CSS, unsafe_allow_html=True)

    # ── Header ────────────────────────────────────────────────────────────────
    hdr_l, hdr_r = st.columns([5, 1])
    hdr_l.markdown(
        f"<div style='padding:4px 0 20px 0;border-bottom:2px solid {BORDER};'>"
        f"<div style='font-size:22px;font-weight:800;color:{T1};letter-spacing:-0.5px;"
        f"font-family:{FONT};'>SPECIALE INCEPT</div>"
        f"<div style='font-size:10px;color:{T3};letter-spacing:2px;text-transform:uppercase;"
        f"margin-top:4px;font-family:{FONT};'>"
        f"Listed Equity Portfolio &nbsp;&middot;&nbsp; IC Dashboard &nbsp;&middot;&nbsp; "
        f"{datetime.now().strftime('%d %b %Y')}</div></div>",
        unsafe_allow_html=True,
    )
    with hdr_r:
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("Refresh", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Load data ─────────────────────────────────────────────────────────────
    _, sheet_display = load_ticker_map()
    active_display   = {**DISPLAY, **sheet_display}

    raw  = load_raw_transactions()
    txns = apply_corporate_actions(raw)
    pos  = build_positions(txns)

    with st.spinner("Fetching live prices..."):
        prices, sources = fetch_prices(tuple(pos.keys()))

    xirr_map = compute_xirr_all(txns, pos, prices)

    # ── Build rows ────────────────────────────────────────────────────────────
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
        sub, broad = SECTORS.get(co, ("Other", "Other"))
        row = {
            "Company":      active_display.get(co, co),
            "_key":         co,
            "Sector":       broad,
            "Sub-Industry": sub,
            "Qty":          int(round(qty)),
            "Avg Cost":     round(avg_cost, 2),
            "Total Cost":   cost,
            "CMP":          price,
            "Cur. Value":   cur_val,
            "P&L":          pnl,
            "P&L %":        pnl_pct,
            "Days Held":    days,
            "XIRR %":       round(xi * 100, 1) if xi is not None else None,
            "Source":       sources.get(co, "—"),
        }
        if qty > 0.5:
            rows_open.append(row)
        else:
            tot_paid       = sum(t["value"] for t in txns if t["company"] == co and t["type"] == "BUY")
            sell_txns      = [t for t in txns if t["company"] == co and t["type"] == "SELL"]
            total_sold_qty = sum(t["qty"] for t in sell_txns)
            avg_sell       = sell_val / total_sold_qty if total_sold_qty else 0
            row["Qty"]        = int(round(total_sold_qty))
            row["Total Cost"] = tot_paid
            row["Cur. Value"] = sell_val
            row["P&L"]        = sell_val - tot_paid
            row["P&L %"]      = (sell_val - tot_paid) / tot_paid * 100 if tot_paid else 0
            row["CMP"]        = avg_sell
            row["Avg Cost"]   = tot_paid / total_sold_qty if total_sold_qty else 0
            rows_closed.append(row)

    df_open   = pd.DataFrame(rows_open).sort_values("Cur. Value", ascending=False).reset_index(drop=True)
    df_closed = pd.DataFrame(rows_closed).reset_index(drop=True) if rows_closed else pd.DataFrame()

    if df_open.empty:
        st.warning("No open positions found.")
        return

    total_cost = df_open["Total Cost"].sum()
    total_val  = df_open["Cur. Value"].sum()
    total_pnl  = df_open["P&L"].sum()
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0

    total_realized = df_closed["P&L"].sum() if not df_closed.empty else 0.0
    win_rate = (
        len(df_closed[df_closed["P&L"] > 0]) / len(df_closed) * 100
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

    df_open["Weight %"] = df_open["Cur. Value"] / total_val * 100

    # ── KPI Strip ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric("Total Invested",  inr(total_cost))
    k2.metric("Current Value",   inr(total_val))
    k3.metric("Unrealised P&L",  inr(total_pnl), f"{total_pnl_pct:+.1f}%")
    k4.metric("Portfolio XIRR",  f"{port_xirr*100:.1f}%" if port_xirr else "—")
    k5.metric("Open Positions",  str(len(df_open)))
    k6.metric("Realised P&L",    inr(total_realized),
              f"Win rate {win_rate:.0f}%" if win_rate is not None else "—")

    st.markdown("<br>", unsafe_allow_html=True)
    st.divider()

    # ── Performance ────────────────────────────────────────────────────────────
    lbl("Performance")
    perf_l, perf_r = st.columns(2)

    with perf_l:
        xi_df = df_open[["Company", "XIRR %"]].dropna().sort_values("XIRR %")
        _xi_h  = max(420, len(xi_df) * 38 + 80)
        _LABEL_FONT = "Aptos Display, Segoe UI, sans-serif"
        fig_xi = go.Figure(go.Bar(
            x=xi_df["XIRR %"], y=xi_df["Company"], orientation="h",
            marker_color=[NEG if v < 0 else POS for v in xi_df["XIRR %"]],
            hovertemplate="<b>%{y}</b><br>XIRR: %{x:+.1f}%<extra></extra>",
        ))
        xi_annotations = [dict(
            xref="paper", yref="y", x=0.99, y=row["Company"],
            text=f"{row['XIRR %']:+.1f}%", showarrow=False, xanchor="right",
            font=dict(size=10, family=_LABEL_FONT, color="#ffffff"),
        ) for _, row in xi_df.iterrows()]
        fig_xi.update_layout(
            **_chart_base(_xi_h, t=44, r=60),
            title=dict(text="XIRR by Stock", font=dict(size=12, color=T1, family=FONT), x=0),
            xaxis=dict(showticklabels=False, gridcolor=BORDER, zeroline=True,
                       zerolinecolor=BORDER, showgrid=False),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", automargin=True,
                       tickfont=dict(family=_LABEL_FONT, color=T1),
                       range=[-0.6, len(xi_df) - 0.4]),
            annotations=xi_annotations,
        )
        st.plotly_chart(fig_xi, use_container_width=True)

    with perf_r:
        pnl_df = df_open.sort_values("P&L %")
        _pnl_h = max(420, len(pnl_df) * 38 + 80)
        fig_pnl = go.Figure(go.Bar(
            x=pnl_df["P&L %"], y=pnl_df["Company"], orientation="h",
            marker_color=[NEG if v < 0 else POS for v in pnl_df["P&L %"]],
            hovertemplate="<b>%{y}</b><br>P&L: %{x:+.1f}%<extra></extra>",
        ))
        pnl_annotations = [dict(
            xref="paper", yref="y", x=0.99, y=row["Company"],
            text=f"{row['P&L %']:+.1f}%", showarrow=False, xanchor="right",
            font=dict(size=10, family=_LABEL_FONT, color="#ffffff"),
        ) for _, row in pnl_df.iterrows()]
        fig_pnl.update_layout(
            **_chart_base(_pnl_h, t=44, r=60),
            title=dict(text="Unrealised P&L %", font=dict(size=12, color=T1, family=FONT), x=0),
            xaxis=dict(showticklabels=False, gridcolor=BORDER, zeroline=True,
                       zerolinecolor=BORDER, showgrid=False),
            yaxis=dict(gridcolor="rgba(0,0,0,0)", automargin=True,
                       tickfont=dict(family=_LABEL_FONT, color=T1),
                       range=[-0.6, len(pnl_df) - 0.4]),
            annotations=pnl_annotations,
        )
        st.plotly_chart(fig_pnl, use_container_width=True)

    st.divider()

    # ── Portfolio ──────────────────────────────────────────────────────────────
    lbl("Portfolio")
    comp_l, comp_r = st.columns([6, 4])

    with comp_l:
        if "selected_company" not in st.session_state:
            st.session_state.selected_company = None

        if st.session_state.selected_company:
            co  = st.session_state.selected_company
            match = df_open[df_open["Company"] == co]
            if not match.empty:
                r = match.iloc[0]
                pc = POS if r["P&L"] >= 0 else NEG
                ps = "+" if r["P&L"] >= 0 else ""
                xi_str = f"{r['XIRR %']:+.1f}%" if pd.notna(r["XIRR %"]) else "—"
                xi_col = (POS if pd.notna(r["XIRR %"]) and r["XIRR %"] >= 0 else NEG) if pd.notna(r["XIRR %"]) else T3
                st.markdown(f"""
<div class="company-expanded">
  <div class="company-exp-name">{co}</div>
  <div class="company-exp-sector">{r['Sub-Industry']} &nbsp;·&nbsp; {r['Sector']}</div>
  <div class="company-exp-grid">
    <div class="exp-metric">
      <div class="exp-label">Invested Value</div>
      <div class="exp-val">{inr(r['Total Cost'])}</div>
    </div>
    <div class="exp-metric">
      <div class="exp-label">Current Value</div>
      <div class="exp-val">{inr(r['Cur. Value'])}</div>
    </div>
    <div class="exp-metric">
      <div class="exp-label">Profit / Loss</div>
      <div class="exp-val" style="color:{pc}">{ps}{inr(r['P&L'])}</div>
      <div class="exp-delta" style="color:{pc}">{r['P&L %']:+.1f}%</div>
    </div>
    <div class="exp-metric">
      <div class="exp-label">Portfolio Weight</div>
      <div class="exp-val">{r['Weight %']:.1f}%</div>
    </div>
    <div class="exp-metric">
      <div class="exp-label">XIRR</div>
      <div class="exp-val" style="color:{xi_col}">{xi_str}</div>
    </div>
    <div class="exp-metric">
      <div class="exp-label">Days Held</div>
      <div class="exp-val">{r['Days Held']}</div>
    </div>
  </div>
  <div class="back-hint">click ← Portfolio Map to go back</div>
</div>
""", unsafe_allow_html=True)
            if st.button("← Portfolio Map", key="back_to_tm",
                         use_container_width=True):
                st.session_state.selected_company = None
                st.rerun()
        else:
            # Handle card click via query param
            _pc = st.query_params.get("pc", "")
            if _pc:
                _co = urllib.parse.unquote(_pc)
                if not df_open[df_open["Company"] == _co].empty:
                    st.session_state.selected_company = _co
                    st.query_params.clear()
                    st.rerun()

            # Handle cap bar click via query param
            if "selected_cap" not in st.session_state:
                st.session_state.selected_cap = None
            _cap_qp = st.query_params.get("cap", "")
            if _cap_qp in ["Large", "Mid", "Small"]:
                st.session_state.selected_cap = _cap_qp
                st.query_params.clear()
                st.rerun()

            card_df = df_open.sort_values("Weight %", ascending=False).reset_index(drop=True)
            card_df["_Cap"] = card_df["Company"].map(CAP_CLASS).fillna("Mid")

            # Cap allocation summary bar
            _cap_alloc = {c: card_df[card_df["_Cap"] == c]["Weight %"].sum()
                          for c in ["Large", "Mid", "Small"]}
            # Derive third cap as remainder to guarantee sum = 100.0
            _large_r = round(_cap_alloc.get("Large", 0), 1)
            _mid_r   = round(_cap_alloc.get("Mid", 0), 1)
            _small_r = round(100.0 - _large_r - _mid_r, 1)
            _cap_rounded = {"Large": _large_r, "Mid": _mid_r, "Small": _small_r}
            _bar_segs  = "".join(
                f"<div style='width:{_cap_rounded[c]:.1f}%;background:{CAP_COLOR[c]};height:100%;'></div>"
                for c in ["Large", "Mid", "Small"] if _cap_rounded.get(c, 0) > 0
            )
            _leg_items = "".join(
                f"<a href='?cap={c}' target='_self' style='text-decoration:none;'>"
                f"<span style='font-size:11px;color:{T2};display:flex;align-items:center;gap:5px;cursor:pointer;'>"
                f"<span style='width:8px;height:8px;border-radius:50%;background:{CAP_COLOR[c]};display:inline-block;'></span>"
                f"<span style='color:{T3};font-size:9px;text-transform:uppercase;letter-spacing:0.8px;'>{c} Cap</span>"
                f"&nbsp;<b style='color:{T1};font-size:13px;'>{_cap_rounded.get(c,0):.1f}%</b></span></a>"
                for c in ["Large", "Mid", "Small"] if _cap_rounded.get(c, 0) > 0
            )
            st.markdown(
                f"<div style='display:flex;border-radius:6px;overflow:hidden;height:7px;margin-bottom:10px;gap:2px;'>{_bar_segs}</div>"
                f"<div style='display:flex;gap:20px;margin-bottom:14px;'>{_leg_items}</div>",
                unsafe_allow_html=True,
            )

            # Cap popup
            if st.session_state.selected_cap:
                _cap = st.session_state.selected_cap
                _cap_sub = (
                    card_df[card_df["_Cap"] == _cap][["Company", "Cur. Value", "Weight %", "P&L %"]]
                    .sort_values("Cur. Value", ascending=False)
                    .reset_index(drop=True)
                )
                _cap_sub["_val_str"] = _cap_sub["Cur. Value"].apply(inr)
                _cap_popup(_cap, _cap_sub.to_dict("records"))
                if st.button("← Back", key="close_cap_popup"):
                    st.session_state.selected_cap = None
                    st.rerun()

            _NC = 3
            for _i in range(0, len(card_df), _NC):
                _batch = card_df.iloc[_i : _i + _NC]
                _ccols = st.columns(_NC)
                for _ccol, (_, r) in zip(_ccols, _batch.iterrows()):
                    with _ccol:
                        pnl_c    = POS if r["P&L %"] >= 0 else NEG
                        xi_str   = f"{r['XIRR %']:+.1f}%" if pd.notna(r["XIRR %"]) else "—"
                        xi_c     = (POS if pd.notna(r["XIRR %"]) and r["XIRR %"] >= 0 else NEG) \
                                    if pd.notna(r["XIRR %"]) else T3
                        cap_cls  = r["_Cap"]
                        co_enc   = urllib.parse.quote(r["Company"])
                        st.markdown(f"""
<a href="?pc={co_enc}" target="_self" style="text-decoration:none;display:block;margin-bottom:10px">
<div class="port-card">
  <div class="port-accent" style="background:{pnl_c}"></div>
  <div class="port-name">{r['Company']}</div>
  <div class="port-sec">{r['Sector']}<span class="cap-chip cap-{cap_cls.lower()}">{cap_cls}</span></div>
  <div class="port-metrics">
    <div class="pm">
      <div class="pm-label">Weight</div>
      <div class="pm-val">{r['Weight %']:.1f}%</div>
    </div>
    <div class="pm">
      <div class="pm-label">P&amp;L</div>
      <div class="pm-val" style="color:{pnl_c}">{r['P&L %']:+.1f}%</div>
    </div>
    <div class="pm">
      <div class="pm-label">XIRR</div>
      <div class="pm-val" style="color:{xi_c}">{xi_str}</div>
    </div>
  </div>
</div>
</a>""", unsafe_allow_html=True)

    with comp_r:
        sect_df = (
            df_open.groupby("Sector")["Cur. Value"].sum()
            .reset_index().sort_values("Cur. Value", ascending=False)
        )
        sect_df["Weight %"] = sect_df["Cur. Value"] / total_val * 100
        sect_colors = [SECTOR_PALETTE.get(s, ACC) for s in sect_df["Sector"]]

        fig_donut = go.Figure(go.Pie(
            labels=sect_df["Sector"].tolist(),
            values=sect_df["Cur. Value"].tolist(),
            hole=0.6,
            marker=dict(colors=sect_colors, line=dict(color=CARD, width=2)),
            textinfo="none",
            hovertemplate="<b>%{label}</b><br>%{percent}<extra></extra>",
        ))
        fig_donut.add_annotation(
            text=f"<b>{len(sect_df)}</b><br>Sectors",
            x=0.5, y=0.5, showarrow=False,
            font=dict(size=16, color=T1, family=FONT), align="center",
        )
        fig_donut.update_layout(
            paper_bgcolor=CARD, showlegend=False,
            font=dict(color=T2, family=FONT),
            height=200, margin=dict(t=0, b=0, l=0, r=0),
            hoverlabel=dict(
                bgcolor="#09090b",
                bordercolor=BORDER,
                font=dict(family="Aptos Display, Segoe UI, sans-serif", color=T1, size=12),
            ),
        )
        if "last_sector_click" not in st.session_state:
            st.session_state.last_sector_click = None
        donut_clicks = plotly_events(
            fig_donut, click_event=True, select_event=False,
            override_height=200, key="donut_pie",
        )
        if donut_clicks:
            pt = donut_clicks[0]
            # pie charts return pointNumber; map it back to label
            idx = pt.get("pointNumber", pt.get("pointIndex", None))
            sect_label = sect_df.iloc[idx]["Sector"] if idx is not None and idx < len(sect_df) else ""
            if sect_label and sect_label != st.session_state.last_sector_click:
                st.session_state.last_sector_click = sect_label
                sub = (
                    df_open[df_open["Sector"] == sect_label]
                    [["Company", "Cur. Value", "Weight %", "P&L %"]].copy()
                    .sort_values("Cur. Value", ascending=False)
                    .reset_index(drop=True)
                )
                sub["_val_str"] = sub["Cur. Value"].apply(inr)
                if not sub.empty:
                    _sector_popup(sect_label, sub.to_dict("records"))
            elif sect_label == st.session_state.last_sector_click:
                st.session_state.last_sector_click = None

        # Sector legend bars
        for _, row in sect_df.iterrows():
            pct   = row["Weight %"]
            bar_w = int(pct / sect_df["Weight %"].max() * 100)
            col   = SECTOR_PALETTE.get(row["Sector"], ACC)
            st.markdown(
                f"<div style='display:flex;align-items:center;margin:5px 0;font-size:12px;"
                f"font-family:{FONT};'>"
                f"<span style='color:{T1};min-width:148px;'>{row['Sector']}</span>"
                f"<div style='flex:1;margin:0 10px;background:{BORDER};border-radius:3px;height:5px;'>"
                f"<div style='width:{bar_w}%;background:{col};height:5px;border-radius:3px;'></div></div>"
                f"<span style='color:{T3};font-weight:700;min-width:38px;text-align:right;'>"
                f"{pct:.1f}%</span></div>",
                unsafe_allow_html=True,
            )

        st.markdown(
            f"<div style='font-size:10px;color:{T3};letter-spacing:1px;margin:8px 0 2px 0;"
            f"font-family:{FONT};'>CLICK A SLICE TO SEE BREAKDOWN</div>",
            unsafe_allow_html=True,
        )

    st.markdown("<br>", unsafe_allow_html=True)

    # Concentration strip
    top1_row = df_open.nlargest(1, "Cur. Value").iloc[0]
    top3_w   = df_open.nlargest(3, "Cur. Value")["Weight %"].sum()
    top_sect = sect_df.iloc[0]
    cn1, cn2, cn3 = st.columns(3)
    cn1.metric("Top Stock",    f"{top1_row['Weight %']:.1f}%", top1_row["Company"])
    cn2.metric("Top 3 Weight", f"{top3_w:.1f}%",              "of portfolio")
    cn3.metric("Top Sector",   f"{top_sect['Weight %']:.1f}%", top_sect["Sector"])


    st.divider()

    # ── Stress Scenarios ───────────────────────────────────────────────────────
    lbl("Stress Scenarios")
    sc1, sc2, sc3, sc4 = st.columns(4)
    for col, (label, drop) in zip(
        [sc1, sc2, sc3, sc4],
        [("Correction  -10%", -10), ("Bear Market  -25%", -25),
         ("Severe Crash  -40%", -40), ("Black Swan  -55%", -55)],
    ):
        stressed = total_val * (1 + drop / 100)
        vs_cost  = (stressed - total_cost) / total_cost * 100
        col.metric(label, inr(stressed), f"{vs_cost:+.1f}% vs cost")

    st.divider()

    # ── XIRR Drill-Down ───────────────────────────────────────────────────────
    lbl("XIRR Drill-Down")
    xirr_options, seen_combined = [], False
    combined_keys = {ABFRL, ABLBL}
    for co in sorted(pos.keys(), key=lambda c: active_display.get(c, c)):
        if co in combined_keys:
            if not seen_combined:
                xirr_options.append("ABFRL + ABLBL (combined)")
                seen_combined = True
        else:
            xirr_options.append(active_display.get(co, co))

    selected = st.selectbox("Select company:", xirr_options)
    lookup   = ABFRL if selected == "ABFRL + ABLBL (combined)" else \
               next((k for k, v in active_display.items() if v == selected), selected)

    xi, cf_rows = get_xirr_cashflows(lookup, txns, pos, prices)

    m1, m2, m3 = st.columns(3)
    m1.metric("XIRR", f"{xi*100:.2f}%" if xi is not None else "—")
    inv_co  = (sum(pos.get(c, {}).get("total_cost", 0) for c in combined_keys)
               if selected == "ABFRL + ABLBL (combined)"
               else pos.get(lookup, {}).get("total_cost", 0))
    cur_co  = cf_rows[-1]["Cash Flow"] if cf_rows else 0
    m2.metric("Invested",      inr(inv_co))
    m3.metric("Current Value", inr(cur_co))

    with st.expander("Transaction History — corporate-action adjusted"):
        cf_df = pd.DataFrame(cf_rows)
        cf_df["Cash Flow"] = cf_df["Cash Flow"].apply(inr)
        cf_df["Date"]      = cf_df["Date"].astype(str)
        st.dataframe(cf_df[["Date", "Event", "Qty", "Cash Flow"]], use_container_width=True, hide_index=True)

    st.divider()

    # ── Watchlist Intelligence ─────────────────────────────────────────────────
    lbl("Research Pipeline  Watchlist")
    watchlist = load_watchlist()
    if not watchlist:
        st.info("No entries in Watchlist yet.")
    else:
        df_wl = pd.DataFrame(watchlist)

        # Status pipeline counts
        status_counts = df_wl["Status"].value_counts()
        if len(status_counts):
            wl_cols = st.columns(min(len(status_counts), 5))
            for col, (status, count) in zip(wl_cols, status_counts.items()):
                if status:
                    col.metric(status, str(count))

        st.markdown("<br>", unsafe_allow_html=True)

        f1, f2, f3 = st.columns(3)
        statuses    = sorted(s for s in df_wl["Status"].unique() if s)
        sel_status  = f1.multiselect("Status",  statuses,  default=statuses)
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

        show_wl = ["Company", "Analyst", "Sector", "CMP (Rs)", "52W High (Rs)", "52W Low (Rs)",
                   "P/E", "Last Disc. Date", "Last Disc. Price (Rs)", "Chg since LDP %",
                   "Status", "Notes"]

        def _chg_color(val):
            if isinstance(val, str):
                if val.startswith("+"): return f"color:{POS};font-weight:600"
                if val.startswith("-"): return f"color:{NEG};font-weight:600"
            return ""

        st.dataframe(
            df_show[show_wl].style.map(_chg_color, subset=["Chg since LDP %"]),
            use_container_width=True, hide_index=True,
        )
        st.caption(f"{len(df_show)} of {len(df_wl)} companies shown")

    st.markdown("<br>", unsafe_allow_html=True)
    st.caption(
        f"As of {datetime.now().strftime('%d %b %Y, %I:%M %p')}  |  "
        "Prices: NSE live via yfinance (15-min delay), fallback where unavailable  |  "
        "ABFRL XIRR = ABFRL + ABLBL combined  |  "
        "Sectors: TheWrap Market Map"
    )


if __name__ == "__main__":
    main()
