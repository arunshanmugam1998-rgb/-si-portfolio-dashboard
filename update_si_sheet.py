"""
Speciale Incept — Listed Portfolio updater.

SI_Portfolio formulas reference All Trades directly.
Re-run Python only when: new company added, new demerger, or first-time setup.
Day-to-day Buy / Sell / Bonus / IPO Allotment entries in All Trades auto-update SI_Portfolio.
"""
import sys
sys.stdout.reconfigure(encoding='utf-8')

import difflib
import json
import os
import re
import requests
import time
import yfinance as yf
from datetime import date, datetime
from collections import defaultdict
import gspread
from google.oauth2.service_account import Credentials

# ── Auth ──────────────────────────────────────────────────────────────────────
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
creds  = Credentials.from_service_account_file("service_account.json", scopes=SCOPES)
gc     = gspread.authorize(creds)
sh     = gc.open_by_key("14zSRp_Q8bOU6w9Z3gz6csV9FFNTC37jitur7I_Egeqg")

# ── Column format persistence ─────────────────────────────────────────────────
# Stores column widths and hidden state for SI_Portfolio.
# Populate by running:  python update_si_sheet.py --save-format
FORMAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "si_portfolio_format.json")
# Watchlist column format — run:  python update_si_sheet.py --save-watchlist-format
WATCHLIST_FORMAT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                     "watchlist_format.json")

# ── All Trades column references ──────────────────────────────────────────────
# Sheet layout: A=Financial Year  B=Trade Date(text)  E=Security Name
#               I=Transaction Type(Buy/Sell)  K=Quantity  M=Total  S=Date Serial
AT        = "'All Trades'"
AT_NAME   = f"{AT}!E:E"
AT_TXN    = f"{AT}!I:I"
AT_QTY    = f"{AT}!K:K"
AT_VAL    = f"{AT}!M:M"
AT_DSER   = f"{AT}!S:S"

AT_NAME_R = f"{AT}!E2:E10000"
AT_TXN_R  = f"{AT}!I2:I10000"
AT_VAL_R  = f"{AT}!M2:M10000"
AT_DSER_R = f"{AT}!S2:S10000"

# ── Portfolio config ──────────────────────────────────────────────────────────
COMPANIES = [
    "Aditya Birla Fashion and Retail Ltd",
    "Aditya Birla Lifestyle Brands Ltd",
    "FSN E-Commerce Ventures Ltd",
    "Federal Bank Ltd",
    "Newgen Software Technologies Ltd",
    "Indegene Ltd",
    "EID Parry (India) Ltd",
    "Gujarat Fluorochemicals Ltd",
    "Greenlam Industries Ltd",
    "Sundaram Clayton Ltd",
    "Aether Industries Ltd",
    "HDFC Bank Ltd",
    "Sansera Engineering Ltd",
]

TICKERS = {
    "Aditya Birla Fashion and Retail Ltd": "ABFRL",
    "Aditya Birla Lifestyle Brands Ltd":   "ABLBL",
    "FSN E-Commerce Ventures Ltd":         "NYKAA",
    "Federal Bank Ltd":                    "FEDERALBNK",
    "Newgen Software Technologies Ltd":    "NEWGEN",
    "Indegene Ltd":                        "INDGN",
    "EID Parry (India) Ltd":               "EIDPARRY",
    "Gujarat Fluorochemicals Ltd":         "FLUOROCHEM",
    "Greenlam Industries Ltd":             "GREENLAM",
    "Sundaram Clayton Ltd":                "SUNCLAY",
    "Aether Industries Ltd":               "AETHER",
    "HDFC Bank Ltd":                       "HDFCBANK",
    "Sansera Engineering Ltd":             "SANSERA",
}

# ── Demerger config ───────────────────────────────────────────────────────────
# HOW TO HANDLE A FUTURE DEMERGER (repeatable playbook):
#
#  Step 1 — In All Trades:
#    Add one row for the demerged company:
#      Security Name    = exact new company name (must match COMPANIES below)
#      Transaction Type = Buy   |   Product Type = Demerger
#      Quantity         = shares received   |   Market Rate = 0   |   Total = 0
#    (Formulas derive real qty/cost from the parent rows. The zero-price row
#     is a record only — it does NOT affect any calculations.)
#
#  Step 2 — In this file:
#    a. Add the new company to COMPANIES and TICKERS above.
#    b. Add a block to DEMERGER_CONFIG:
#         key          = new company name (must match All Trades exactly)
#         "parent"     = parent company name (must match All Trades exactly)
#         "date"       = date(YYYY, M, D)  ← day shares were received
#         "cost_ratio" = fraction of parent's pre-demerger cost allocated here
#         "pre_date"   = True  (use parent buys BEFORE the demerger date)
#
#  Step 3 — Re-run this script once. All future transactions auto-update after that.

DEMERGER_CONFIG = {
    # ABLBL received via 1:1 demerger from ABFRL on 22-May-2025.
    # Cost allocated: 50% of pre-demerger ABFRL buy cost.
    "Aditya Birla Lifestyle Brands Ltd": {
        "parent":     "Aditya Birla Fashion and Retail Ltd",
        "date":       date(2025, 5, 22),
        "cost_ratio": 0.5,
        "pre_date":   True,
    },
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def get_or_create(name):
    try:
        ws = sh.worksheet(name)
        ws.clear()
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=name, rows=300, cols=20)
    return ws


# ── Fix All Trades: text numbers → numeric ────────────────────────────────────
def fix_at_numbers():
    """
    Converts Qty (col K) and Total (col M) from text to numbers in All Trades.
    Zerodha CSV exports paste these as text strings; SUMIFS ignores text and returns 0.
    Safe to re-run — only updates cells where the value is still a text string.
    """
    ws     = sh.worksheet("All Trades")
    k_data = ws.get("K2:K10000", value_render_option="UNFORMATTED_VALUE")
    m_data = ws.get("M2:M10000", value_render_option="UNFORMATTED_VALUE")

    updates = []
    k_count = m_count = 0

    for i, row in enumerate(k_data, start=2):
        val = row[0] if row else ''
        if isinstance(val, str) and val.strip():
            try:
                updates.append({'range': f'K{i}', 'values': [[float(val.replace(',', ''))]]})
                k_count += 1
            except ValueError:
                pass

    for i, row in enumerate(m_data, start=2):
        val = row[0] if row else ''
        if isinstance(val, str) and val.strip():
            try:
                updates.append({'range': f'M{i}', 'values': [[float(val.replace(',', ''))]]})
                m_count += 1
            except ValueError:
                pass

    if updates:
        ws.batch_update(updates, value_input_option='RAW')
    print(f"All Trades: converted {k_count} Qty and {m_count} Total values from text to numbers")


# ── Setup date serial column in All Trades ────────────────────────────────────
def setup_all_trades_helper():
    """
    Adds/updates column S ('Date Serial') in All Trades.
    DATEVALUE cannot parse dd/mm/yyyy; uses DATE(VALUE(MID),VALUE(MID),VALUE(LEFT)) instead.
    Always rewrites S2 — safe to re-run (fixes broken formula from prior runs).
    """
    ws  = sh.worksheet("All Trades")
    hdr = ws.row_values(1)
    if "Date Serial" not in hdr:
        ws.update(range_name="S1", values=[["Date Serial"]], value_input_option="RAW")
        ws.format("S1", {"textFormat": {"bold": True}})
    # dd/mm/yyyy: LEFT(B,2)=day · MID(B,4,2)=month · MID(B,7,4)=year
    formula = ('=ARRAYFORMULA(IF(B2:B="","",'
               'DATE(VALUE(MID(B2:B,7,4)),VALUE(MID(B2:B,4,2)),VALUE(LEFT(B2:B,2)))))')
    ws.update(range_name="S2", values=[[formula]], value_input_option="USER_ENTERED")
    print("All Trades: Date Serial formula written at column S")


