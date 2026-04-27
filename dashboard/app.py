import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.broker import get_account, get_positions
from src.data_feed import get_bars
from src.indicators import add_indicators
from src.strategy import get_signal, Signal
from src.backtest import run_backtest
from src.config import TRADE_SYMBOLS

st.set_page_config(page_title="Stock Trading Bot", layout="wide", page_icon="📈")

# ── 토스 스타일 CSS ──────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"] {
    font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
}

/* 전체 배경 */
.stApp { background-color: #0A0A0A; }

/* 헤더 숨기기 */
header[data-testid="stHeader"] { background: transparent; }

/* 카드 스타일 */
.toss-card {
    background: #1C1C1E;
    border-radius: 16px;
    padding: 20px 24px;
    margin-bottom: 12px;
    border: 1px solid #2C2C2E;
}

/* 신호 배지 */
.badge {
    display: inline-block;
    padding: 4px 12px;
    border-radius: 20px;
    font-size: 13px;
    font-weight: 600;
    letter-spacing: -0.3px;
}
.badge-buy  { background: rgba(0, 210, 120, 0.15); color: #00D278; }
.badge-sell { background: rgba(255, 71,  71, 0.15); color: #FF4747; }
.badge-hold { background: rgba(142,142,147, 0.15); color: #8E8E93; }

/* 종목 행 */
.sym-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 0;
    border-bottom: 1px solid #2C2C2E;
}
.sym-row:last-child { border-bottom: none; }
.sym-name { font-weight: 600; font-size: 15px; color: #F5F5F5; }
.sym-sub  { font-size: 12px; color: #8E8E93; margin-top: 2px; }

/* 섹션 제목 */
.section-title {
    font-size: 18px;
    font-weight: 700;
    color: #F5F5F5;
    margin-bottom: 16px;
    letter-spacing: -0.5px;
}

/* st.metric 오버라이드 */
[data-testid="stMetric"] {
    background: #1C1C1E;
    border-radius: 16px;
    padding: 16px 20px;
    border: 1px solid #2C2C2E;
}
[data-testid="stMetricLabel"] { color: #8E8E93 !important; font-size: 13px !important; }
[data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 700 !important; color: #F5F5F5 !important; }
[data-testid="stMetricDelta"] svg { display: none; }

/* 구분선 */
hr { border-color: #2C2C2E !important; margin: 24px 0 !important; }

/* selectbox / slider */
[data-baseweb="select"] { border-radius: 12px !important; }
.stSlider { padding: 4px 0; }

/* plotly 배경 */
.js-plotly-plot { border-radius: 12px; overflow: hidden; }

/* 신호 알림 박스 */
.stAlert { border-radius: 12px !important; border: none !important; }
div[data-testid="stMarkdownContainer"] p { margin: 0; }
</style>
""", unsafe_allow_html=True)


# ── 타이틀 ──────────────────────────────────────────────────
st.markdown('<h1 style="font-size:28px;font-weight:800;letter-spacing:-1px;color:#F5F5F5;margin-bottom:4px;">주식 트레이딩 봇</h1>', unsafe_allow_html=True)
st.markdown('<p style="color:#8E8E93;font-size:14px;margin-bottom:24px;">실시간 모니터링 대시보드</p>', unsafe_allow_html=True)

# ── 계좌 현황 ──────────────────────────────────────────────
try:
    acct = get_account()
    pnl = acct['pnl']
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산",   f"${acct['equity']:,.2f}")
    col2.metric("현금",      f"${acct['cash']:,.2f}")
    col3.metric("매수 가능", f"${acct['buying_power']:,.2f}")
    col4.metric("오늘 손익", f"${pnl:+,.2f}", delta=f"{pnl:+.2f}")
except Exception as e:
    st.error(f"계좌 정보 오류: {e}")

st.divider()

# ── 차트 & 사이드패널 ──────────────────────────────────────
col_left, col_right = st.columns([2, 1])

with col_left:
    st.markdown('<div class="section-title">가격 차트</div>', unsafe_allow_html=True)
    ctrl1, ctrl2 = st.columns([2, 1])
    symbol    = ctrl1.selectbox("종목", TRADE_SYMBOLS, label_visibility="collapsed")
    tf_option = ctrl2.selectbox("타임프레임", ["1Min", "5Min", "15Min", "1Hour"], index=1, label_visibility="collapsed")

    # 타임프레임별 기본 표시 캔들 수 및 로드 기간
    tf_config = {"1Min": (60, 100), "5Min": (30, 80), "15Min": (60, 60), "1Hour": (180, 50)}
    load_days, default_candles = tf_config.get(tf_option, (30, 80))

    try:
        df = get_bars(symbol, days=load_days, timeframe=tf_option)
        df = add_indicators(df)
        signal, reason = get_signal(df.iloc[:-1].copy())

        if signal == Signal.BUY:
            st.success(f"매수 신호  |  {reason}")
        elif signal == Signal.SELL:
            st.error(f"매도 신호  |  {reason}")
        else:
            st.info(f"홀드  |  {reason}")

        # 볼륨 프로파일 계산
        bins = 30
        price_min = df["low"].min()
        price_max = df["high"].max()
        bin_size  = (price_max - price_min) / bins
        vp_prices, vp_vols = [], []
        for b in range(bins):
            lo = price_min + b * bin_size
            hi = lo + bin_size
            vol = df.loc[(df["close"] >= lo) & (df["close"] < hi), "volume"].sum()
            vp_prices.append(round((lo + hi) / 2, 2))
            vp_vols.append(vol)
        max_vol = max(vp_vols) if max(vp_vols) > 0 else 1
        poc_price = vp_prices[vp_vols.index(max(vp_vols))]  # Point of Control

        # 캔들 + EMA9 + VWAP + 볼륨 프로파일
        from plotly.subplots import make_subplots
        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.82, 0.18],
            shared_yaxes=True,
            horizontal_spacing=0.01,
        )

        # 캔들
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["open"], high=df["high"],
            low=df["low"],   close=df["close"],
            name=symbol,
            increasing_line_color="#00D278", increasing_fillcolor="#00D278",
            decreasing_line_color="#FF4747", decreasing_fillcolor="#FF4747",
        ), row=1, col=1)

        # EMA9
        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema9"], name="EMA9",
            line=dict(color="#FF6B6B", width=1.5),
        ), row=1, col=1)

        # VWAP
        fig.add_trace(go.Scatter(
            x=df.index, y=df["vwap"], name="VWAP",
            line=dict(color="#F5A623", width=1.5, dash="dash"),
        ), row=1, col=1)

        # 볼륨 프로파일 (오른쪽 패널)
        vp_colors = ["#F5A623" if p == poc_price else "rgba(100,149,237,0.5)" for p in vp_prices]
        fig.add_trace(go.Bar(
            x=vp_vols, y=vp_prices,
            orientation="h",
            name="Volume Profile",
            marker_color=vp_colors,
            showlegend=False,
        ), row=1, col=2)

        # POC 라인
        fig.add_hline(y=poc_price, line_color="#F5A623", line_dash="dot",
                      line_width=1, row=1, col=1)

        # 보이는 구간 기준으로 Y축 범위 계산
        visible = df.tail(default_candles)
        y_min = visible["low"].min() * 0.9995
        y_max = visible["high"].max() * 1.0005
        x_end   = df.index[-1]
        x_start = df.index[max(0, len(df) - default_candles)]

        fig.update_layout(
            height=450,
            paper_bgcolor="#1C1C1E", plot_bgcolor="#1C1C1E",
            font=dict(color="#8E8E93", size=12),
            xaxis=dict(
                gridcolor="#2C2C2E", showgrid=True,
                rangeslider_visible=False,
                range=[x_start, x_end],
                fixedrange=False,
            ),
            yaxis=dict(
                gridcolor="#2C2C2E", showgrid=True,
                range=[y_min, y_max],
                fixedrange=False,
            ),
            xaxis2=dict(gridcolor="#2C2C2E", showgrid=False, showticklabels=False, fixedrange=True),
            yaxis2=dict(range=[0, max_vol * 4], fixedrange=True),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11), x=0.01, y=0.99),
            margin=dict(l=0, r=0, t=8, b=0),
            dragmode="pan",
        )
        st.plotly_chart(fig, use_container_width=True)

        # 거래량 차트
        fig_vol = go.Figure()
        fig_vol.add_trace(go.Bar(
            x=df.index, y=df["volume"],
            marker_color=["#00D278" if c >= o else "#FF4747"
                          for c, o in zip(df["close"], df["open"])],
            showlegend=False,
        ))
        fig_vol.update_layout(
            height=100,
            paper_bgcolor="#1C1C1E", plot_bgcolor="#1C1C1E",
            font=dict(color="#8E8E93", size=10),
            xaxis=dict(gridcolor="#2C2C2E", showgrid=False),
            yaxis=dict(gridcolor="#2C2C2E", showgrid=False, showticklabels=False),
            margin=dict(l=0, r=0, t=0, b=0),
        )
        st.plotly_chart(fig_vol, use_container_width=True)

    except Exception as e:
        st.error(f"차트 오류: {e}")

with col_right:
    # ── 보유 포지션 ──────────────────────────────────────────
    st.markdown('<div class="section-title">보유 포지션</div>', unsafe_allow_html=True)
    try:
        positions = get_positions()
        if positions:
            rows = []
            for p in positions:
                pnl_v = float(p.unrealized_pl)
                pct   = float(p.unrealized_plpc) * 100
                color = "#00D278" if pnl_v >= 0 else "#FF4747"
                rows.append(f"""
                <div class="sym-row">
                  <div>
                    <div class="sym-name">{p.symbol}</div>
                    <div class="sym-sub">{p.qty}주  ·  ${float(p.current_price):.2f}</div>
                  </div>
                  <div style="text-align:right">
                    <div style="font-weight:700;color:{color}">{pnl_v:+.2f}</div>
                    <div style="font-size:12px;color:{color}">{pct:+.1f}%</div>
                  </div>
                </div>""")
            st.markdown(f'<div class="toss-card">{"".join(rows)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="toss-card" style="color:#8E8E93;text-align:center;padding:32px;">보유 포지션 없음</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"포지션 오류: {e}")

    st.markdown("<div style='height:16px'></div>", unsafe_allow_html=True)

    # ── 전 종목 신호 ─────────────────────────────────────────
    st.markdown('<div class="section-title">종목 신호</div>', unsafe_allow_html=True)
    try:
        rows = []
        for sym in TRADE_SYMBOLS:
            df_sym = get_bars(sym, days=10)
            sig, _ = get_signal(df_sym)
            badge_cls = "badge-buy" if sig == Signal.BUY else "badge-sell" if sig == Signal.SELL else "badge-hold"
            label     = "매수" if sig == Signal.BUY else "매도" if sig == Signal.SELL else "홀드"
            rows.append(f"""
            <div class="sym-row">
              <div class="sym-name">{sym}</div>
              <span class="badge {badge_cls}">{label}</span>
            </div>""")
        st.markdown(f'<div class="toss-card">{"".join(rows)}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"신호 오류: {e}")

st.divider()

# ── 백테스트 결과 ──────────────────────────────────────────
st.markdown('<div class="section-title">백테스트 결과</div>', unsafe_allow_html=True)
bt_days = st.slider("백테스트 기간 (일)", 30, 180, 90, key="bt_days")

bt_cols = st.columns(len(TRADE_SYMBOLS))
for i, sym in enumerate(TRADE_SYMBOLS):
    try:
        df_bt  = get_bars(sym, days=bt_days)
        result = run_backtest(df_bt, sym)
        color  = "#00D278" if result.total_return_pct >= 0 else "#FF4747"

        with bt_cols[i]:
            st.markdown(f"""
            <div class="toss-card">
              <div style="color:#8E8E93;font-size:13px;font-weight:500">{sym}</div>
              <div style="font-size:28px;font-weight:800;color:{color};letter-spacing:-1px;margin:6px 0">
                {result.total_return_pct:+.2f}%
              </div>
              <div style="color:#8E8E93;font-size:12px">
                승률 <span style="color:#F5F5F5;font-weight:600">{result.win_rate:.0f}%</span>
                &nbsp;·&nbsp; {len(result.trades)}건
              </div>
              <div style="color:#8E8E93;font-size:12px;margin-top:4px">
                MDD <span style="color:#F5F5F5;font-weight:600">{result.mdd:.1f}%</span>
                &nbsp;·&nbsp; 샤프 <span style="color:#F5F5F5;font-weight:600">{result.sharpe:.2f}</span>
              </div>
            </div>
            """, unsafe_allow_html=True)

            if result.equity_curve:
                fig_eq = px.line(y=result.equity_curve)
                fig_eq.update_layout(
                    height=100,
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    margin=dict(l=0, r=0, t=0, b=0),
                    showlegend=False,
                    xaxis=dict(visible=False),
                    yaxis=dict(visible=False),
                )
                fig_eq.update_traces(line_color=color, line_width=2)
                st.plotly_chart(fig_eq, use_container_width=True)

    except Exception as e:
        bt_cols[i].error(f"{sym}: {e}")
