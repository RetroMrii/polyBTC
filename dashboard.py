from pathlib import Path
import json
from datetime import datetime
from html import escape

import pandas as pd
import plotly.graph_objects as go
import streamlit as st


# ============================================================
# Page config
# ============================================================

st.set_page_config(
    page_title="BTC 5m Bot Dashboard",
    page_icon="₿",
    layout="wide",
    initial_sidebar_state="collapsed",
)


# ============================================================
# File paths
# ============================================================

PROJECT_DIR = Path(__file__).parent
REFRESH_SECONDS = 5

TRADE_CANDIDATE_FILES = [
    PROJECT_DIR / "btc_5m_trades.csv",
    PROJECT_DIR / "btc5m_trades.csv",
]

DECISION_CANDIDATE_FILES = [
    PROJECT_DIR / "btc_5m_decisions.csv",
    PROJECT_DIR / "btc5m_decisions.csv",
]

STATE_CANDIDATE_FILES = [
    PROJECT_DIR / "btc_5m_state.json",
    PROJECT_DIR / "btc5m_state.json",
]

QUALITY_FILE = PROJECT_DIR / "trade_quality_scored.csv"
COMBINED_DIAG_FILE = PROJECT_DIR / "trade_quality_combined_diagnostics.csv"
TRADINGAGENTS_REVIEW_FILE = PROJECT_DIR / "tradingagents_daily_review.json"
PHASE11_READINESS_FILE = PROJECT_DIR / "phase11_readiness_report.json"

BTC_CANDIDATE_FILES = [
    PROJECT_DIR / "btc_5m_ohlcv.csv",
    PROJECT_DIR / "btc5m_ohlcv.csv",
    PROJECT_DIR / "btc_5m_data.csv",
    PROJECT_DIR / "btc5m_data.csv",
    PROJECT_DIR / "btc_5m_candles.csv",
    PROJECT_DIR / "btc5m_candles.csv",
    PROJECT_DIR / "btc_5m.csv",
    PROJECT_DIR / "btc5m.csv",
]


# ============================================================
# Styling
# ============================================================