# ── Determine Open / Closed status per company ───────────────────────────────
def get_company_statuses():
    """
    Reads All Trades to classify each company as 'Open' or 'Closed'.
    Closed  = net qty held rounds to 0 (all shares sold).
    Open    = still holds shares (net qty > 0).
    Demerger children: net = parent pre-demerger buy qty − child direct sell qty.
    Standard companies: net = total buy qty − total sell qty.
    Prints a status line per company so you can see exactly what was detected.
    """
    ws   = sh.worksheet("All Trades")
    rows = ws.get("A1:K10000", value_render_option="UNFORMATTED_VALUE")

    def to_qty(v):
        try:
            return float(v) if isinstance(v, (int, float)) else \
                   float(str(v).replace(',', '').strip() or 0)
        except (ValueError, TypeError):
            return 0.0

    def parse_dt(s):
        try:
            return datetime.strptime(str(s).strip(), "%d/%m/%Y").date()
        except (ValueError, TypeError):
            return None

    buy_qty        = defaultdict(float)
    sell_qty       = defaultdict(float)
    parent_pre_buy = defaultdict(float)

    parent_dem_date = {cfg["parent"]: cfg["date"] for cfg in DEMERGER_CONFIG.values()}

    for row in rows[1:]:
        name  = (row[4].strip()  if isinstance(row[4], str)  else str(row[4])) if len(row) > 4  else ''
        txn   = (row[8].strip()  if isinstance(row[8], str)  else str(row[8])) if len(row) > 8  else ''
        qty   = to_qty(row[10]   if len(row) > 10 else 0)
        date_s = (row[1].strip() if isinstance(row[1], str) else str(row[1]))   if len(row) > 1  else ''

        if not name or not txn or qty == 0:
            continue

        if txn.lower() == "sell":
            sell_qty[name] += qty
        else:
            buy_qty[name] += qty
            if name in parent_dem_date:
                d = parse_dt(date_s)
                if d and d < parent_dem_date[name]:
                    parent_pre_buy[name] += qty

    # Auto-extend COMPANIES with any new names found in All Trades (preserves order, appends new)
    all_traded = sorted(set(buy_qty.keys()) | set(sell_qty.keys()))
    for name in all_traded:
        if name and name not in COMPANIES:
            COMPANIES.append(name)
            ticker_hint = " — add NSE ticker to TICKERS dict for live prices" if name not in TICKERS else ""
            print(f"  Auto-discovered new company: {name!r}{ticker_hint}")

    print("  Open/Closed status per company:")
    statuses = {}
    for co in COMPANIES:
        if co in DEMERGER_CONFIG:
            parent = DEMERGER_CONFIG[co]["parent"]
            net    = parent_pre_buy[parent] - sell_qty[co]
        else:
            net = buy_qty[co] - sell_qty[co]
        if net < 0.5:
            status = "Closed"
        elif sell_qty[co] > 0:
            status = "Partial"
        else:
            status = "Open"
        statuses[co] = status
        print(f"    {co}: bought={buy_qty[co]:.0f}  sold={sell_qty[co]:.0f}  net={net:.0f}  → {status}")

    return statuses


