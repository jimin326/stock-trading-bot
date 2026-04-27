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
st.title("📈 Stock Trading Bot Dashboard")

# 자동 새로고침 (30초)
st.markdown("""
<meta http-equiv="refresh" content="30">
""", unsafe_allow_html=True)

# ── 계좌 현황 ──────────────────────────────────────────────
st.subheader("💰 계좌 현황")
try:
    acct = get_account()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("총 자산", f"${acct['equity']:,.2f}")
    col2.metric("현금", f"${acct['cash']:,.2f}")
    col3.metric("매수 가능", f"${acct['buying_power']:,.2f}")
    pnl = acct['pnl']
    col4.metric("오늘 손익", f"${pnl:+,.2f}", delta=f"{pnl:+.2f}")
except Exception as e:
    st.error(f"계좌 정보 오류: {e}")

st.divider()

# ── 종목 선택 & 차트 ───────────────────────────────────────
col_left, col_right = st.columns([2, 1])

with col_left:
    st.subheader("📊 가격 차트 & 지표")
    symbol = st.selectbox("종목 선택", TRADE_SYMBOLS)
    days = st.slider("기간 (일)", 5, 60, 30)

    try:
        df = get_bars(symbol, days=days)
        df = add_indicators(df)
        signal, reason = get_signal(df.iloc[:-1].copy())  # 마지막 봉 전까지로 신호 계산

        # 신호 배지
        if signal == Signal.BUY:
            st.success(f"🟢 매수 신호 | {reason}")
        elif signal == Signal.SELL:
            st.error(f"🔴 매도 신호 | {reason}")
        else:
            st.info(f"⚪ 홀드 | {reason}")

        # 캔들차트 + 이동평균
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=df.index,
            open=df["open"], high=df["high"],
            low=df["low"], close=df["close"],
            name=symbol,
        ))
        fig.add_trace(go.Scatter(x=df.index, y=df["ma_short"], name=f"MA{df['ma_short'].name}", line=dict(color="orange", width=1)))
        fig.add_trace(go.Scatter(x=df.index, y=df["ma_long"], name=f"MA Long", line=dict(color="blue", width=1)))
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_upper"], name="BB Upper", line=dict(color="gray", width=1, dash="dash")))
        fig.add_trace(go.Scatter(x=df.index, y=df["bb_lower"], name="BB Lower", line=dict(color="gray", width=1, dash="dash"),
                                  fill="tonexty", fillcolor="rgba(200,200,200,0.1)"))
        fig.update_layout(height=400, xaxis_rangeslider_visible=False, margin=dict(l=0, r=0, t=0, b=0))
        st.plotly_chart(fig, use_container_width=True)

        # RSI 차트
        fig_rsi = go.Figure()
        fig_rsi.add_trace(go.Scatter(x=df.index, y=df["rsi"], name="RSI", line=dict(color="purple")))
        fig_rsi.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="과매수(70)")
        fig_rsi.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="과매도(30)")
        fig_rsi.update_layout(height=150, margin=dict(l=0, r=0, t=0, b=0), yaxis=dict(range=[0, 100]))
        st.plotly_chart(fig_rsi, use_container_width=True)

    except Exception as e:
        st.error(f"차트 오류: {e}")

with col_right:
    # ── 보유 포지션 ──────────────────────────────────────────
    st.subheader("📋 보유 포지션")
    try:
        positions = get_positions()
        if positions:
            for p in positions:
                pnl = float(p.unrealized_pl)
                pct = float(p.unrealized_plpc) * 100
                st.metric(
                    label=f"{p.symbol} ({p.qty}주)",
                    value=f"${float(p.current_price):.2f}",
                    delta=f"${pnl:+.2f} ({pct:+.1f}%)"
                )
        else:
            st.info("보유 포지션 없음")
    except Exception as e:
        st.error(f"포지션 오류: {e}")

    st.divider()

    # ── 전 종목 신호 ─────────────────────────────────────────
    st.subheader("🔍 전 종목 신호")
    try:
        for sym in TRADE_SYMBOLS:
            df_sym = get_bars(sym, days=10)
            sig, _ = get_signal(df_sym)
            icon = "🟢" if sig == Signal.BUY else "🔴" if sig == Signal.SELL else "⚪"
            st.write(f"{icon} **{sym}** — {sig.value}")
    except Exception as e:
        st.error(f"신호 오류: {e}")

st.divider()

# ── 백테스트 결과 ──────────────────────────────────────────
st.subheader("📉 백테스트 결과")
bt_days = st.slider("백테스트 기간 (일)", 30, 180, 90, key="bt_days")

bt_cols = st.columns(len(TRADE_SYMBOLS))
for i, sym in enumerate(TRADE_SYMBOLS):
    try:
        df_bt = get_bars(sym, days=bt_days)
        result = run_backtest(df_bt, sym)

        with bt_cols[i]:
            st.metric(
                label=sym,
                value=f"{result.total_return_pct:+.2f}%",
                delta=f"승률 {result.win_rate:.0f}% | {len(result.trades)}건"
            )

            # 자산 곡선
            if result.equity_curve:
                fig_eq = px.line(y=result.equity_curve, labels={"y": "자산", "index": ""})
                fig_eq.update_layout(height=120, margin=dict(l=0, r=0, t=0, b=0), showlegend=False)
                fig_eq.update_traces(line_color="green" if result.total_return_pct >= 0 else "red")
                st.plotly_chart(fig_eq, use_container_width=True)

            st.caption(f"MDD {result.mdd:.1f}% | 샤프 {result.sharpe:.2f}")
    except Exception as e:
        bt_cols[i].error(f"{sym}: {e}")
