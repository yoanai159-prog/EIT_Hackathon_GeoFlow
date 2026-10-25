"""Look of the platform: logo, colours, small helpers. Colours follow the DryRadar logo (navy, teal, amber)."""
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).parent
NAVY, TEAL, AMBER = "#0B2A4A", "#0E8FA8", "#F59E0B"
LEVEL_COLOR = {"ok": "#1B7F4B", "warn": "#C99700", "high": "#D9660F", "crit": "#B3261E"}
ALERT_HEX = {"green": "#2ea043", "yellow": "#e6be28", "orange": "#f0821e", "red": "#d22828"}

CSS = f"""
<style>
 .block-container{{padding:2rem 2.5rem 3rem 2.5rem;max-width:1400px}}
 [data-testid="stSidebar"]{{min-width:230px}}
 [data-testid="stSidebar"] img{{max-width:100%}}
 h1,h2,h3{{color:{NAVY};letter-spacing:-.01em}}
 [data-testid="stSidebar"]{{border-right:1px solid #dbe5ee}}
 [data-testid="stMetric"]{{background:#fff;border:1px solid #dbe5ee;border-radius:12px;padding:10px 14px;box-shadow:0 1px 2px rgba(11,42,74,.05)}}
 [data-testid="stMetricLabel"]{{color:#5b6f82}}
 div[data-testid="stDataFrame"]{{border:1px solid #dbe5ee;border-radius:10px}}
 .dr-card{{background:#fff;border:1px solid #dbe5ee;border-radius:14px;padding:14px 16px;margin-bottom:12px;box-shadow:0 1px 3px rgba(11,42,74,.06)}}
 .dr-card h4{{margin:0 0 6px;font-size:15px;color:{NAVY}}}
 .dr-badge{{display:inline-block;padding:3px 10px;border-radius:99px;font-weight:700;font-size:13px;border:2px solid currentColor}}
 .dr-row{{display:flex;justify-content:space-between;gap:10px;padding:3px 0;font-size:14px;border-bottom:1px solid #eef3f7}}
 .dr-muted{{color:#5b6f82;font-size:12px}}
 .dr-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;margin-right:6px}}
</style>
"""


def setup():
    """Page config (title, icon), theme CSS and the logo. Call first in app.py."""
    icon = ROOT / "assets" / "dryradar_icon.png"
    st.set_page_config(page_title="DryRadar", page_icon=str(icon) if icon.exists() else None, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)
    logo = ROOT / "assets" / "dryradar_logo.png"
    if logo.exists():
        st.logo(str(logo), size="large")


def badge(text: str, color: str) -> str:
    return f'<span class="dr-badge" style="color:{color}">{text}</span>'


def card(title: str, body_html: str):
    st.markdown(f'<div class="dr-card"><h4>{title}</h4>{body_html}</div>', unsafe_allow_html=True)


def rows(pairs) -> str:
    return "".join(f'<div class="dr-row"><span>{a}</span><b>{b}</b></div>' for a, b in pairs)


def chart(kind: str, df, x_label: str, y_label: str, source: str, note: str = ""):
    """Line or bar chart with named axes (units) and a caption that says what is on each axis and where the data come from."""
    fn = st.bar_chart if kind == "bar" else st.line_chart
    try:
        fn(df, x_label=x_label, y_label=y_label)
    except TypeError:                      # older Streamlit without axis labels
        fn(df)
    st.caption(f"Horizontal axis: {x_label}. Vertical axis: {y_label}. {note} Source: {source}".replace("  ", " "))
