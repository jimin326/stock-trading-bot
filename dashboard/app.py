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
from src.backtest import run_backtest, run_scanner_backtest
from src.scanner import scan_market
from src.config import TRADE_SYMBOLS

st.set_page_config(page_title="Stock Trading Bot", layout="wide", page_icon="📈")

# ── CSS ─────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
.stApp { background-color: #0A0A0A; }
header[data-testid="stHeader"] { background: transparent; }
.toss-card {
    background: #1C1C1E; border-radius: 16px;
    padding: 20px 24px; margin-bottom: 12px; border: 1px solid #2C2C2E;
}
.badge { display:inline-block; padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; }
.badge-buy  { background:rgba(0,210,120,0.15); color:#00D278; }
.badge-sell { background:rgba(255,71,71,0.15);  color:#FF4747; }
.badge-hold { background:rgba(142,142,147,0.15);color:#8E8E93; }
.sym-row { display:flex; align-items:center; justify-content:space-between;
           padding:12px 0; border-bottom:1px solid #2C2C2E; }
.sym-row:last-child { border-bottom:none; }
.sym-name { font-weight:600; font-size:15px; color:#F5F5F5; }
.sym-sub  { font-size:12px; color:#8E8E93; margin-top:2px; }
.section-title { font-size:18px; font-weight:700; color:#F5F5F5;
                 margin-bottom:16px; letter-spacing:-0.5px; }
[data-testid="stMetric"] { background:#1C1C1E; border-radius:16px;
                            padding:16px 20px; border:1px solid #2C2C2E; }
[data-testid="stMetricLabel"] { color:#8E8E93 !important; font-size:13px !important; }
[data-testid="stMetricValue"] { font-size:22px !important; font-weight:700 !important; color:#F5F5F5 !important; }
[data-testid="stMetricDelta"] svg { display:none; }
hr { border-color:#2C2C2E !important; margin:24px 0 !important; }
.js-plotly-plot { border-radius:12px; overflow:hidden; }
.stAlert { border-radius:12px !important; border:none !important; }
div[data-testid="stMarkdownContainer"] p { margin:0; }
</style>
""", unsafe_allow_html=True)

# ── 세션 상태 초기화 ─────────────────────────────────────────
if "chart_symbol" not in st.session_state:
    st.session_state.chart_symbol = TRADE_SYMBOLS[0]
if "scan_results" not in st.session_state:
    st.session_state.scan_results = []

# ── 타이틀 ──────────────────────────────────────────────────
st.markdown('<h1 style="font-size:28px;font-weight:800;letter-spacing:-1px;color:#F5F5F5;margin-bottom:4px;">주식 트레이딩 봇</h1>', unsafe_allow_html=True)
st.markdown('<p style="color:#8E8E93;font-size:14px;margin-bottom:24px;">실시간 모니터링 대시보드</p>', unsafe_allow_html=True)

# ── 계좌 현황 ──────────────────────────────────────────────
try:
    acct = get_account()
    pnl  = acct['pnl']
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

    # 스캔 종목이 선택돼 있으면 우선 표시, 아니면 기본 종목 리스트
    scan_symbols = [r.symbol for r in st.session_state.scan_results]
    all_symbols  = list(dict.fromkeys(scan_symbols + TRADE_SYMBOLS))  # 중복 제거, 스캔 종목 먼저

    current_idx = all_symbols.index(st.session_state.chart_symbol) if st.session_state.chart_symbol in all_symbols else 0

    ctrl1, ctrl2 = st.columns([2, 1])
    selected_sym = ctrl1.selectbox("종목", all_symbols, index=current_idx, label_visibility="collapsed")
    tf_option    = ctrl2.selectbox("타임프레임", ["1Min", "5Min", "15Min", "1Hour"], index=1, label_visibility="collapsed")

    # 셀렉트박스에서 수동으로 바꾼 경우 반영
    if selected_sym != st.session_state.chart_symbol:
        st.session_state.chart_symbol = selected_sym

    symbol = st.session_state.chart_symbol

    tf_config = {"1Min": (3, 120), "5Min": (5, 100), "15Min": (10, 60), "1Hour": (30, 40)}
    load_days, default_candles = tf_config.get(tf_option, (5, 100))

    try:
        df = get_bars(symbol, days=load_days, timeframe=tf_option)
        df = add_indicators(df)
        signal, reason, confidence = get_signal(df.iloc[:-1].copy())

        if signal == Signal.BUY:
            st.success(f"매수 신호 (확신도 {confidence})  |  {reason}")
        elif signal == Signal.SELL:
            st.error(f"매도 신호 (확신도 {confidence})  |  {reason}")
        else:
            st.info(f"홀드  |  {reason}")

        # 볼륨 프로파일
        bins      = 30
        price_min = df["low"].min()
        price_max = df["high"].max()
        bin_size  = (price_max - price_min) / bins
        vp_prices, vp_vols = [], []
        for b in range(bins):
            lo  = price_min + b * bin_size
            hi  = lo + bin_size
            vol = df.loc[(df["close"] >= lo) & (df["close"] < hi), "volume"].sum()
            vp_prices.append(round((lo + hi) / 2, 2))
            vp_vols.append(vol)
        max_vol   = max(vp_vols) if max(vp_vols) > 0 else 1
        poc_price = vp_prices[vp_vols.index(max(vp_vols))]

        from plotly.subplots import make_subplots
        fig = make_subplots(rows=1, cols=2, column_widths=[0.82, 0.18],
                            shared_yaxes=True, horizontal_spacing=0.01)

        fig.add_trace(go.Candlestick(
            x=df.index, open=df["open"], high=df["high"],
            low=df["low"], close=df["close"], name=symbol,
            increasing_line_color="#00D278", increasing_fillcolor="#00D278",
            decreasing_line_color="#FF4747", decreasing_fillcolor="#FF4747",
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df.index, y=df["ema9"], name="EMA8",
            line=dict(color="#FF6B6B", width=1.5),
        ), row=1, col=1)

        fig.add_trace(go.Scatter(
            x=df.index, y=df["vwap"], name="VWAP",
            line=dict(color="#F5A623", width=1.5, dash="dash"),
        ), row=1, col=1)

        vp_colors = ["#F5A623" if p == poc_price else "rgba(100,149,237,0.5)" for p in vp_prices]
        fig.add_trace(go.Bar(
            x=vp_vols, y=vp_prices, orientation="h",
            name="Volume Profile", marker_color=vp_colors, showlegend=False,
        ), row=1, col=2)

        fig.add_hline(y=poc_price, line_color="#F5A623", line_dash="dot",
                      line_width=1, row=1, col=1)

        visible = df.tail(default_candles)
        y_min   = visible["low"].min()  * 0.9995
        y_max   = visible["high"].max() * 1.0005
        x_start = df.index[max(0, len(df) - default_candles)]
        x_end   = df.index[-1]

        fig.update_layout(
            height=450,
            paper_bgcolor="#1C1C1E", plot_bgcolor="#1C1C1E",
            font=dict(color="#8E8E93", size=12),
            xaxis=dict(gridcolor="#2C2C2E", rangeslider_visible=False,
                       range=[x_start, x_end], fixedrange=False),
            yaxis=dict(gridcolor="#2C2C2E", range=[y_min, y_max], fixedrange=False),
            xaxis2=dict(gridcolor="#2C2C2E", showgrid=False, showticklabels=False, fixedrange=True),
            yaxis2=dict(range=[0, max_vol * 4], fixedrange=True),
            legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(size=11), x=0.01, y=0.99),
            margin=dict(l=0, r=0, t=8, b=0),
            dragmode="pan",
        )
        st.plotly_chart(fig, use_container_width=True)

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
                    <div class="sym-sub">{p.qty}주 · ${float(p.current_price):.2f}</div>
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

    st.markdown('<div class="section-title">종목 신호</div>', unsafe_allow_html=True)
    try:
        rows = []
        for sym in TRADE_SYMBOLS:
            df_sym = get_bars(sym, days=5)
            sig, reason_sym, conf_sym = get_signal(df_sym)
            badge  = "badge-buy" if sig == Signal.BUY else "badge-sell" if sig == Signal.SELL else "badge-hold"
            label  = "매수" if sig == Signal.BUY else "매도" if sig == Signal.SELL else "홀드"
            conf_label = f" {conf_sym}" if sig != Signal.HOLD else ""
            rows.append(f"""
            <div class="sym-row">
              <div class="sym-name">{sym}</div>
              <span class="badge {badge}">{label}{conf_label}</span>
            </div>""")
        st.markdown(f'<div class="toss-card">{"".join(rows)}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"신호 오류: {e}")

st.divider()

# ── 종목 스캐너 ────────────────────────────────────────────
st.markdown('<div class="section-title">오늘의 스캔 종목</div>', unsafe_allow_html=True)

sc1, sc2, sc3 = st.columns([1, 1, 1])
gap_thr   = sc1.number_input("갭 기준 (%)", min_value=0.5, max_value=10.0, value=2.0, step=0.5)
vol_ratio = sc2.number_input("거래량 배수 (20일 평균)", min_value=1.0, max_value=10.0, value=1.5, step=0.5)
top_n     = sc3.number_input("최대 종목 수", min_value=1, max_value=20, value=5, step=1)

if st.button("스캔 실행", type="primary"):
    with st.spinner("스캔 중... (약 10초)"):
        try:
            results = scan_market(top_n=int(top_n), gap_threshold=gap_thr, vol_ratio_min=vol_ratio)
            st.session_state.scan_results = results
        except Exception as e:
            st.error(f"스캔 오류: {e}")

# 스캔 결과 표시
if st.session_state.scan_results:
    st.markdown("**클릭하면 위 차트에서 바로 확인할 수 있어요**", )
    cols = st.columns(len(st.session_state.scan_results))
    for i, r in enumerate(st.session_state.scan_results):
        with cols[i]:
            arrow  = "▲" if r.direction == "up" else "▼"
            color  = "#00D278" if r.direction == "up" else "#FF4747"
            active = "border:2px solid #3182F6;" if r.symbol == st.session_state.chart_symbol else ""
            st.markdown(f"""
            <div class="toss-card" style="text-align:center;padding:16px 12px;{active}">
              <div style="font-size:16px;font-weight:700;color:#F5F5F5">{r.symbol}</div>
              <div style="font-size:22px;font-weight:800;color:{color};margin:4px 0">{arrow} {r.gap_pct:+.1f}%</div>
              <div style="font-size:12px;color:#8E8E93">거래량 {r.vol_ratio:.1f}x</div>
              <div style="font-size:12px;color:#8E8E93">${r.price:.2f}</div>
            </div>
            """, unsafe_allow_html=True)
            if st.button(f"{r.symbol} 차트 보기", key=f"scan_{r.symbol}", use_container_width=True):
                st.session_state.chart_symbol = r.symbol
                st.rerun()
elif "scan_results" in st.session_state and len(st.session_state.scan_results) == 0:
    # 버튼을 눌렀는데 결과 없는 경우
    st.markdown('<div class="toss-card" style="color:#8E8E93;text-align:center;padding:24px;">조건을 만족하는 종목 없음<br><span style="font-size:12px">갭 기준이나 거래량 배수를 낮춰보세요</span></div>', unsafe_allow_html=True)

st.divider()

# ── 백테스트 결과 ──────────────────────────────────────────
st.markdown('<div class="section-title">백테스트 결과 (스캐너 기반)</div>', unsafe_allow_html=True)
st.caption("매 거래일 갭+거래량 조건을 만족한 종목만 골라 거래하는 방식으로 시뮬레이션")

bt_days = st.slider("백테스트 기간 (일)", 30, 90, 60, key="bt_days")

if st.button("백테스트 실행", type="secondary"):
    with st.spinner("데이터 수집 및 시뮬레이션 중... (약 30~60초)"):
        try:
            result = run_scanner_backtest(days=bt_days)
            st.session_state.bt_result = result
        except Exception as e:
            st.error(f"백테스트 오류: {e}")

if "bt_result" in st.session_state:
    result = st.session_state.bt_result
    color  = "#00D278" if result.total_return_pct >= 0 else "#FF4747"

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("총 수익률",  f"{result.total_return_pct:+.2f}%")
    m2.metric("MDD",       f"{result.mdd:.2f}%")
    m3.metric("샤프 비율", f"{result.sharpe:.2f}")
    m4.metric("승률",      f"{result.win_rate:.1f}%  ({len(result.trades)}건)")

    if result.equity_curve:
        fig_eq = px.line(y=result.equity_curve, title="자본 곡선")
        fig_eq.update_layout(
            height=250,
            paper_bgcolor="#1C1C1E", plot_bgcolor="#1C1C1E",
            font=dict(color="#8E8E93"),
            margin=dict(l=0, r=0, t=32, b=0),
            showlegend=False,
            xaxis=dict(visible=False),
            yaxis=dict(gridcolor="#2C2C2E"),
            title_font_color="#F5F5F5",
        )
        fig_eq.update_traces(line_color=color, line_width=2)
        st.plotly_chart(fig_eq, use_container_width=True)

    # 거래 내역 테이블
    if result.trades:
        st.markdown('<div class="section-title" style="margin-top:24px">거래 내역</div>', unsafe_allow_html=True)

        trade_data = []
        for t in result.trades:
            trade_data.append({
                "날짜":    t.entry_time.strftime("%m/%d"),
                "진입시간": t.entry_time.strftime("%H:%M"),
                "청산시간": t.exit_time.strftime("%H:%M") if t.exit_time else "-",
                "종목":    t.symbol,
                "방향":    "▲ 롱" if t.side == "long" else "▼ 숏",
                "진입가":  f"${t.entry_price:.2f}",
                "청산가":  f"${t.exit_price:.2f}" if t.exit_price else "-",
                "수익률":  f"{t.pnl_pct:+.2f}%",
                "수익금액": f"${t.pnl:+.2f}",
                "사유":    t.reason,
            })

        df_trades = pd.DataFrame(trade_data)

        # 수익률 컬럼 색상 적용
        def color_pnl(val):
            color = "#00D278" if val.startswith("+") else "#FF4747"
            return f"color: {color}; font-weight: 600"

        styled = df_trades.style.map(color_pnl, subset=["수익률", "수익금액"])
        st.dataframe(
            styled,
            use_container_width=True,
            hide_index=True,
            height=min(400, 35 + len(trade_data) * 35),
        )