# ── Write SI_Portfolio ────────────────────────────────────────────────────────
def write_portfolio():
    """
    Writes SI_Portfolio with two sections: Open Positions and Closed Positions.
    Status is determined from All Trades net qty (Open = still holds shares).
    Column layout (A–M, 13 cols):
      A = Company           B = NSE Ticker
      C = Qty               D = Total Cost (Rs.)      E = Avg Cost/Share (Rs.)
      F = Current Price     G = Current Value (Rs.)   [Closed: Sale Price / Sale Value]
      H = P&L (Rs.)         I = P&L %
      J = First Buy Date    K = Days Held             L = XIRR %    M = CAGR %
    CAGR = ((Current Value + Sell Proceeds) / Total Cost) ^ (365 / Days Held) − 1
    """
    ws = get_or_create("SI_Portfolio")

    statuses   = get_company_statuses()
    open_cos   = [co for co in COMPANIES if statuses.get(co, "Open") in ("Open", "Partial")]
    closed_cos = [co for co in COMPANIES if statuses.get(co, "Open") in ("Closed", "Partial")]
    n_open     = len(open_cos)
    n_closed   = len(closed_cos)

    # ── Compute row numbers ───────────────────────────────────────────────────
    next_row = 3

    OPEN_SEC = OPEN_HDR = OPEN_D0 = OPEN_D1 = OPEN_TOTAL = None
    if open_cos:
        OPEN_SEC   = next_row; next_row += 1
        OPEN_HDR   = next_row; next_row += 1
        OPEN_D0    = next_row; next_row += n_open
        OPEN_D1    = next_row - 1
        OPEN_TOTAL = next_row; next_row += 1
        if closed_cos:
            next_row += 1   # blank separator

    CLOSED_SEC = CLOSED_HDR = CLOSED_D0 = CLOSED_D1 = CLOSED_TOTAL = None
    if closed_cos:
        CLOSED_SEC   = next_row; next_row += 1
        CLOSED_HDR   = next_row; next_row += 1
        CLOSED_D0    = next_row; next_row += n_closed
        CLOSED_D1    = next_row - 1
        CLOSED_TOTAL = next_row; next_row += 1

    LAST_ROW = next_row - 1

    # ── Row formula factories ─────────────────────────────────────────────────

    def _standard_row(co, r, ticker):
        bq_v      = f'SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        bval_v    = f'SUMIFS({AT_VAL},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        qty_f     = f'=IFERROR({bq_v}-SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"Sell"),0)'
        avg_f     = f'=IFERROR({bval_v}/{bq_v},"\u2014")'
        cost_f    = f'=IFERROR(C{r}*E{r},0)'
        price_f   = f'=IFERROR(GOOGLEFINANCE("NSE:"&B{r},"price"),"\u2014 add manually")'
        curval_f  = f'=IFERROR(IF(ISNUMBER(F{r}),C{r}*F{r},"\u2014"),"\u2014")'
        pnl_f     = f'=IFERROR(G{r}-D{r},"\u2014")'
        pnl_pct_f = f'=IFERROR(TEXT(H{r}/D{r}*100,"0.00")&"%","\u2014")'
        first_f   = f'=IFERROR(TEXT(MINIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"<>Sell"),"dd-mmm-yyyy"),"\u2014")'
        days_f    = f'=IFERROR(TODAY()-MINIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"<>Sell"),"\u2014")'
        sign_v    = f'IF({AT_TXN_R}<>"Sell",-1,1)*{AT_VAL_R}'
        xirr_f    = (f'=IFERROR(TEXT(XIRR('
                     f'VSTACK(FILTER({sign_v},{AT_NAME_R}=A{r}),G{r}),'
                     f'VSTACK(FILTER({AT_DSER_R},{AT_NAME_R}=A{r}),TODAY())'
                     f')*100,"0.00")&"%","\u2014")')
        return [co, ticker, qty_f, cost_f, avg_f, price_f, curval_f,
                pnl_f, pnl_pct_f, first_f, days_f, xirr_f]

    def _demerger_child_row(co, r, ticker):
        cfg    = DEMERGER_CONFIG[co]
        parent = cfg["parent"]
        d      = cfg["date"]
        cr     = cfg["cost_ratio"]
        dgs    = f'DATE({d.year},{d.month},{d.day})'
        dcmp   = f'"<"&{dgs}' if cfg["pre_date"] else f'">="&{dgs}'

        par_bq    = f'SUMIFS({AT_QTY},{AT_NAME},"{parent}",{AT_TXN},"<>Sell",{AT_DSER},{dcmp})'
        par_bval  = f'SUMIFS({AT_VAL},{AT_NAME},"{parent}",{AT_TXN},"<>Sell",{AT_DSER},{dcmp})'
        qty_f     = f'=IFERROR({par_bq}-SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"Sell"),0)'
        avg_f     = f'=IFERROR({par_bval}*{cr}/{par_bq},"\u2014")'
        cost_f    = f'=IFERROR(C{r}*E{r},0)'
        price_f   = f'=IFERROR(GOOGLEFINANCE("NSE:"&B{r},"price"),"\u2014 add manually")'
        curval_f  = f'=IFERROR(IF(ISNUMBER(F{r}),C{r}*F{r},"\u2014"),"\u2014")'
        pnl_f     = f'=IFERROR(G{r}-D{r},"\u2014")'
        pnl_pct_f = f'=IFERROR(TEXT(H{r}/D{r}*100,"0.00")&"%","\u2014")'
        first_f   = f'=TEXT({dgs},"dd-mmm-yyyy")'
        days_f    = f'=TODAY()-{dgs}'
        # XIRR: ABFRL pre-demerger buy cost × cost_ratio at original ABFRL buy dates.
        # Terminal = G{r} (ABLBL qty × live price).
        # Pattern mirrors _demerger_parent_row: date logic inside IF (not inside FILTER),
        # FILTER only on company name + transaction type — avoids S-column comparison issues.
        cash_f    = f'IF({AT}!S2:S10000<{dgs},-ABS({AT}!M2:M10000)*{cr},0)'
        xirr_f    = (f'=IFERROR(TEXT(XIRR('
                     f'VSTACK(FILTER({cash_f},{AT}!E2:E10000="{parent}",{AT}!I2:I10000<>"Sell"),G{r}),'
                     f'VSTACK(FILTER({AT_DSER_R},{AT_NAME_R}="{parent}",{AT_TXN_R}<>"Sell"),TODAY())'
                     f')*100,"0.00")&"%","\u2014")')
        return [co, ticker, qty_f, cost_f, avg_f, price_f, curval_f,
                pnl_f, pnl_pct_f, first_f, days_f, xirr_f]

    def _demerger_parent_row(co, r, ticker, child_cfgs):
        cfg  = next(iter(child_cfgs.values()))
        d    = cfg["date"]
        cr   = cfg["cost_ratio"]
        pr   = round(1 - cr, 10)
        dgs  = f'DATE({d.year},{d.month},{d.day})'

        bq_v      = f'SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        pre_bval  = f'SUMIFS({AT_VAL},{AT_NAME},A{r},{AT_TXN},"<>Sell",{AT_DSER},"<"&{dgs})'
        post_bval = f'SUMIFS({AT_VAL},{AT_NAME},A{r},{AT_TXN},"<>Sell",{AT_DSER},">="&{dgs})'
        qty_f     = f'=IFERROR({bq_v}-SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"Sell"),0)'
        avg_f     = f'=IFERROR(({pre_bval}*{pr}+{post_bval})/{bq_v},"\u2014")'
        cost_f    = f'=IFERROR(C{r}*E{r},0)'
        price_f   = f'=IFERROR(GOOGLEFINANCE("NSE:"&B{r},"price"),"\u2014 add manually")'
        curval_f  = f'=IFERROR(IF(ISNUMBER(F{r}),C{r}*F{r},"\u2014"),"\u2014")'
        pnl_f     = f'=IFERROR(G{r}-D{r},"\u2014")'
        pnl_pct_f = f'=IFERROR(TEXT(H{r}/D{r}*100,"0.00")&"%","\u2014")'
        first_f   = f'=IFERROR(TEXT(MINIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"<>Sell"),"dd-mmm-yyyy"),"\u2014")'
        days_f    = f'=IFERROR(TODAY()-MINIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"<>Sell"),"\u2014")'
        cash_f    = (f'IF({AT}!S2:S10000<{dgs},-{AT}!M2:M10000*{pr},'
                     f'IF({AT}!I2:I10000="Sell",{AT}!M2:M10000,-{AT}!M2:M10000))')
        xirr_f    = (f'=IFERROR(TEXT(XIRR('
                     f'VSTACK(FILTER({cash_f},{AT}!E2:E10000=A{r}),G{r}),'
                     f'VSTACK(FILTER({AT_DSER_R},{AT_NAME_R}=A{r}),TODAY())'
                     f')*100,"0.00")&"%","\u2014")')
        return [co, ticker, qty_f, cost_f, avg_f, price_f, curval_f,
                pnl_f, pnl_pct_f, first_f, days_f, xirr_f]

    def _realized_row(co, r, ticker):
        """Closed section — realized (sold) portion only.
        Qty = sold qty.  Cost = proportional avg cost of sold shares.
        Sale Price = avg realised price.  Sale Value = total proceeds.
        XIRR: buy cash flows are scaled proportionally by sold_qty/total_bought_qty
              so that only the share of capital deployed on the sold lot is counted.
        """
        sq_v   = f'SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"Sell")'
        bq_v   = f'SUMIFS({AT_QTY},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        bval_v = f'SUMIFS({AT_VAL},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        sv_v   = f'SUMIFS({AT_VAL},{AT_NAME},A{r},{AT_TXN},"Sell")'
        last_s = f'MAXIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"Sell")'
        first_b= f'MINIFS({AT_DSER},{AT_NAME},A{r},{AT_TXN},"<>Sell")'
        qty_f     = f'={sq_v}'
        avg_f     = f'=IFERROR({bval_v}/{bq_v},"\u2014")'
        cost_f    = f'=IFERROR(C{r}*E{r},0)'
        price_f   = f'=IFERROR({sv_v}/{sq_v},"\u2014")'
        curval_f  = f'={sv_v}'
        pnl_f     = f'=IFERROR(G{r}-D{r},"\u2014")'
        pnl_pct_f = f'=IFERROR(TEXT(H{r}/D{r}*100,"0.00")&"%","\u2014")'
        first_f   = f'=IFERROR(TEXT({first_b},"dd-mmm-yyyy"),"\u2014")'
        days_f    = f'=IFERROR({last_s}-{first_b},"\u2014")'
        # XIRR: scale each buy cash flow by (sold_qty / total_bought_qty)
        ratio     = f'({sq_v}/{bq_v})'
        scaled_buys = f'FILTER(-{AT_VAL_R}*{ratio},{AT_NAME_R}=A{r},{AT_TXN_R}<>"Sell")'
        sell_flows  = f'FILTER({AT_VAL_R},{AT_NAME_R}=A{r},{AT_TXN_R}="Sell")'
        buy_dates   = f'FILTER({AT_DSER_R},{AT_NAME_R}=A{r},{AT_TXN_R}<>"Sell")'
        sell_dates  = f'FILTER({AT_DSER_R},{AT_NAME_R}=A{r},{AT_TXN_R}="Sell")'
        xirr_f    = (f'=IFERROR(TEXT(XIRR('
                     f'VSTACK({scaled_buys},{sell_flows}),'
                     f'VSTACK({buy_dates},{sell_dates})'
                     f')*100,"0.00")&"%","\u2014")')
        return [co, ticker, qty_f, cost_f, avg_f, price_f, curval_f,
                pnl_f, pnl_pct_f, first_f, days_f, xirr_f]

    def make_row(co, r):
        ticker     = TICKERS.get(co, "")
        if co in DEMERGER_CONFIG:
            return _demerger_child_row(co, r, ticker)
        child_cfgs = {c: cfg for c, cfg in DEMERGER_CONFIG.items() if cfg["parent"] == co}
        if child_cfgs:
            return _demerger_parent_row(co, r, ticker, child_cfgs)
        return _standard_row(co, r, ticker)

    def make_closed_row(co, r):
        return _realized_row(co, r, TICKERS.get(co, ""))

    def subtotal_row(d0, d1, tr):
        # 12 elements (A–L)
        return ["TOTAL", "", "", f'=SUM(D{d0}:D{d1})', "",
                "", f'=SUM(G{d0}:G{d1})', f'=SUM(H{d0}:H{d1})',
                f'=IFERROR(TEXT(H{tr}/D{tr}*100,"0.00")&"%","\u2014")',
                "", "", ""]

    # ── Build row list ────────────────────────────────────────────────────────
    OPEN_HDRS = ["Company", "NSE Ticker", "Qty", "Total Cost (Rs.)", "Avg Cost/Share (Rs.)",
                 "Current Price (Rs.)", "Current Value (Rs.)", "P&L (Rs.)", "P&L %",
                 "First Buy Date", "Days Held", "XIRR %"]
    CLOSED_HDRS = ["Company", "NSE Ticker", "Qty", "Total Cost (Rs.)", "Avg Cost/Share (Rs.)",
                   "Sale Price (Rs.)", "Sale Value (Rs.)", "P&L (Rs.)", "P&L %",
                   "First Buy Date", "Days Held", "XIRR %"]

    title_row = ["SPECIALE INCEPT \u2014 LISTED PORTFOLIO"] + [""] * 11   # 12 cols
    blank_row  = [""] * 12

    all_rows = [title_row, blank_row]

    if open_cos:
        all_rows.append(["OPEN POSITIONS"] + [""] * 11)
        all_rows.append(OPEN_HDRS)
        for i, co in enumerate(open_cos):
            all_rows.append(make_row(co, OPEN_D0 + i))
        all_rows.append(subtotal_row(OPEN_D0, OPEN_D1, OPEN_TOTAL))
        if closed_cos:
            all_rows.append(blank_row)

    if closed_cos:
        all_rows.append(["CLOSED POSITIONS"] + [""] * 11)
        all_rows.append(CLOSED_HDRS)
        for i, co in enumerate(closed_cos):
            all_rows.append(make_closed_row(co, CLOSED_D0 + i))
        all_rows.append(subtotal_row(CLOSED_D0, CLOSED_D1, CLOSED_TOTAL))

    # ── Portfolio XIRR row ────────────────────────────────────────────────────
    # Cash flows: all buys (negative) + all sells (positive) across every company.
    # Terminal value: current market value of all open positions (closed positions
    # have no residual — their proceeds are already captured in sell cash flows).
    PORT_XIRR_ROW = LAST_ROW + 2
    LAST_ROW = PORT_XIRR_ROW

    terminal   = f'SUM(G{OPEN_D0}:G{OPEN_D1})' if OPEN_D0 else '0'
    buy_cf     = f'FILTER(-{AT_VAL_R},{AT_NAME_R}<>"",{AT_TXN_R}<>"Sell")'
    sell_cf    = f'FILTER({AT_VAL_R},{AT_NAME_R}<>"",{AT_TXN_R}="Sell")'
    buy_dt     = f'FILTER({AT_DSER_R},{AT_NAME_R}<>"",{AT_TXN_R}<>"Sell")'
    sell_dt    = f'FILTER({AT_DSER_R},{AT_NAME_R}<>"",{AT_TXN_R}="Sell")'
    port_xirr_f = (
        f'=IFERROR(TEXT(XIRR('
        f'IFERROR(VSTACK({buy_cf},{sell_cf},{terminal}),VSTACK({buy_cf},{terminal})),'
        f'IFERROR(VSTACK({buy_dt},{sell_dt},TODAY()),VSTACK({buy_dt},TODAY()))'
        f')*100,"0.00")&"%","\u2014")'
    )
    all_rows.append(blank_row)
    all_rows.append(["Portfolio XIRR"] + [""] * 10 + [port_xirr_f])

    ws.update(
        range_name=f"A1:L{LAST_ROW}",
        values=all_rows,
        value_input_option="USER_ENTERED",
    )
    ws.freeze(rows=2)
    print(f"SI_Portfolio: {n_open} open, {n_closed} closed companies written (rows 1–{LAST_ROW})")

    return ws, {
        "open_sec":    OPEN_SEC,   "open_hdr":    OPEN_HDR,
        "open_d0":     OPEN_D0,    "open_d1":     OPEN_D1,    "open_total":  OPEN_TOTAL,
        "closed_sec":  CLOSED_SEC, "closed_hdr":  CLOSED_HDR,
        "closed_d0":   CLOSED_D0,  "closed_d1":   CLOSED_D1,  "closed_total": CLOSED_TOTAL,
        "last_row":    LAST_ROW,   "port_xirr_row": PORT_XIRR_ROW,
        "n_open":      n_open,     "n_closed":    n_closed,
    }


# ── IC Formatting: SI_Portfolio ───────────────────────────────────────────────
def format_portfolio_tab(ws, layout):
    open_sec     = layout["open_sec"]
    open_hdr     = layout["open_hdr"]
    open_d0      = layout["open_d0"]
    open_d1      = layout["open_d1"]
    open_total   = layout["open_total"]
    closed_sec   = layout["closed_sec"]
    closed_hdr   = layout["closed_hdr"]
    closed_d0    = layout["closed_d0"]
    closed_d1    = layout["closed_d1"]
    closed_total   = layout["closed_total"]
    port_xirr_row  = layout["port_xirr_row"]
    last_row       = layout["last_row"]

    NAVY     = {"red": 0.122, "green": 0.235, "blue": 0.392}
    SEC_NAVY = {"red": 0.200, "green": 0.333, "blue": 0.490}
    WHITE    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
    PALE     = {"red": 0.933, "green": 0.953, "blue": 0.980}
    TOTAL_BG = {"red": 0.741, "green": 0.855, "blue": 0.941}
    POS_BG   = {"red": 0.902, "green": 0.957, "blue": 0.914}
    NEG_BG   = {"red": 0.992, "green": 0.887, "blue": 0.882}
    POS_TEXT = {"red": 0.118, "green": 0.408, "blue": 0.137}
    NEG_TEXT = {"red": 0.612, "green": 0.0,   "blue": 0.004}
    BDR_MED  = {"red": 0.122, "green": 0.235, "blue": 0.392}
    BDR_IN   = {"red": 0.700, "green": 0.700, "blue": 0.700}

    COL_END = 12   # A–L

    # ── Static formatting ─────────────────────────────────────────────────────
    ws.format("A1:L1", {"backgroundColor": WHITE,
                        "textFormat": {"bold": True, "fontSize": 10},
                        "horizontalAlignment": "LEFT"})
    ws.format("A2:L2", {"backgroundColor": WHITE})

    SEC_FMT = {
        "backgroundColor": SEC_NAVY,
        "textFormat": {"bold": True, "fontSize": 10, "foregroundColor": WHITE},
        "horizontalAlignment": "LEFT", "verticalAlignment": "MIDDLE",
    }
    COL_HDR_FMT = {
        "backgroundColor": NAVY,
        "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE},
        "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
        "wrapStrategy": "WRAP",
    }
    DATA_FMT  = {"backgroundColor": WHITE, "textFormat": {"fontSize": 10}, "wrapStrategy": "WRAP"}
    TOTAL_FMT = {"backgroundColor": TOTAL_BG, "textFormat": {"bold": True, "fontSize": 10}}

    for sec, hdr, d0, d1, total in [
        (open_sec,   open_hdr,   open_d0,   open_d1,   open_total),
        (closed_sec, closed_hdr, closed_d0, closed_d1, closed_total),
    ]:
        if sec is None:
            continue
        ws.format(f"A{sec}:L{sec}",    SEC_FMT)
        ws.format(f"A{hdr}:L{hdr}",    COL_HDR_FMT)
        ws.format(f"A{d0}:L{d1}",      DATA_FMT)
        ws.format(f"A{total}:L{total}", TOTAL_FMT)

    first_data = open_d0 or closed_d0
    if first_data:
        ws.format(f"A{first_data}:B{last_row}", {"horizontalAlignment": "LEFT"})
        ws.format(f"C{first_data}:L{last_row}", {"horizontalAlignment": "RIGHT"})

    for d0, d1, total in [
        (open_d0,   open_d1,   open_total),
        (closed_d0, closed_d1, closed_total),
    ]:
        if d0 is None:
            continue
        ws.format(f"C{d0}:C{total}",
                  {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})
        ws.format(f"D{d0}:H{total}",
                  {"numberFormat": {"type": "NUMBER", "pattern": "#,##0.00"}})
        ws.format(f"K{d0}:K{d1}",
                  {"numberFormat": {"type": "NUMBER", "pattern": "#,##0"}})

    sid = ws.id

    # Fetch metadata once for unmerge + rule deletion
    meta       = sh.fetch_sheet_metadata()
    sheet_meta = next((s for s in meta.get("sheets", [])
                       if s["properties"]["sheetId"] == sid), {})

    merge_rows = {0, 1}
    if open_sec:   merge_rows.add(open_sec   - 1)
    if closed_sec: merge_rows.add(closed_sec - 1)
    title_merges = [m for m in sheet_meta.get("merges", [])
                    if m.get("startRowIndex", 99) in merge_rows]
    if title_merges:
        sh.batch_update({"requests": [
            {"unmergeCells": {"range": {**m, "sheetId": sid}}}
            for m in title_merges
        ]})

    n_rules = len(sheet_meta.get("conditionalFormats", []))
    if n_rules > 0:
        sh.batch_update({"requests": [
            {"deleteConditionalFormatRule": {"index": 0, "sheetId": sid}}
            for _ in range(n_rules)
        ]})

    # ── Batch: merges, borders, conditional formatting ────────────────────────
    def bdr(style, color):
        return {"style": style, "colorStyle": {"rgbColor": color}}

    OUTER = bdr("SOLID_MEDIUM", BDR_MED)
    THIN  = bdr("SOLID",        BDR_IN)
    THICK = bdr("SOLID_MEDIUM", BDR_MED)

    def rng(r0, r1, c0, c1):
        return {"sheetId": sid,
                "startRowIndex": r0 - 1, "endRowIndex": r1,
                "startColumnIndex": c0,  "endColumnIndex": c1}

    def cond_ranges(c0, c1):
        rngs = []
        if open_d0 is not None:
            rngs.append(rng(open_d0, open_d1, c0, c1))
        if closed_d0 is not None:
            rngs.append(rng(closed_d0, closed_d1, c0, c1))
        return rngs

    anchor = open_d0 or closed_d0

    requests = [
        # Clear all formatting in col M (leftover from any prior 13-col run)
        {"repeatCell": {
            "range": {"sheetId": sid, "startColumnIndex": 12, "endColumnIndex": 13},
            "cell": {"userEnteredFormat": {}},
            "fields": "userEnteredFormat",
        }},
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 0, "endRowIndex": 1,
                                  "startColumnIndex": 0, "endColumnIndex": COL_END},
                        "mergeType": "MERGE_ALL"}},
        {"mergeCells": {"range": {"sheetId": sid, "startRowIndex": 1, "endRowIndex": 2,
                                  "startColumnIndex": 0, "endColumnIndex": COL_END},
                        "mergeType": "MERGE_ALL"}},
    ]

    for sec in [open_sec, closed_sec]:
        if sec is not None:
            requests.append({"mergeCells": {
                "range": {"sheetId": sid,
                          "startRowIndex": sec - 1, "endRowIndex": sec,
                          "startColumnIndex": 0, "endColumnIndex": COL_END},
                "mergeType": "MERGE_ALL",
            }})

    for hdr, d0, total in [
        (open_hdr,   open_d0,   open_total),
        (closed_hdr, closed_d0, closed_total),
    ]:
        if hdr is None:
            continue
        requests.append({"updateBorders": {
            "range": {"sheetId": sid,
                      "startRowIndex": hdr - 1, "endRowIndex": total,
                      "startColumnIndex": 0, "endColumnIndex": COL_END},
            "top": OUTER, "bottom": OUTER, "left": OUTER, "right": OUTER,
            "innerHorizontal": THIN, "innerVertical": THIN,
        }})
        requests.append({"updateBorders": {
            "range": {"sheetId": sid,
                      "startRowIndex": hdr - 1, "endRowIndex": hdr,
                      "startColumnIndex": 0, "endColumnIndex": COL_END},
            "bottom": THICK,
        }})

    pnl_r  = cond_ranges(7, 8)    # col H  P&L Rs.
    pct_r  = cond_ranges(8, 9)    # col I  P&L %
    xirr_r = cond_ranges(11, 12)  # col L  XIRR %
    alt_r  = cond_ranges(0, COL_END)

    if pnl_r:
        requests += [
            {"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": pnl_r,
                "booleanRule": {
                    "condition": {"type": "NUMBER_GREATER", "values": [{"userEnteredValue": "0"}]},
                    "format": {"backgroundColor": POS_BG,
                               "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
                },
            }}},
            {"addConditionalFormatRule": {"index": 1, "rule": {
                "ranges": pnl_r,
                "booleanRule": {
                    "condition": {"type": "NUMBER_LESS", "values": [{"userEnteredValue": "0"}]},
                    "format": {"backgroundColor": NEG_BG,
                               "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
                },
            }}},
        ]
    if pct_r:
        requests += [
            {"addConditionalFormatRule": {"index": 2, "rule": {
                "ranges": pct_r,
                "booleanRule": {
                    "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "-"}]},
                    "format": {"backgroundColor": NEG_BG,
                               "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
                },
            }}},
            {"addConditionalFormatRule": {"index": 3, "rule": {
                "ranges": pct_r,
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue":
                                      f'=AND(NOT(ISERROR(FIND("%",I{anchor}))),ISERROR(FIND("-",I{anchor})))'}]},
                    "format": {"backgroundColor": POS_BG,
                               "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
                },
            }}},
        ]
    for idx_base, col_letter, ranges in [(4, "L", xirr_r)]:
        if not ranges:
            continue
        requests += [
            {"addConditionalFormatRule": {"index": idx_base, "rule": {
                "ranges": ranges,
                "booleanRule": {
                    "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "-"}]},
                    "format": {"backgroundColor": NEG_BG,
                               "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
                },
            }}},
            {"addConditionalFormatRule": {"index": idx_base + 1, "rule": {
                "ranges": ranges,
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue":
                                      f'=AND(NOT(ISERROR(FIND("%",{col_letter}{anchor}))),ISERROR(FIND("-",{col_letter}{anchor})))'}]},
                    "format": {"backgroundColor": POS_BG,
                               "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
                },
            }}},
        ]
    if alt_r:
        requests.append({"addConditionalFormatRule": {"index": 10, "rule": {
            "ranges": alt_r,
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue": "=MOD(ROW(),2)=0"}]},
                "format": {"backgroundColor": PALE},
            },
        }}})

    # Portfolio XIRR row formatting
    px = port_xirr_row
    requests += [
        {"addConditionalFormatRule": {"index": 6, "rule": {
            "ranges": [rng(px, px, 11, 12)],
            "booleanRule": {
                "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "-"}]},
                "format": {"backgroundColor": NEG_BG,
                           "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
            },
        }}},
        {"addConditionalFormatRule": {"index": 7, "rule": {
            "ranges": [rng(px, px, 11, 12)],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue":
                                  f'=AND(NOT(ISERROR(FIND("%",L{px}))),ISERROR(FIND("-",L{px})))'}]},
                "format": {"backgroundColor": POS_BG,
                           "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
            },
        }}},
    ]

    sh.batch_update({"requests": requests})

    ws.format(f"A{px}:K{px}", {
        "backgroundColor": NAVY,
        "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE},
        "horizontalAlignment": "LEFT",
    })
    ws.format(f"L{px}", {
        "backgroundColor": NAVY,
        "textFormat": {"bold": True, "fontSize": 11, "foregroundColor": WHITE},
        "horizontalAlignment": "RIGHT",
    })
    print("SI_Portfolio: formatting applied")


