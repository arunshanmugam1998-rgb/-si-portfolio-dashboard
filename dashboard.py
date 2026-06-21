"""
Speciale Incept — Listed Portfolio Dashboard
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

# ── Config ────────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Speciale Incept — Listed Portfolio",
    layout="wide",
    initial_sidebar_state="collapsed",
)

SPREADSHEET_ID = "14zSRp_Q8bOU6w9Z3gz6csV9FFNTC37jitur7I_Egeqg"
SCOPES         = ["https://www.googleapis.com/auth/spreadsheets"]

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

ABFRL_DEMERGE_DATE = date(2025, 5, 22)
ABFRL              = "Aditya Birla Fashion and Retail Ltd"
ABLBL              = "Aditya Birla Lifestyle Brands Ltd"

# ── Data loading ──────────────────────────────────────────────────────────────
def _parse_date(val):
    """Parse All Trades date: text 'dd/mm/yyyy' or Excel serial number."""
    if isinstance(val, (int, float)):
        return date(1899, 12, 30) + timedelta(days=int(val))
    try:
        return datetime.strptime(str(val).strip(), "%d/%m/%Y").date()
    except ValueError:
        return None


@st.cache_data(ttl=3600)
def load_raw_transactions():
    """Read All Trades from Google Sheets. Cached for 1 hour."""
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
            "date":         d,
            "company":      name,
            "qty":          qty,
            "price":        price,
            "value":        value,
            "type":         txn.upper(),   # "BUY" or "SELL"
            "product_type": prod,          # "Cash", "Bonus", "Demerger"
            "note":         "",
        })
    return result


def apply_corporate_actions(raw):
    """
    Adjustments applied on top of raw All Trades rows:

    Bonus (Nykaa 5:1, Newgen 1:1):
      All Trades already contains a ₹0 Buy row for bonus shares.
      Pass through as-is — the ₹0 row naturally dilutes avg cost.

    ABFRL / ABLBL demerger (22-May-2025):
      All Trades has an ABLBL Demerger Buy row at ₹0 — skip it.
      Instead: split ABFRL pre-demerger buy cost 50:50.
        ABFRL lot → price ÷2, value ÷2  (orig_value kept for XIRR)
        Synthetic ABLBL lot → same qty/date, 50% of original cost.
    """
    adjusted   = []
    abfrl_lots = []

    for t in raw:
        t = dict(t)
        co, d, ttype, prod = t["company"], t["date"], t["type"], t["product_type"]

        # Skip the ₹0 ABLBL demerger row — ABLBL cost derived from ABFRL below
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

    # Synthetic ABLBL lots (same qty/date as adjusted ABFRL lots, at 50% of original cost)
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
    """Weighted-average cost positions from adjusted transactions."""
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


# ── Live prices ───────────────────────────────────────────────────────────────
@st.cache_data(ttl=900)
def fetch_prices(companies: tuple):
    prices, sources = {}, {}
    for co in companies:
        ticker = TICKERS.get(co)
        if ticker:
            try:
                px_val = yf.Ticker(ticker).fast_info.last_price
                if px_val and px_val > 0:
                    prices[co]  = round(float(px_val), 2)
                    sources[co] = "NSE live"
                    continue
            except Exception:
                pass
        if co in FALLBACK:
            prices[co]  = FALLBACK[co]
            sources[co] = "manual fallback"
    return prices, sources


# ── XIRR ─────────────────────────────────────────────────────────────────────
def _xirr(cashflows):
    """cashflows: list of (date, amount). Negative = outflow."""
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
    """
    Returns (xirr_value, cashflow_rows) for a single company.
    ABFRL and ABLBL are always combined into one XIRR.
    """
    combined = {ABFRL, ABLBL}
    group    = combined if co in combined else {co}
    cfs, rows = [], []

    for t in txns:
        if t["company"] not in group:
            continue
        # Skip synthetic ABLBL DEMERGER rows — cost captured via ABFRL orig_value
        if t["product_type"] == "DEMERGER":
            continue
        if t["type"] == "BUY":
            # For ABFRL pre-demerger, use orig_value (full original cost, not split 50:50)
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
    """
    ABFRL + ABLBL combined as one investment.
    All others computed individually.
    """
    combined = {ABFRL, ABLBL}
    xirr_map = {}

    # ABFRL + ABLBL combined
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

    # Standalone companies
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


# ── Formatting ────────────────────────────────────────────────────────────────
def inr(val):
    sign = "-" if val < 0 else ""
    v = abs(val)
    if v >= 1e7: return f"{sign}₹{v/1e7:.2f} Cr"
    if v >= 1e5: return f"{sign}₹{v/1e5:.2f} L"
    return f"{sign}₹{v:,.0f}"


# ── App ───────────────────────────────────────────────────────────────────────
def main():
    st.title("Speciale Incept — Listed Portfolio")

    # ── Action buttons ─────────────────────────────────────────────────────
    _bc1, _gap = st.columns([1, 7])
    if _bc1.button("Refresh Data"):
        st.cache_data.clear()
        st.rerun()

    raw   = load_raw_transactions()
    txns  = apply_corporate_actions(raw)
    pos   = build_positions(txns)

    with st.spinner("Fetching live prices from NSE…"):
        prices, sources = fetch_prices(tuple(pos.keys()))

    xirr_map = compute_xirr_all(txns, pos, prices)

    # ── Build display dataframe ───────────────────────────────────────────────
    rows_open, rows_closed = [], []
    for co, p in pos.items():
        qty      = p["qty"]
        cost     = p["total_cost"]
        price    = prices.get(co, 0)
        cur_val  = qty * price
        sell_val = sum(s["proceeds"] for s in p["sells"])
        pnl      = (cur_val + sell_val) - (cost + sell_val - sell_val)   # simplify: cur_val - cost
        pnl      = cur_val - cost
        pnl_pct  = (pnl / cost * 100) if cost > 0 else 0
        avg_cost = (cost / qty) if qty > 0 else 0
        days     = (date.today() - p["first_buy"]).days if p["first_buy"] else 0
        xi       = xirr_map.get(co)
        row = {
            "Company":       DISPLAY.get(co, co),
            "_key":          co,
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
            # Closed position: show realized P&L
            tot_cost_paid = sum(
                t["value"] for t in txns
                if t["company"] == co and t["type"] == "BUY"
            )
            sell_txns = [t for t in txns if t["company"] == co and t["type"] == "SELL"]
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

    total_cost = df_open["Total Cost"].sum()
    total_val  = df_open["Cur. Value"].sum()
    total_pnl  = df_open["P&L (₹)"].sum()
    total_pnl_pct = total_pnl / total_cost * 100 if total_cost else 0

    # Portfolio-level XIRR (open + realised)
    port_cfs = []
    for t in txns:
        if t["product_type"] == "DEMERGER":
            continue
        if t["type"] == "BUY":
            val = t.get("orig_value", t["value"])
            port_cfs.append((t["date"], -val))
        elif t["type"] == "SELL":
            port_cfs.append((t["date"], t["value"]))
    port_cfs.append((date.today(), total_val))
    port_xirr = _xirr(port_cfs)

    # ── KPI cards ─────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Total Invested",  inr(total_cost))
    k2.metric("Current Value",   inr(total_val))
    k3.metric("Total P&L",       inr(total_pnl), f"{total_pnl_pct:+.1f}%")
    k4.metric("Portfolio XIRR",  f"{port_xirr*100:.1f}%" if port_xirr else "—")
    k5.metric("Open Positions",  f"{len(df_open)}")

    st.divider()

    # ── Charts ────────────────────────────────────────────────────────────────
    col_l, col_r = st.columns(2)

    with col_l:
        st.subheader("Allocation — Current Value")
        fig_pie = px.pie(
            df_open, values="Cur. Value", names="Company",
            hole=0.42,
            color_discrete_sequence=px.colors.qualitative.Pastel,
        )
        fig_pie.update_traces(textposition="auto", textinfo="percent+label", textfont_size=12)
        fig_pie.update_layout(showlegend=False, margin=dict(t=20, b=20, l=40, r=40), height=420)
        st.plotly_chart(fig_pie, use_container_width=True)

    with col_r:
        st.subheader("P&L % by Company")
        bar_df  = df_open.sort_values("P&L %")
        colors  = ["#d62728" if v < 0 else "#1f77b4" for v in bar_df["P&L %"]]
        fig_bar = go.Figure(go.Bar(
            x=bar_df["P&L %"], y=bar_df["Company"],
            orientation="h",
            marker_color=colors,
            text=[f"{v:+.1f}%" for v in bar_df["P&L %"]],
            textposition="outside",
            cliponaxis=False,
        ))
        fig_bar.update_layout(
            xaxis=dict(title="P&L %", automargin=True),
            yaxis=dict(automargin=True),
            margin=dict(t=10, b=10, l=10, r=110),
            height=420,
        )
        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()

    # ── Open positions table ──────────────────────────────────────────────────
    st.subheader("Open Positions")
    disp_cols = ["Company", "Qty", "Avg Cost (₹)", "Total Cost",
                 "Price (₹)", "Cur. Value", "P&L (₹)", "P&L %",
                 "Days Held", "XIRR %", "Price Source"]

    styled = (
        df_open[disp_cols].style
        .format({
            "Avg Cost (₹)": "₹{:,.2f}",
            "Price (₹)":    "₹{:,.2f}",
            "Total Cost":   lambda x: inr(x),
            "Cur. Value":   lambda x: inr(x),
            "P&L (₹)":      lambda x: inr(x),
            "P&L %":        "{:+.2f}%",
            "XIRR %":       lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
        })
        .map(
            lambda v: "color:#d62728;font-weight:bold" if isinstance(v, (int, float)) and v < 0
                 else "color:#1f77b4;font-weight:bold" if isinstance(v, (int, float)) and v > 0
                 else "",
            subset=["P&L (₹)", "P&L %", "XIRR %"],
        )
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ── Closed positions table ────────────────────────────────────────────────
    if not df_closed.empty:
        st.subheader("Closed Positions")
        closed_cols = ["Company", "Qty", "Avg Cost (₹)", "Total Cost",
                       "Price (₹)", "Cur. Value", "P&L (₹)", "P&L %",
                       "Days Held", "XIRR %"]
        st.dataframe(
            df_closed[closed_cols].style
            .format({
                "Avg Cost (₹)": "₹{:,.2f}",
                "Price (₹)":    "₹{:,.2f}",
                "Total Cost":   lambda x: inr(x),
                "Cur. Value":   lambda x: inr(x),
                "P&L (₹)":      lambda x: inr(x),
                "P&L %":        "{:+.2f}%",
                "XIRR %":       lambda x: f"{x:.1f}%" if pd.notna(x) else "—",
            })
            .map(
                lambda v: "color:#d62728;font-weight:bold" if isinstance(v, (int, float)) and v < 0
                     else "color:#1f77b4;font-weight:bold" if isinstance(v, (int, float)) and v > 0
                     else "",
                subset=["P&L (₹)", "P&L %", "XIRR %"],
            ),
            use_container_width=True, hide_index=True,
        )

    st.divider()

    # ── XIRR drill-down ───────────────────────────────────────────────────────
    st.subheader("XIRR Drill-Down")

    xirr_options  = []
    seen_combined = False
    combined_keys = {ABFRL, ABLBL}
    for co in sorted(pos.keys(), key=lambda c: DISPLAY.get(c, c)):
        if co in combined_keys:
            if not seen_combined:
                xirr_options.append("ABFRL + ABLBL (combined)")
                seen_combined = True
        else:
            xirr_options.append(DISPLAY.get(co, co))

    selected = st.selectbox("Select a company to see its XIRR cash flows:", xirr_options)

    # Resolve display name back to All Trades key
    if selected == "ABFRL + ABLBL (combined)":
        lookup = ABFRL
    else:
        lookup = next((k for k, v in DISPLAY.items() if v == selected), selected)

    xi, cf_rows = get_xirr_cashflows(lookup, txns, pos, prices)

    m1, m2, m3 = st.columns(3)
    m1.metric("XIRR", f"{xi*100:.2f}%" if xi is not None else "—")

    if selected == "ABFRL + ABLBL (combined)":
        total_inv = sum(pos.get(c, {}).get("total_cost", 0) for c in combined_keys)
    else:
        total_inv = pos.get(lookup, {}).get("total_cost", 0)
    cur_val_co = cf_rows[-1]["Cash Flow"] if cf_rows else 0
    m2.metric("Total Invested", inr(total_inv))
    m3.metric("Current Value",  inr(cur_val_co))

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
        connector={"line": {"color": "rgb(63,63,63)"}},
        increasing={"marker": {"color": "#1f77b4"}},
        decreasing={"marker": {"color": "#d62728"}},
        totals={"marker":    {"color": "#2ca02c"}},
    ))
    fig_wf.update_layout(
        title=f"Cash Flow Timeline — {selected}",
        yaxis=dict(title="₹", automargin=True),
        margin=dict(t=60, b=40, l=60, r=60),
        height=430,
    )
    st.plotly_chart(fig_wf, use_container_width=True)

    # ── Transaction history ───────────────────────────────────────────────────
    with st.expander("Transaction History (corporate-action adjusted)"):
        hist = pd.DataFrame([{
            "Date":       t["date"],
            "Company":    DISPLAY.get(t["company"], t["company"]),
            "Type":       t["type"],
            "Product":    t["product_type"],
            "Qty":        int(round(t["qty"])),
            "Adj Price":  f"₹{t['price']:,.2f}",
            "Value":      inr(t["value"]),
            "Note":       t.get("note", ""),
        } for t in txns]).sort_values("Date", ascending=False)
        st.dataframe(hist, use_container_width=True, hide_index=True)

    st.caption(
        f"Refreshed: {datetime.now().strftime('%d %b %Y %I:%M %p')}  |  "
        "Data: Google Sheets — All Trades  |  "
        "Prices: NSE live via yfinance (15-min delay), manual fallback where unavailable  |  "
        "ABFRL XIRR = ABFRL + ABLBL combined  |  "
        "Cost basis: Qty × Price, no charges"
    )


if __name__ == "__main__":
    main()