st.markdown(
    """
<style>
:root {
    --bg-main: #050611;
    --bg-card: rgba(13, 15, 34, 0.97);
    --bg-card-soft: rgba(17, 20, 45, 0.96);
    --text-main: #f5f7ff;
    --text-muted: #9fa3c6;
    --text-faint: #666b91;
    --blue: #47c7ff;
    --yellow: #f4d35e;
    --green: #58f08b;
    --red: #ff5c72;
    --purple: #a78bfa;
    --blue-soft: rgba(71, 199, 255, 0.13);
    --green-soft: rgba(88, 240, 139, 0.13);
    --red-soft: rgba(255, 92, 114, 0.15);
    --border: rgba(255, 255, 255, 0.07);
    --border-strong: rgba(255, 255, 255, 0.13);
}

html, body, [data-testid="stAppViewContainer"] {
    background:
        radial-gradient(circle at 8% 0%, rgba(71, 199, 255, 0.075), transparent 30rem),
        radial-gradient(circle at 96% 4%, rgba(167, 139, 250, 0.075), transparent 30rem),
        linear-gradient(180deg, #050611 0%, #070817 52%, #050611 100%);
    color: var(--text-main);
}

[data-testid="stHeader"] { background: transparent; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stSidebar"] { background: #050611; }

.block-container {
    padding-top: 1.05rem;
    padding-bottom: 1.25rem;
    max-width: 100%;
}

h1, h2, h3, h4, h5, h6, p, span, div, label {
    color: var(--text-main);
}

.dashboard-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 1rem;
}

.dashboard-title {
    font-size: 1.65rem;
    font-weight: 950;
    letter-spacing: -0.045em;
}

.dashboard-subtitle {
    margin-top: 0.16rem;
    font-size: 0.82rem;
    color: var(--text-faint);
}

.refresh-pill {
    color: var(--text-muted);
    border: 1px solid var(--border);
    background: rgba(255,255,255,0.03);
    padding: 0.45rem 0.72rem;
    border-radius: 999px;
    font-size: 0.77rem;
    white-space: nowrap;
}

.hero-card {
    min-height: 212px;
    border-radius: 20px;
    padding: 1.25rem;
    background: linear-gradient(145deg, rgba(16, 19, 43, 0.98), rgba(10, 12, 29, 0.98));
    border: 1px solid var(--border-strong);
    box-shadow: 0 18px 55px rgba(0,0,0,0.40);
    position: relative;
    overflow: hidden;
}

.hero-card::after {
    content: "";
    position: absolute;
    width: 230px;
    height: 230px;
    top: -110px;
    right: -90px;
    background: radial-gradient(circle, rgba(71,199,255,0.17), transparent 68%);
    pointer-events: none;
}

.hero-card.green-glow::after {
    background: radial-gradient(circle, rgba(88,240,139,0.19), transparent 68%);
}

.hero-card.red-glow::after {
    background: radial-gradient(circle, rgba(255,92,114,0.22), transparent 68%);
}

.hero-title {
    font-size: 0.82rem;
    color: var(--text-muted);
    font-weight: 850;
    text-transform: uppercase;
    letter-spacing: 0.085em;
    margin-bottom: 0.84rem;
}

.hero-value {
    font-size: 3.55rem;
    line-height: 0.98;
    font-weight: 950;
    letter-spacing: -0.08em;
    position: relative;
    z-index: 2;
}

.hero-value-smaller {
    font-size: 2.82rem;
}

.hero-label {
    margin-top: 0.48rem;
    color: var(--text-muted);
    font-size: 0.98rem;
    position: relative;
    z-index: 2;
}

.hero-lowkey {
    margin-top: 0.9rem;
    color: var(--text-faint);
    font-size: 0.74rem;
    opacity: 0.86;
    position: relative;
    z-index: 2;
}

.mode-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.52rem;
    padding: 0.5rem 0.86rem;
    border-radius: 999px;
    font-size: 0.9rem;
    font-weight: 950;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    position: relative;
    z-index: 2;
}

.mode-pill::before {
    content: "";
    width: 0.56rem;
    height: 0.56rem;
    border-radius: 50%;
    display: inline-block;
}

.mode-paper {
    background: var(--blue-soft);
    border: 1px solid rgba(71,199,255,0.40);
    color: var(--blue);
}
.mode-paper::before { background: var(--blue); }

.mode-live {
    background: var(--red-soft);
    border: 1px solid rgba(255,92,114,0.50);
    color: #ff8492;
}
.mode-live::before { background: var(--red); }

.mode-unknown {
    background: rgba(255,255,255,0.045);
    border: 1px solid var(--border-strong);
    color: var(--text-muted);
}
.mode-unknown::before { background: var(--text-muted); }

.card {
    background: linear-gradient(145deg, rgba(13,15,34,0.98), rgba(9,11,27,0.98));
    border-radius: 18px;
    padding: 1rem;
    border: 1px solid var(--border);
    box-shadow: 0 14px 48px rgba(0,0,0,0.30);
    position: relative;
    overflow: hidden;
}

.card-alert {
    background: linear-gradient(145deg, rgba(31,20,42,0.98), rgba(11,13,31,0.98));
    border: 1px solid rgba(255,92,114,0.58);
}

.card-title {
    font-size: 0.98rem;
    font-weight: 900;
    color: var(--text-main);
    margin-bottom: 0.85rem;
}

.alert-badge {
    position: absolute;
    right: -9px;
    bottom: -9px;
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: var(--red);
    border: 2px solid #ffb1bb;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.45rem;
    font-weight: 950;
    color: white;
}

.good { color: var(--green); }
.bad { color: var(--red); }
.flat { color: var(--text-main); }
.blue { color: var(--blue); }
.yellow { color: var(--yellow); }

.kv-header, .kv-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.8rem;
    align-items: center;
}

.kv-header {
    color: var(--text-faint);
    font-weight: 850;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.065em;
    border-bottom: 1px solid var(--border);
    padding-bottom: 0.48rem;
}

.kv-row {
    font-size: 0.92rem;
    border-bottom: 1px solid var(--border);
    padding: 0.52rem 0;
}

.kv-row div:nth-child(2), .kv-header div:nth-child(2) {
    text-align: right;
}

.decision-feed {
    display: flex;
    flex-direction: column;
    gap: 0.65rem;
}

.decision-chip {
    display: grid;
    grid-template-columns: 46px 1fr;
    gap: 0.8rem;
    align-items: center;
    border-radius: 15px;
    padding: 0.72rem;
    border: 1px solid var(--border);
    background: rgba(255,255,255,0.04);
}

.decision-buy {
    background: linear-gradient(135deg, rgba(88,240,139,0.20), rgba(88,240,139,0.035));
    border-color: rgba(88,240,139,0.35);
}

.decision-sell {
    background: linear-gradient(135deg, rgba(255,92,114,0.22), rgba(255,92,114,0.04));
    border-color: rgba(255,92,114,0.38);
}

.decision-skip {
    background: linear-gradient(135deg, rgba(244,211,94,0.19), rgba(244,211,94,0.04));
    border-color: rgba(244,211,94,0.34);
}

.decision-hold {
    background: linear-gradient(135deg, rgba(71,199,255,0.17), rgba(71,199,255,0.035));
    border-color: rgba(71,199,255,0.29);
}

.decision-error {
    background: linear-gradient(135deg, rgba(255,92,114,0.26), rgba(167,139,250,0.07));
    border-color: rgba(255,92,114,0.42);
}

.decision-icon {
    width: 44px;
    height: 44px;
    border-radius: 14px;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 1.22rem;
    font-weight: 950;
    background: rgba(255,255,255,0.095);
}

.decision-main {
    font-size: 1.02rem;
    font-weight: 900;
    color: var(--text-main);
}

.decision-reason {
    margin-top: 0.12rem;
    font-size: 0.81rem;
    color: var(--text-muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}

.win-modern {
    min-height: 330px;
    display: flex;
    flex-direction: column;
}

.win-head {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.7rem;
    margin-bottom: 1rem;
}

.win-rate-number {
    font-size: 3.35rem;
    line-height: 1;
    font-weight: 950;
    letter-spacing: -0.075em;
}

.win-rate-label {
    color: var(--text-faint);
    font-size: 0.78rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-weight: 850;
}

.win-track {
    width: 100%;
    height: 14px;
    border-radius: 999px;
    background: rgba(255,255,255,0.06);
    border: 1px solid var(--border);
    overflow: hidden;
}

.win-fill {
    height: 100%;
    border-radius: 999px;
    background: linear-gradient(90deg, var(--red), var(--yellow), var(--green));
    box-shadow: 0 0 22px rgba(88,240,139,0.22);
}

.win-marker-row {
    display: flex;
    justify-content: space-between;
    color: var(--text-faint);
    font-size: 0.72rem;
    margin-top: 0.42rem;
}

.win-stats {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.62rem;
    margin-top: 1rem;
}

.win-stat {
    background: rgba(255,255,255,0.04);
    border: 1px solid var(--border);
    border-radius: 13px;
    padding: 0.72rem;
}

.win-stat-label {
    color: var(--text-faint);
    font-size: 0.72rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    font-weight: 850;
}

.win-stat-value {
    margin-top: 0.28rem;
    font-size: 1.05rem;
    font-weight: 950;
}

.live-state-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.8rem;
    margin-bottom: 0.9rem;
}

.state-mini {
    background: rgba(255,255,255,0.035);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 0.85rem;
}

.state-mini-label {
    color: var(--text-faint);
    font-size: 0.74rem;
    text-transform: uppercase;
    letter-spacing: 0.075em;
    font-weight: 850;
}

.state-mini-value {
    margin-top: 0.35rem;
    font-size: 1.14rem;
    font-weight: 950;
}

.dashboard-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-top: 1rem;
    color: var(--text-main);
    font-size: 1.05rem;
}

.brand {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    font-size: 1.08rem;
    font-weight: 850;
}

.brand-logo {
    width: 34px;
    height: 34px;
    border-radius: 10px;
    background: linear-gradient(135deg, var(--green), var(--blue));
    display: flex;
    align-items: center;
    justify-content: center;
    color: #050611;
    font-weight: 950;
}

.section-gap { margin-top: 0.95rem; }

.stDataFrame {
    border-radius: 12px;
    overflow: hidden;
}

div[data-testid="stMetric"] {
    background: linear-gradient(145deg, rgba(13,15,34,0.98), rgba(9,11,27,0.98));
    border: 1px solid var(--border);
    padding: 0.8rem;
    border-radius: 14px;
}

[data-testid="stTabs"] button {
    color: var(--text-muted);
}

@media (max-width: 900px) {
    .dashboard-header { flex-direction: column; align-items: flex-start; }
    .live-state-grid { grid-template-columns: repeat(2, 1fr); }
    .hero-value { font-size: 2.65rem; }
    .hero-value-smaller { font-size: 2.1rem; }
}
</style>
""",
    unsafe_allow_html=True,
)