# ── Column format save / apply ────────────────────────────────────────────────
def save_column_format():
    """
    Read the current column widths and hidden state from SI_Portfolio and save
    to si_portfolio_format.json.  Run once after manually formatting the sheet:
        python update_si_sheet.py --save-format
    Subsequent normal runs will restore this layout automatically.
    """
    ws   = sh.worksheet("SI_Portfolio")
    sid  = ws.id
    meta = sh.fetch_sheet_metadata()
    sheet_meta = next((s for s in meta.get("sheets", [])
                       if s["properties"]["sheetId"] == sid), {})
    col_meta = sheet_meta.get("data", [{}])[0].get("columnMetadata", [])
    fmt = {}
    for i, cm in enumerate(col_meta):
        entry = {}
        if cm.get("pixelSize"):
            entry["width"] = cm["pixelSize"]
        if cm.get("hiddenByUser"):
            entry["hidden"] = True
        if entry:
            fmt[str(i)] = entry
    with open(FORMAT_FILE, "w", encoding="utf-8") as f:
        json.dump(fmt, f, indent=2)
    print(f"Saved format for {len(fmt)} columns → {FORMAT_FILE}")


def apply_column_format(ws):
    """
    Restore column widths and hidden state from si_portfolio_format.json.
    No-op if the file does not exist yet.
    """
    if not os.path.exists(FORMAT_FILE):
        print("No saved column format found — skipping (run --save-format to capture one).")
        return
    with open(FORMAT_FILE, encoding="utf-8") as f:
        fmt = json.load(f)
    if not fmt:
        return
    sid      = ws.id
    requests = []
    for col_str, props in fmt.items():
        col_idx   = int(col_str)
        col_props = {}
        fields    = []
        if "width" in props:
            col_props["pixelSize"]    = props["width"]
            fields.append("pixelSize")
        if props.get("hidden"):
            col_props["hiddenByUser"] = True
            fields.append("hiddenByUser")
        elif "hidden" in props:          # explicitly not hidden — make sure it's visible
            col_props["hiddenByUser"] = False
            fields.append("hiddenByUser")
        if col_props:
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": col_idx, "endIndex": col_idx + 1},
                "properties": col_props,
                "fields": ",".join(fields),
            }})
    if requests:
        sh.batch_update({"requests": requests})
        print(f"Column format restored ({len(requests)} columns).")


def save_watchlist_format():
    """Save current Watchlist column widths to watchlist_format.json.
    Reads widths from the API (includeGridData=True) so it captures any
    manual resizes made in the browser, not just the hardcoded defaults."""
    ws   = sh.worksheet("Watchlist")
    sid  = ws.id
    resp = sh.client.request(
        "GET",
        f"https://sheets.googleapis.com/v4/spreadsheets/{sh.id}",
        params={"fields": "sheets(properties/sheetId,data/columnMetadata)",
                "includeGridData": "false"},
    ).json()
    sheet_meta = next((s for s in resp.get("sheets", [])
                       if s["properties"]["sheetId"] == sid), {})
    col_meta = sheet_meta.get("data", [{}])[0].get("columnMetadata", [])
    fmt = {}
    for i, cm in enumerate(col_meta):
        entry = {}
        if cm.get("pixelSize"):
            entry["width"] = cm["pixelSize"]
        if cm.get("hiddenByUser"):
            entry["hidden"] = True
        if entry:
            fmt[str(i)] = entry
    # If API returned nothing, fall back to hardcoded COL_W defaults
    if not fmt:
        COL_W = [35, 90, 220, 120, 120, 85, 85, 80, 110, 65, 120, 120, 120, 100, 250]
        fmt = {str(i): {"width": w} for i, w in enumerate(COL_W)}
    with open(WATCHLIST_FORMAT_FILE, "w", encoding="utf-8") as f:
        json.dump(fmt, f, indent=2)
    print(f"Saved Watchlist format for {len(fmt)} columns → {WATCHLIST_FORMAT_FILE}")