# ============================================================
# Helpers
# ============================================================


def html(content: str):
    """Render HTML without letting Markdown reinterpret indented tags as code."""
    if hasattr(st, "html"):
        st.html(content)
    else:
        st.markdown(content, unsafe_allow_html=True)


def as_number(value, default=0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def first_existing_path(candidates: list[Path]) -> Path:
    for path in candidates:
        if path.exists():
            return path
    return candidates[0]


TRADES_FILE = first_existing_path(TRADE_CANDIDATE_FILES)
DECISIONS_FILE = first_existing_path(DECISION_CANDIDATE_FILES)
STATE_FILE = first_existing_path(STATE_CANDIDATE_FILES)


def load_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def load_json(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {}, f"File not found: {path}"

    try:
        raw = path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}, f"File exists but is empty: {path}"
        return json.loads(raw), ""
    except json.JSONDecodeError as exc:
        return (
            {},
            f"JSON decode error in {path.name}: line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
    except PermissionError:
        return {}, f"Permission error reading: {path}"
    except Exception as exc:
        return {}, f"{type(exc).__name__} while reading {path.name}: {exc}"


def find_col(df: pd.DataFrame, candidates: list[str]) -> str | None:
    if df.empty:
        return None

    lower_map = {str(col).lower(): col for col in df.columns}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]

    for col in df.columns:
        col_l = str(col).lower()
        for candidate in candidates:
            if candidate.lower() in col_l:
                return col

    return None


def fmt(value, default="—") -> str:
    if value is None:
        return default
    text = str(value)
    if text.strip() == "" or text.lower() == "nan":
        return default
    return escape(text)


def get_state_value(state: dict, candidates: list[str], default="—"):
    for key in candidates:
        if key in state:
            return state[key]
    return default


def get_latest_timestamp(*dfs: pd.DataFrame) -> str:
    candidates = ["timestamp", "time", "datetime", "date", "created_at", "updated_at"]
    latest_values = []

    for df in dfs:
        if df.empty:
            continue

        col = find_col(df, candidates)
        if col is None:
            continue

        series = pd.to_datetime(df[col], errors="coerce").dropna()
        if not series.empty:
            latest_values.append(series.max())

    if not latest_values:
        return datetime.now().strftime("%H:%M:%S")

    return max(latest_values).strftime("%H:%M:%S")


def normalize_mode(raw_mode) -> str:
    value = str(raw_mode or "").strip().lower()

    if "live" in value:
        return "live"
    if "paper" in value:
        return "paper"
    if value in ["", "—", "none", "unknown", "paper/unknown"]:
        return "paper"

    return value


def mode_class(mode_value: str) -> str:
    if mode_value == "live":
        return "mode-live"
    if mode_value == "paper":
        return "mode-paper"
    return "mode-unknown"


def render_card(title: str, body_html: str, alert: bool = False, min_height: int = 155):
    alert_class = " card-alert" if alert else ""
    badge = '<div class="alert-badge">!</div>' if alert else ""

    content = (
        f'<div class="card{alert_class}" style="min-height:{min_height}px;">'
        f'<div class="card-title">{escape(title)}</div>'
        f"{body_html.strip()}"
        f"{badge}"
        f"</div>"
    )
    html(content)


def plotly_dark_layout(fig: go.Figure, height: int = 280):
    fig.update_layout(
        height=height,
        margin=dict(l=12, r=12, t=18, b=12),
        paper_bgcolor="#0d0f22",
        plot_bgcolor="#0d0f22",
        font=dict(color="#f5f7ff"),
        legend=dict(
            orientation="h",
            yanchor="top",
            y=1.08,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            gridcolor="rgba(255,255,255,0.055)",
            zerolinecolor="rgba(255,255,255,0.09)",
        ),
        yaxis=dict(
            gridcolor="rgba(255,255,255,0.055)",
            zerolinecolor="rgba(255,255,255,0.09)",
        ),
    )
    return fig


def infer_pnl_col(trades: pd.DataFrame) -> str | None:
    return find_col(
        trades,
        [
            "pnl",
            "profit",
            "profit_loss",
            "realized_pnl",
            "net_pnl",
            "pnl_usd",
            "return",
        ],
    )


def infer_side_col(df: pd.DataFrame) -> str | None:
    return find_col(df, ["side", "action", "signal", "decision", "direction"])


def infer_reason_col(df: pd.DataFrame) -> str | None:
    return find_col(
        df, ["reason", "decision_reason", "skip_reason", "notes", "message"]
    )


def infer_score_col(df: pd.DataFrame) -> str | None:
    return find_col(
        df, ["score", "model_score", "quality_score", "probability", "confidence"]
    )


def infer_price_col(df: pd.DataFrame) -> str | None:
    return find_col(df, ["close", "price", "btc_price", "last_price", "mark_price"])


def load_btc_market_data() -> pd.DataFrame:
    for path in BTC_CANDIDATE_FILES:
        df = load_csv(path)
        if not df.empty:
            return df
    return pd.DataFrame()


def get_btc_price_and_change(*dfs: pd.DataFrame) -> tuple[float | None, float | None]:
    for df in dfs:
        if df.empty:
            continue

        price_col = infer_price_col(df)
        if price_col is None:
            continue

        prices = pd.to_numeric(df[price_col], errors="coerce").dropna()
        if prices.empty:
            continue

        current_price = float(prices.iloc[-1])
        if len(prices) >= 2 and prices.iloc[-2] != 0:
            change_pct = float(
                ((prices.iloc[-1] - prices.iloc[-2]) / prices.iloc[-2]) * 100
            )
        else:
            change_pct = 0.0

        return current_price, change_pct

    return None, None


def current_streak_from_pnl(series: pd.Series) -> tuple[str, int]:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return "None", 0

    last_sign = 1 if clean.iloc[-1] > 0 else -1 if clean.iloc[-1] < 0 else 0
    if last_sign == 0:
        return "Flat", 0

    streak = 0
    for value in reversed(clean.tolist()):
        sign = 1 if value > 0 else -1 if value < 0 else 0
        if sign == last_sign:
            streak += 1
        else:
            break

    return ("Win" if last_sign > 0 else "Loss"), streak


def decision_style(value) -> tuple[str, str]:
    text = str(value).lower()
    if "error" in text or "fail" in text or "exception" in text:
        return "decision-error", "!"
    if "buy" in text or "long" in text:
        return "decision-buy", "▲"
    if "sell" in text or "short" in text:
        return "decision-sell", "▼"
    if "skip" in text or "block" in text or "reject" in text:
        return "decision-skip", "!"
    if "hold" in text or "wait" in text:
        return "decision-hold", "•"
    return "decision-hold", "₿"


def build_kv_rows(rows: list[tuple[str, object]]) -> str:
    output = '<div class="kv-header"><div>Metric</div><div>Status</div></div>'
    for label, value in rows:
        output += (
            f'<div class="kv-row"><div>{escape(str(label))}</div>'
            f"<div>{fmt(value)}</div></div>"
        )
    return output


def render_win_rate_card(
    win_rate: float,
    total_trades: int,
    best_trade: float,
    worst_trade: float,
    streak_label: str,
    streak_count: int,
):
    bounded = max(0.0, min(100.0, float(win_rate)))
    if bounded >= 60:
        rate_class = "good"
    elif bounded >= 45:
        rate_class = "yellow"
    else:
        rate_class = "bad"

    streak_class = (
        "good" if streak_label == "Win" else "bad" if streak_label == "Loss" else "flat"
    )

    content = (
        '<div class="win-modern">'
        '<div class="win-head">'
        '<div>'
        '<div class="win-rate-label">Win rate</div>'
        f'<div class="win-rate-number {rate_class}">{bounded:.1f}%</div>'
        '</div>'
        '<div style="text-align:right;">'
        '<div class="win-rate-label">Streak</div>'
        f'<div class="win-stat-value {streak_class}">{escape(streak_label)} {streak_count}</div>'
        '</div>'
        '</div>'
        '<div class="win-track">'
        f'<div class="win-fill" style="width:{bounded:.1f}%;"></div>'
        '</div>'
        '<div class="win-marker-row">'
        '<span>0</span><span>45</span><span>60</span><span>100</span>'
        '</div>'
        '<div class="win-stats">'
        '<div class="win-stat">'
        '<div class="win-stat-label">Trades</div>'
        f'<div class="win-stat-value">{total_trades}</div>'
        '</div>'
        '<div class="win-stat">'
        '<div class="win-stat-label">Best</div>'
        f'<div class="win-stat-value good">{best_trade:.4f}</div>'
        '</div>'
        '<div class="win-stat">'
        '<div class="win-stat-label">Worst</div>'
        f'<div class="win-stat-value bad">{worst_trade:.4f}</div>'
        '</div>'
        '<div class="win-stat">'
        '<div class="win-stat-label">Benchmark</div>'
        '<div class="win-stat-value blue">60%</div>'
        '</div>'
        '</div>'
        '</div>'
    )
    render_card("Win profile", content, min_height=330)


# ============================================================
# Live dashboard fragment
# ============================================================


@st.fragment(run_every=f"{REFRESH_SECONDS}s")
def render_live_dashboard():
    trades = load_csv(TRADES_FILE)
    decisions = load_csv(DECISIONS_FILE)
    state, state_error = load_json(STATE_FILE)
    trading_review, trading_review_error = load_json(TRADINGAGENTS_REVIEW_FILE)
    phase11_readiness, phase11_readiness_error = load_json(PHASE11_READINESS_FILE)
    quality = load_csv(QUALITY_FILE)
    market_data = load_btc_market_data()
    combined_diag = load_csv(COMBINED_DIAG_FILE)

    pnl_col = infer_pnl_col(trades)
    decision_side_col = infer_side_col(decisions)
    reason_col = infer_reason_col(decisions)
    score_col = infer_score_col(combined_diag)
    if score_col is None:
        score_col = infer_score_col(quality)

    latest_time = get_latest_timestamp(market_data, trades, decisions, quality, combined_diag)

    total_trades = len(trades)
    total_decisions = len(decisions)

    if pnl_col and not trades.empty:
        trades[pnl_col] = pd.to_numeric(trades[pnl_col], errors="coerce")
        pnl_series = trades[pnl_col].fillna(0)
        total_pnl = float(pnl_series.sum())
        avg_pnl = float(pnl_series.mean()) if len(pnl_series) else 0.0
        win_rate = float((pnl_series > 0).mean() * 100) if len(pnl_series) else 0.0
        best_trade = float(pnl_series.max()) if len(pnl_series) else 0.0
        worst_trade = float(pnl_series.min()) if len(pnl_series) else 0.0
        cumulative_pnl = pnl_series.cumsum()
        peak = cumulative_pnl.cummax()
        drawdown = cumulative_pnl - peak
        max_drawdown = float(drawdown.min()) if len(drawdown) else 0.0
        streak_label, streak_count = current_streak_from_pnl(pnl_series)
    else:
        total_pnl = 0.0
        avg_pnl = 0.0
        win_rate = 0.0
        best_trade = 0.0
        worst_trade = 0.0
        max_drawdown = 0.0
        cumulative_pnl = pd.Series(dtype=float)
        streak_label, streak_count = "None", 0

    raw_mode = get_state_value(
        state, ["mode", "trading_mode", "env", "environment"], default="paper"
    )
    mode = normalize_mode(raw_mode)
    position = get_state_value(
        state, ["position", "current_position", "side", "market_position"], default="—"
    )
    balance = get_state_value(
        state,
        ["balance", "cash", "equity", "wallet_balance", "account_balance"],
        default="—",
    )
    open_size = get_state_value(
        state, ["open_size", "position_size", "size", "qty", "quantity"], default="—"
    )
    last_error = get_state_value(
        state, ["last_error", "error", "last_exception"], default=""
    )

    btc_price, btc_change_pct = get_btc_price_and_change(market_data, decisions, trades, combined_diag)
    risk_alert = bool(last_error) or total_pnl < 0 or max_drawdown < 0

    html(
        f"""
<div class="dashboard-header">
    <div>
        <div class="dashboard-title">BTC 5m Bot Control Dashboard</div>
        <div class="dashboard-subtitle">Fragment-refresh operational view · local CSV/JSON artifacts</div>
    </div>
    <div class="refresh-pill">Fragment refresh {REFRESH_SECONDS}s · Last render {datetime.now().strftime("%H:%M:%S")}</div>
</div>
"""
    )

    top1, top2, top3 = st.columns([1, 1.15, 1], gap="medium")

    with top1:
        html(
            f"""
<div class="hero-card">
    <div class="hero-title">Runtime</div>
    <div class="mode-pill {mode_class(mode)}">{escape(mode.upper())}</div>
    <div class="hero-label" style="margin-top: 1.25rem;">Bot execution mode</div>
    <div class="hero-lowkey">Latest update · {escape(latest_time)}</div>
</div>
"""
        )

    with top2:
        if btc_price is None:
            btc_display = "—"
            btc_sub = "No BTC price column found"
            btc_class = "flat"
        else:
            btc_display = f"${btc_price:,.2f}"
            btc_sub = (
                f"{btc_change_pct:+.3f}% last tick"
                if btc_change_pct is not None
                else "Change unavailable"
            )
            btc_class = "good" if (btc_change_pct or 0) >= 0 else "bad"

        streak_class = (
            "good" if streak_label == "Win" else "bad" if streak_label == "Loss" else "flat"
        )

        html(
            f"""
<div class="hero-card">
    <div class="hero-title">BTC info</div>
    <div class="hero-value hero-value-smaller {btc_class}">{escape(btc_display)}</div>
    <div class="hero-label">{escape(btc_sub)}</div>
    <div class="hero-lowkey">Current streak · <span class="{streak_class}" style="font-weight:950;">{escape(streak_label)} {streak_count}</span></div>
</div>
"""
        )

    with top3:
        pnl_class = "good" if total_pnl > 0 else "bad" if total_pnl < 0 else "flat"
        glow = "green-glow" if total_pnl > 0 else "red-glow" if total_pnl < 0 else ""

        html(
            f"""
<div class="hero-card {glow}">
    <div class="hero-title">Total PnL</div>
    <div class="hero-value {pnl_class}">{total_pnl:.2f}</div>
    <div class="hero-label">Net result</div>
    <div class="hero-lowkey">Avg trade · {avg_pnl:.4f}</div>
</div>
"""
        )

    html('<div class="section-gap"></div>')

    mid1, mid2, mid3 = st.columns([1.35, 1, 0.9], gap="medium")

    with mid1:
        decisions_html = '<div class="decision-feed">'
        if not decisions.empty:
            recent_decisions = decisions.tail(5).iloc[::-1]
            for _, row in recent_decisions.iterrows():
                decision_value = (
                    row.get(decision_side_col, "Decision")
                    if decision_side_col
                    else "Decision"
                )
                reason_value = row.get(reason_col, "") if reason_col else ""
                chip_class, icon = decision_style(decision_value)
                decisions_html += (
                    f'<div class="decision-chip {chip_class}">'
                    f'<div class="decision-icon">{escape(icon)}</div>'
                    f'<div><div class="decision-main">{fmt(decision_value)}</div>'
                    f'<div class="decision-reason">{fmt(str(reason_value)[:130])}</div></div>'
                    f"</div>"
                )
        else:
            decisions_html += (
                '<div class="decision-chip decision-hold">'
                '<div class="decision-icon">?</div>'
                '<div><div class="decision-main">No decisions yet</div>'
                f'<div class="decision-reason">{escape(DECISIONS_FILE.name)} is empty or missing</div></div>'
                "</div>"
            )
        decisions_html += "</div>"
        render_card("Bot decisions", decisions_html, min_height=330)

    with mid2:
        risk_rows = build_kv_rows(
            [
                ("Balance", balance),
                ("Total trades", total_trades),
                ("Decisions", total_decisions),
                ("Best trade", f"{best_trade:.4f}"),
                ("Worst trade", f"{worst_trade:.4f}"),
                ("Max DD", f"{max_drawdown:.4f}"),
            ]
        )
        render_card("Risk and health", risk_rows, alert=risk_alert, min_height=330)

    with mid3:
        render_win_rate_card(
            win_rate=win_rate,
            total_trades=total_trades,
            best_trade=best_trade,
            worst_trade=worst_trade,
            streak_label=streak_label,
            streak_count=streak_count,
        )

    html('<div class="section-gap"></div>')

    overview_tab, trades_tab, decisions_tab, risk_tab, models_tab = st.tabs(
        ["Overview", "Trades", "Decisions", "Risk", "Models"]
    )

    with overview_tab:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total trades", total_trades)
        c2.metric("Win rate", f"{win_rate:.1f}%")
        c3.metric("Total PnL", f"{total_pnl:.4f}")
        c4.metric("Max drawdown", f"{max_drawdown:.4f}")

        st.subheader("Live Bot State")
        html(
            f"""
<div class="live-state-grid">
    <div class="state-mini"><div class="state-mini-label">Position</div><div class="state-mini-value">{fmt(position)}</div></div>
    <div class="state-mini"><div class="state-mini-label">Open size</div><div class="state-mini-value">{fmt(open_size)}</div></div>
    <div class="state-mini"><div class="state-mini-label">Mode</div><div class="state-mini-value">{fmt(mode)}</div></div>
    <div class="state-mini"><div class="state-mini-label">BTC</div><div class="state-mini-value">{escape(f"${btc_price:,.2f}" if btc_price is not None else "—")}</div></div>
</div>
"""
        )

        if state:
            st.json(state)
        else:
            st.warning(f"{STATE_FILE.name} is missing or unreadable.")
            st.code(state_error or f"Dashboard looked here: {STATE_FILE}")

        st.subheader("Cumulative PnL")
        if pnl_col and not trades.empty:
            x_values = list(range(len(cumulative_pnl)))
            time_col = find_col(trades, ["timestamp", "time", "datetime", "date"])
            if time_col:
                x_values = trades[time_col]

            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=cumulative_pnl,
                    mode="lines",
                    name="Cumulative PnL",
                    line=dict(width=3, color="#47c7ff"),
                )
            )
            fig.add_trace(
                go.Scatter(
                    x=x_values,
                    y=[0] * len(cumulative_pnl),
                    mode="lines",
                    name="Break-even",
                    line=dict(width=2, color="#f4d35e", dash="dash"),
                )
            )
            fig = plotly_dark_layout(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.info(f"No PnL column found in {TRADES_FILE.name}.")

    with trades_tab:
        st.subheader("Trade Log")
        if trades.empty:
            st.warning(f"{TRADES_FILE.name} is empty or missing.")
        else:
            st.dataframe(trades.tail(300), use_container_width=True, height=500)

    with decisions_tab:
        st.subheader("Decision Feed")
        if decisions.empty:
            st.warning(f"{DECISIONS_FILE.name} is empty or missing.")
        else:
            if decision_side_col:
                counts = (
                    decisions[decision_side_col]
                    .astype(str)
                    .value_counts()
                    .reset_index()
                )
                counts.columns = ["Decision", "Count"]
                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=counts["Decision"],
                        y=counts["Count"],
                        marker=dict(color="#47c7ff"),
                    )
                )
                fig = plotly_dark_layout(fig, height=315)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            st.dataframe(decisions.tail(500), use_container_width=True, height=500)

    with risk_tab:
        st.subheader("Risk Diagnostics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Current position", str(position))
        c2.metric("Open size", str(open_size))
        c3.metric("Worst trade", f"{worst_trade:.4f}")
        c4.metric("Max drawdown", f"{max_drawdown:.4f}")

        if last_error:
            st.error(f"Last error: {last_error}")
        else:
            st.success("No last_error field found in state.")

        st.subheader("Drawdown Curve")
        if pnl_col and not trades.empty:
            dd_series = cumulative_pnl - cumulative_pnl.cummax()
            fig = go.Figure()
            fig.add_trace(
                go.Scatter(
                    x=list(range(len(dd_series))),
                    y=dd_series,
                    mode="lines",
                    name="Drawdown",
                    line=dict(width=3, color="#ff5c72"),
                )
            )
            fig = plotly_dark_layout(fig, height=340)
            st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
        else:
            st.warning("No PnL data available for drawdown chart.")

    with models_tab:
        st.subheader("Combined Model Diagnostics")

        model_df = combined_diag if not combined_diag.empty else quality

        if model_df.empty:
            st.warning("trade_quality_combined_diagnostics.csv is empty or missing.")
        else:
            latest = model_df.iloc[-1]

            prob_cols = [
                "model_probability",
                "market_probability",
                "ml_probability_good_trade",
                "lgbm_probability_good_trade",
                "xgb_probability_good_trade",
            ]

            confidence_cols = [
                "kronos_confidence",
                "timesfm_confidence",
                "chronos_confidence",
            ]

            vote_cols = [
                "ml_trade_quality_decision",
                "kronos_direction",
                "timesfm_direction",
                "chronos_direction",
                "forecast_agreement_count",
                "forecast_agreement_available_count",
            ]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Model probability", f"{as_number(latest.get('model_probability'), 0):.3f}")
            c2.metric("Market probability", f"{as_number(latest.get('market_probability'), 0):.3f}")
            c3.metric("Edge", f"{as_number(latest.get('edge'), 0):.4f}")
            c4.metric("Close PnL", f"{as_number(latest.get('close_pnl'), 0):.4f}")

            existing_prob_cols = [col for col in prob_cols if col in model_df.columns]
            if existing_prob_cols:
                st.subheader("Probability Stack")
                plot_df = model_df.tail(250).copy()
                x_col = find_col(
                    plot_df,
                    ["candidate_timestamp", "timestamp", "time", "datetime", "date"],
                )
                x_values = list(range(len(plot_df))) if x_col is None else plot_df[x_col]

                fig = go.Figure()
                for col in existing_prob_cols:
                    fig.add_trace(
                        go.Scatter(
                            x=x_values,
                            y=pd.to_numeric(plot_df[col], errors="coerce"),
                            mode="lines",
                            name=col,
                        )
                    )
                fig = plotly_dark_layout(fig, height=360)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            existing_confidence_cols = [
                col for col in confidence_cols if col in model_df.columns
            ]
            if existing_confidence_cols:
                st.subheader("Forecast Confidence")
                confidence_df = pd.DataFrame(
                    [
                        {
                            "model": col.replace("_confidence", ""),
                            "confidence": as_number(latest.get(col), 0),
                        }
                        for col in existing_confidence_cols
                    ]
                )

                fig = go.Figure()
                fig.add_trace(
                    go.Bar(
                        x=confidence_df["model"],
                        y=confidence_df["confidence"],
                    )
                )
                fig = plotly_dark_layout(fig, height=300)
                st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})

            st.subheader("Latest Model Vote")
            existing_vote_cols = [col for col in vote_cols if col in model_df.columns]
            if existing_vote_cols:
                vote_snapshot = pd.DataFrame(
                    [
                        {
                            "field": col,
                            "latest_value": latest.get(col, "—"),
                        }
                        for col in existing_vote_cols
                    ]
                )
                st.dataframe(vote_snapshot, use_container_width=True, height=250)
            else:
                st.info("No vote columns found in combined diagnostics.")

            if "edge" in model_df.columns and "close_pnl" in model_df.columns:
                st.subheader("Edge vs Close PnL")
                scatter_df = model_df.copy()
                scatter_df["edge"] = pd.to_numeric(scatter_df["edge"], errors="coerce")
                scatter_df["close_pnl"] = pd.to_numeric(
                    scatter_df["close_pnl"], errors="coerce"
                )
                scatter_df = scatter_df.dropna(subset=["edge", "close_pnl"]).tail(500)

                if not scatter_df.empty:
                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatter(
                            x=scatter_df["edge"],
                            y=scatter_df["close_pnl"],
                            mode="markers",
                            name="Trades",
                        )
                    )
                    fig = plotly_dark_layout(fig, height=340)
                    fig.update_layout(xaxis_title="Edge", yaxis_title="Close PnL")
                    st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.info("No numeric edge / close_pnl rows available.")

            st.subheader("Recent Combined Diagnostics")
            st.dataframe(model_df.tail(400), use_container_width=True, height=500)

        st.subheader("TradingAgents Daily Review")
        if trading_review:
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Action", str(trading_review.get("recommended_action", "unknown")))
            r2.metric("Risk", str(trading_review.get("risk_level", "unknown")))
            r3.metric("Regime", str(trading_review.get("regime", "unknown")))
            r4.metric("Confidence", f"{as_number(trading_review.get('confidence'), 0):.2f}")

            st.caption(
                "Source: "
                f"{trading_review.get('source', 'unknown')} | "
                f"Status: {trading_review.get('tradingagents_status', 'unknown')}"
            )
            st.json(
                {
                    "allow_trading": trading_review.get("allow_trading"),
                    "max_size_multiplier": trading_review.get("max_size_multiplier"),
                    "main_loss_driver": trading_review.get("main_loss_driver"),
                    "suggested_next_experiment": trading_review.get("suggested_next_experiment"),
                    "do_not_change": trading_review.get("do_not_change", []),
                    "notes": trading_review.get("notes", []),
                }
            )
        else:
            st.warning(f"{TRADINGAGENTS_REVIEW_FILE.name} is missing or unreadable.")
            st.code(trading_review_error or f"Dashboard looked here: {TRADINGAGENTS_REVIEW_FILE}")

        st.subheader("Phase 11 Readiness")
        if phase11_readiness:
            ready = bool(phase11_readiness.get("ready", False))
            if ready:
                st.success("Phase 11 readiness check passed. Manual review is still required before live consumption.")
            else:
                st.error("Phase 11 is blocked. Keep the live bot ignoring AI/ML review outputs.")

            p1, p2, p3, p4 = st.columns(4)
            p1.metric("Ready", str(ready))
            p2.metric("Dataset rows", str(phase11_readiness.get("dataset_rows", 0)))
            p3.metric("Review closes", str(phase11_readiness.get("review_closed_count", 0)))
            p4.metric("Review confidence", f"{as_number(phase11_readiness.get('review_confidence'), 0):.2f}")

            blockers = phase11_readiness.get("blockers", [])
            if blockers:
                st.write("Blockers")
                st.dataframe(
                    pd.DataFrame({"blocker": blockers}),
                    use_container_width=True,
                    height=min(260, 56 + (len(blockers) * 38)),
                )

            st.json(
                {
                    "recommendation": phase11_readiness.get("recommendation"),
                    "checks": phase11_readiness.get("checks", {}),
                    "target_counts": phase11_readiness.get("target_counts", {}),
                    "safe_default_regime": phase11_readiness.get("safe_default_regime", {}),
                    "safety": phase11_readiness.get("safety"),
                }
            )
        else:
            st.warning(f"{PHASE11_READINESS_FILE.name} is missing or unreadable.")
            st.code(phase11_readiness_error or f"Dashboard looked here: {PHASE11_READINESS_FILE}")

    html(
        f"""
<div class="dashboard-footer">
    <div class="brand">
        <div class="brand-logo">₿</div>
        <div>BTC 5m trading bot</div>
    </div>
    <div>{datetime.now().strftime("%H:%M")}</div>
</div>
"""
    )


render_live_dashboard()