def apply_watchlist_format(ws):
    """Restore Watchlist column widths from watchlist_format.json. No-op if file absent."""
    if not os.path.exists(WATCHLIST_FORMAT_FILE):
        return
    with open(WATCHLIST_FORMAT_FILE, encoding="utf-8") as f:
        fmt = json.load(f)
    if not fmt:
        return
    sid      = ws.id
    requests = []
    for col_str, props in fmt.items():
        col_idx   = int(col_str)
        col_props = {}
        fields    = []
        if "width" in props:
            col_props["pixelSize"] = props["width"]
            fields.append("pixelSize")
        if col_props:
            requests.append({"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": col_idx, "endIndex": col_idx + 1},
                "properties": col_props,
                "fields": ",".join(fields),
            }})
    if requests:
        sh.batch_update({"requests": requests})
        print(f"Watchlist: column format restored ({len(requests)} columns).")


# ── Watchlist tab ─────────────────────────────────────────────────────────────
def create_watchlist():
    """
    Creates or refreshes the Watchlist tab, positioned after SI_Portfolio.

    User workflow: enter NSE Ticker (col B) + Last Disc. Date (col K) →
    all formula columns auto-fill. Manual cols: B Ticker, D Analyst,
    E Sector, K Last Disc. Date, N Status, O Notes. Safe to re-run at any time.

    Columns:
      A #  B Ticker  C Company  D Analyst  E Sector
      F CMP  G 52W High  H 52W Low
      I Mkt Cap (₹ Cr)  J P/E
      K Last Disc. Date  L Last Disc. Price (₹)  M Chg since LDP %
      N Status  O Notes
    """
    NROWS = 100

    # ── Get or create sheet ────────────────────────────────────────────────
    is_new = False
    try:
        ws = sh.worksheet("Watchlist")
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title="Watchlist", rows=NROWS + 10, cols=15)
        is_new = True

    sid     = ws.id
    D_START = 4                       # rows 1-2 blank, row 3 = headers, data from row 4
    last    = D_START + NROWS - 1     # = 103

    apply_fmt = is_new or "--format-watchlist" in sys.argv

    # ── Insert Analyst column (col D) — idempotent ─────────────────────────
    row3 = ws.row_values(3)
    if len(row3) < 4 or row3[3] != "Analyst":
        sh.batch_update({"requests": [{"insertDimension": {
            "range": {"sheetId": sid, "dimension": "COLUMNS",
                      "startIndex": 3, "endIndex": 4},
            "inheritFromBefore": False,
        }}]})
        print("Watchlist: Analyst column inserted at col D")

    # ── Headers (row 3) ────────────────────────────────────────────────────
    HEADERS = [
        "#", "NSE Ticker", "Company", "Analyst", "Sector",
        "CMP (₹)", "52W High (₹)", "52W Low (₹)",
        "Mkt Cap (₹ Cr)", "P/E", "Last Disc. Date", "Last Disc. Price (₹)", "Chg since LDP %",
        "Status", "Notes",
    ]
    ws.update(range_name="A3:O3", values=[HEADERS], value_input_option="RAW")

    # ── Formula columns (rows 4 to last) ───────────────────────────────────
    rows = range(D_START, last + 1)

    def fcol(col_range, fn):
        ws.update(range_name=col_range, values=[[fn(r)] for r in rows], value_input_option="USER_ENTERED")

    gf = lambda attr, r: f'=IF(B{r}="","",IFERROR(GOOGLEFINANCE("NSE:"&B{r},"{attr}"),"—"))'

    fcol(f"A{D_START}:A{last}", lambda r: f'=IF(B{r}="","",ROW()-3)')
    fcol(f"C{D_START}:C{last}", lambda r: f'=IF(B{r}="","",IFERROR(GOOGLEFINANCE("NSE:"&B{r},"name"),"—"))')
    fcol(f"F{D_START}:F{last}", lambda r: gf("price",  r))
    fcol(f"G{D_START}:G{last}", lambda r: gf("high52", r))
    fcol(f"H{D_START}:H{last}", lambda r: gf("low52",  r))
    fcol(f"I{D_START}:I{last}", lambda r:
         f'=IF(B{r}="","",IFERROR(TEXT(GOOGLEFINANCE("NSE:"&B{r},"marketcap")/10000000,"#,##0"),"—"))')
    fcol(f"J{D_START}:J{last}", lambda r: gf("pe", r))
    # Last Disc. Price: ISNUMBER check (date cells store a serial, not "")
    fcol(f"L{D_START}:L{last}", lambda r:
         f'=IF(OR(B{r}="",NOT(ISNUMBER(K{r}))),"",IFERROR(INDEX(GOOGLEFINANCE("NSE:"&B{r},"close",K{r},K{r}+7),2,2),"—"))')
    fcol(f"M{D_START}:M{last}", lambda r:
         f'=IF(OR(B{r}="",NOT(ISNUMBER(L{r})),L{r}=0,NOT(ISNUMBER(F{r}))),"",TEXT((F{r}/L{r}-1)*100,"+0.00;-0.00;0.00")&"%")')

    ws.freeze(rows=3)

    # ── Date number format on col K — always applied (functional, not cosmetic)
    sh.batch_update({"requests": [{"repeatCell": {
        "range": {"sheetId": sid,
                  "startRowIndex": D_START - 1, "endRowIndex": last,
                  "startColumnIndex": 10, "endColumnIndex": 11},
        "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd-mmm-yyyy"}}},
        "fields": "userEnteredFormat.numberFormat",
    }}]})

    # ── Col M conditional format (red/green) — always applied, no other rules touched
    POS_BG   = {"red": 0.902, "green": 0.957, "blue": 0.914}
    NEG_BG   = {"red": 0.992, "green": 0.887, "blue": 0.882}
    POS_TEXT = {"red": 0.118, "green": 0.408, "blue": 0.137}
    NEG_TEXT = {"red": 0.612, "green": 0.0,   "blue": 0.004}
    M_RANGE  = {"sheetId": sid, "startRowIndex": D_START - 1, "endRowIndex": last,
                "startColumnIndex": 12, "endColumnIndex": 13}

    meta_now   = sh.fetch_sheet_metadata()
    sheet_meta = next((s for s in meta_now.get("sheets", [])
                       if s["properties"]["sheetId"] == sid), {})
    existing   = sheet_meta.get("conditionalFormats", [])
    # Delete only rules that cover col M (startColumnIndex == 12)
    l_rule_idxs = [i for i, r in enumerate(existing)
                   if any(rng.get("startColumnIndex") == 12
                          for rng in r.get("ranges", []))]
    delete_reqs = [{"deleteConditionalFormatRule": {"index": i, "sheetId": sid}}
                   for i in sorted(l_rule_idxs, reverse=True)]
    add_reqs = [
        {"addConditionalFormatRule": {"index": 0, "rule": {
            "ranges": [M_RANGE],
            "booleanRule": {
                "condition": {"type": "TEXT_CONTAINS", "values": [{"userEnteredValue": "-"}]},
                "format": {"backgroundColor": NEG_BG,
                           "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
            },
        }}},
        {"addConditionalFormatRule": {"index": 1, "rule": {
            "ranges": [M_RANGE],
            "booleanRule": {
                "condition": {"type": "CUSTOM_FORMULA",
                              "values": [{"userEnteredValue":
                                  f'=AND(NOT(ISERROR(FIND("%",M{D_START}))),ISERROR(FIND("-",M{D_START})))'}]},
                "format": {"backgroundColor": POS_BG,
                           "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
            },
        }}},
    ]
    sh.batch_update({"requests": delete_reqs + add_reqs})
    print(f"Watchlist: headers + formulas written ({NROWS} rows)")

    # ── Formatting — only on first creation or --format-watchlist ──────────
    if apply_fmt:
        NAVY     = {"red": 0.122, "green": 0.235, "blue": 0.392}
        WHITE    = {"red": 1.0,   "green": 1.0,   "blue": 1.0}
        PALE     = {"red": 0.933, "green": 0.953, "blue": 0.980}
        POS_BG   = {"red": 0.902, "green": 0.957, "blue": 0.914}
        NEG_BG   = {"red": 0.992, "green": 0.887, "blue": 0.882}
        POS_TEXT = {"red": 0.118, "green": 0.408, "blue": 0.137}
        NEG_TEXT = {"red": 0.612, "green": 0.0,   "blue": 0.004}
        BDR_MED  = {"red": 0.122, "green": 0.235, "blue": 0.392}

        ws.format("A3:O3", {
            "backgroundColor": NAVY,
            "textFormat": {"bold": True, "fontSize": 10, "foregroundColor": WHITE},
            "horizontalAlignment": "CENTER", "verticalAlignment": "MIDDLE",
            "wrapStrategy": "WRAP",
        })
        ws.format(f"A{D_START}:O{last}", {"textFormat": {"fontSize": 10}, "verticalAlignment": "MIDDLE"})
        ws.format(f"A{D_START}:B{last}", {"horizontalAlignment": "CENTER"})
        ws.format(f"C{D_START}:E{last}", {"horizontalAlignment": "LEFT"})
        ws.format(f"F{D_START}:M{last}", {"horizontalAlignment": "RIGHT"})
        ws.format(f"N{D_START}:O{last}", {"horizontalAlignment": "LEFT"})

        def rng(r0, r1, c0, c1):
            return {"sheetId": sid,
                    "startRowIndex": r0 - 1, "endRowIndex": r1,
                    "startColumnIndex": c0,  "endColumnIndex": c1}

        meta       = sh.fetch_sheet_metadata()
        sheet_meta = next((s for s in meta.get("sheets", [])
                           if s["properties"]["sheetId"] == sid), {})
        n_rules = len(sheet_meta.get("conditionalFormats", []))
        if n_rules:
            sh.batch_update({"requests": [
                {"deleteConditionalFormatRule": {"index": 0, "sheetId": sid}}
                for _ in range(n_rules)
            ]})

        COL_W = [35, 90, 220, 120, 120, 85, 85, 80, 110, 65, 120, 120, 120, 100, 250]
        sh.batch_update({"requests": [
            *[{"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "COLUMNS",
                          "startIndex": i, "endIndex": i + 1},
                "properties": {"pixelSize": w}, "fields": "pixelSize",
            }} for i, w in enumerate(COL_W)],
            {"updateDimensionProperties": {
                "range": {"sheetId": sid, "dimension": "ROWS",
                          "startIndex": 2, "endIndex": 3},
                "properties": {"pixelSize": 40}, "fields": "pixelSize",
            }},
            {"updateBorders": {
                "range": rng(3, 3, 0, 15),
                "bottom": {"style": "SOLID_MEDIUM", "colorStyle": {"rgbColor": BDR_MED}},
            }},
            {"addConditionalFormatRule": {"index": 0, "rule": {
                "ranges": [rng(D_START, last, 0, 15)],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue": "=MOD(ROW(),2)=0"}]},
                    "format": {"backgroundColor": PALE},
                },
            }}},
            {"addConditionalFormatRule": {"index": 1, "rule": {
                "ranges": [rng(D_START, last, 12, 13)],
                "booleanRule": {
                    "condition": {"type": "TEXT_CONTAINS",
                                  "values": [{"userEnteredValue": "-"}]},
                    "format": {"backgroundColor": NEG_BG,
                               "textFormat": {"foregroundColor": NEG_TEXT, "bold": True}},
                },
            }}},
            {"addConditionalFormatRule": {"index": 2, "rule": {
                "ranges": [rng(D_START, last, 12, 13)],
                "booleanRule": {
                    "condition": {"type": "CUSTOM_FORMULA",
                                  "values": [{"userEnteredValue":
                                      f'=AND(NOT(ISERROR(FIND("%",M{D_START}))),ISERROR(FIND("-",M{D_START})))'}]},
                    "format": {"backgroundColor": POS_BG,
                               "textFormat": {"foregroundColor": POS_TEXT, "bold": True}},
                },
            }}},
            {"repeatCell": {
                "range": rng(D_START, last, 10, 11),
                "cell": {"userEnteredFormat": {"numberFormat": {"type": "DATE", "pattern": "dd-mmm-yyyy"}}},
                "fields": "userEnteredFormat.numberFormat",
            }},
            {"setDataValidation": {
                "range": rng(D_START, last, 13, 14),
                "rule": {
                    "condition": {
                        "type": "ONE_OF_LIST",
                        "values": [{"userEnteredValue": v}
                                   for v in ["Watching", "Tracking", "Interested", "Pass", "Portfolio"]],
                    },
                    "showCustomUi": True, "strict": False,
                },
            }},
        ]})
        apply_watchlist_format(ws)   # restore saved column widths (no-op if file absent)
        print("Watchlist: formatting applied")

    # ── Position after SI_Portfolio ────────────────────────────────────────
    meta   = sh.fetch_sheet_metadata()
    sheets = meta.get("sheets", [])
    si_idx = next((s["properties"]["index"] for s in sheets
                   if s["properties"]["title"] == "SI_Portfolio"), None)
    if si_idx is not None:
        sh.batch_update({"requests": [{"updateSheetProperties": {
            "properties": {"sheetId": sid, "index": si_idx + 1},
            "fields": "index",
        }}]})
        print("Watchlist: positioned after SI_Portfolio")


# ── Watchlist sector population (TheWrap Market Map) ──────────────────────────
_TW_API  = ("https://wabi-india-central-a-primary-api.analysis.windows.net"
            "/public/reports/querydata?synchronous=true")
_TW_KEY  = "20d70a38-025d-4a7c-8bc3-778c7823b516"
_TW_BODY = {
    "version": "1.0.0",
    "queries": [{
        "Query": {
            "Commands": [{
                "SemanticQueryDataShapeCommand": {
                    "Query": {
                        "Version": 2,
                        "From": [{"Name": "m", "Entity": "MarketMap", "Type": 0}],
                        "Select": [
                            {"Column": {"Expression": {"SourceRef": {"Source": "m"}},
                                        "Property": "CompanyName"}, "Name": "CompanyName"},
                            {"Column": {"Expression": {"SourceRef": {"Source": "m"}},
                                        "Property": "Index"}, "Name": "SubIndustry"},
                            {"Column": {"Expression": {"SourceRef": {"Source": "m"}},
                                        "Property": "Industry"}, "Name": "Industry"},
                        ],
                    },
                    "Binding": {
                        "Primary": {"Groupings": [{"Projections": [0, 1, 2]}]},
                        "DataReduction": {"DataVolume": 4, "Primary": {"Top": {"Count": 10000}}},
                        "Version": 1,
                    },
                }
            }]
        },
        "QueryId": "",
        "ApplicationContext": {
            "DatasetId": "3d5680cd-652b-4fbd-b7ff-34f7b6fb2f8e",
            "Sources": [{"ReportId": "53d20f7b-d345-4462-9c59-3e44b64c4ad8"}],
        },
    }],
    "cancelQueries": [],
    "modelId": 6625446,
}


def _fetch_thewrap_market_map():
    """Call TheWrap Power BI public API and return list of {CompanyName, SubIndustry, Industry}."""
    resp = requests.post(
        _TW_API,
        headers={"Content-Type": "application/json", "x-powerbi-resourcekey": _TW_KEY},
        json=_TW_BODY,
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()

    DS0  = data["results"][0]["result"]["data"]["dsr"]["DS"][0]
    DM0  = DS0["PH"][0]["DM0"]
    VD   = DS0["ValueDicts"]      # {"D0": [...], "D1": [...], "D2": [...]}

    NCOLS = 3
    rows  = []
    prev  = [None] * NCOLS

    for entry in DM0:
        R  = entry.get("R", 0)
        C  = entry.get("C", [])
        ci = 0
        cur = []
        for col in range(NCOLS):
            if R & (1 << col):
                cur.append(prev[col])
            else:
                idx = C[ci]; ci += 1
                d   = VD.get(f"D{col}", [])
                if isinstance(d, list) and isinstance(idx, int) and 0 <= idx < len(d):
                    cur.append(d[idx])
                else:
                    cur.append(idx)   # inline value (not a dict index)
        prev = cur
        rows.append({"CompanyName": cur[0], "SubIndustry": cur[1], "Industry": cur[2]})

    return rows


def _norm_co(name):
    """Normalise company name for fuzzy matching."""
    if not name:
        return ""
    n = name.lower()
    n = re.sub(r'\(india\)', '', n)                              # strip "(India)"
    n = re.sub(r'\b(ltd|limited|pvt|co|inc|corp|plc|llp)\b\.?', '', n)
    n = re.sub(r'[^a-z0-9 ]', ' ', n)
    return re.sub(r'\s+', ' ', n).strip()


def populate_watchlist_sectors():
    """
    Fetches sub-industry for ALL Watchlist companies from TheWrap Market Map and
    writes to col E, overwriting existing values.
    Companies not found in TheWrap are skipped (existing value preserved).
    Run with: python update_si_sheet.py --populate-sectors
    """
    print("Watchlist: fetching Market Map from TheWrap...")
    thewrap = _fetch_thewrap_market_map()
    print(f"  {len(thewrap)} companies loaded from TheWrap")

    # Normalised lookup: norm_name → row dict
    tw_norm = {_norm_co(r["CompanyName"]): r for r in thewrap}

    ws      = sh.worksheet("Watchlist")
    D_START = 4
    # B=ticker, C=company name, D=middle, E=sector
    rows = ws.get(f"B{D_START}:E1000", value_render_option="FORMATTED_VALUE")

    updates = []
    for i, r in enumerate(rows):
        r       = r + [""] * (4 - len(r))
        ticker  = r[0].strip()
        co_name = r[1].strip()   # col C
        if not ticker and not co_name:
            continue

        needle = _norm_co(co_name) if co_name else _norm_co(ticker)
        match  = tw_norm.get(needle)
        if not match:
            close = difflib.get_close_matches(needle, tw_norm.keys(), n=1, cutoff=0.75)
            match = tw_norm[close[0]] if close else None

        row_num = D_START + i
        if match:
            sector = match["SubIndustry"]
            updates.append({"range": f"E{row_num}", "values": [[sector]]})
            print(f"  {(co_name or ticker):35s} → {sector}")
        else:
            print(f"  {(co_name or ticker):35s} → (not in TheWrap — skipped)")

    if updates:
        ws.batch_update(updates, value_input_option="RAW")
        print(f"Watchlist: {len(updates)} sector cells updated")
    else:
        print("Watchlist: no TheWrap matches found")


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--save-format" in sys.argv:
        print("Saving current SI_Portfolio column format...")
        save_column_format()
        sys.exit(0)

    if "--save-watchlist-format" in sys.argv:
        print("Saving current Watchlist column format...")
        save_watchlist_format()
        sys.exit(0)

    if "--populate-sectors" in sys.argv:
        # Standalone run: refresh all empty sectors without running the full update
        populate_watchlist_sectors()
        sys.exit(0)

    print("Fixing All Trades: converting text numbers to numeric values...")
    fix_at_numbers()

    print("\nSetting up All Trades date serial helper...")
    setup_all_trades_helper()

    print("\nWriting SI_Portfolio...")
    ws_port, layout = write_portfolio()

    print("\nApplying formatting...")
    format_portfolio_tab(ws_port, layout)

    print("\nRestoring saved column format...")
    apply_column_format(ws_port)

    print("\nCreating/refreshing Watchlist...")
    create_watchlist()

    print("\nUpdating Watchlist sectors from TheWrap...")
    populate_watchlist_sectors()

    print("\nDone. SI_Portfolio now updates automatically when All Trades changes.")
    print("Re-run this script only when: adding a new company, or after a demerger.")
    print("Sheet:", "https://docs.google.com/spreadsheets/d/14zSRp_Q8bOU6w9Z3gz6csV9FFNTC37jitur7I_Egeqg")
