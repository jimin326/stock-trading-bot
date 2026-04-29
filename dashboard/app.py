import streamlit as st
import pandas as pd
import os
import sys
from datetime import datetime, date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.broker import get_account, get_positions
from src.data_feed import get_bars
from src.strategy import get_signal, Signal
from src.config import TRADE_SYMBOLS, PAPER_TRADING

st.set_page_config(page_title="Trading Bot Monitor", layout="wide", page_icon="📊")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');
html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
.stApp { background-color: #0A0A0A; }
header[data-testid="stHeader"] { background: transparent; }
.card {
    background: #1C1C1E; border-radius: 16px;
    padding: 20px 24px; margin-bottom: 12px; border: 1px solid #2C2C2E;
}
.badge { display:inline-block; padding:4px 12px; border-radius:20px; font-size:13px; font-weight:600; }
.badge-buy  { background:rgba(0,210,120,0.15); color:#00D278; }
.badge-sell { background:rgba(255,71,71,0.15);  color:#FF4747; }
.badge-hold { background:rgba(142,142,147,0.15);color:#8E8E93; }
.row { display:flex; align-items:center; justify-content:space-between;
       padding:12px 0; border-bottom:1px solid #2C2C2E; }
.row:last-child { border-bottom:none; }
.sec-title { font-size:16px; font-weight:700; color:#F5F5F5; margin-bottom:14px; }
[data-testid="stMetric"] { background:#1C1C1E; border-radius:16px;
                            padding:16px 20px; border:1px solid #2C2C2E; }
[data-testid="stMetricLabel"]  { color:#8E8E93 !important; font-size:13px !important; }
[data-testid="stMetricValue"]  { font-size:22px !important; font-weight:700 !important; color:#F5F5F5 !important; }
[data-testid="stMetricDelta"] svg { display:none; }
hr { border-color:#2C2C2E !important; margin:20px 0 !important; }
</style>
""", unsafe_allow_html=True)

# ── 헤더 ────────────────────────────────────────────────────
mode_badge = "🟡 페이퍼" if PAPER_TRADING else "🔴 실전"
col_title, col_refresh = st.columns([4, 1])
with col_title:
    st.markdown(f'<h1 style="font-size:26px;font-weight:800;color:#F5F5F5;margin:0">트레이딩 봇 모니터 <span style="font-size:14px;color:#8E8E93;font-weight:500">{mode_badge}</span></h1>', unsafe_allow_html=True)
    st.markdown(f'<p style="color:#8E8E93;font-size:13px;margin:4px 0 20px">마지막 갱신: {datetime.now().strftime("%H:%M:%S")}</p>', unsafe_allow_html=True)
with col_refresh:
    st.markdown("<div style='height:8px'></div>", unsafe_allow_html=True)
    auto_refresh = st.toggle("자동 새로고침 (60초)", value=False)

# ── 계좌 현황 ────────────────────────────────────────────────
try:
    acct = get_account()
    pnl  = acct["pnl"]
    pnl_color = "#00D278" if pnl >= 0 else "#FF4747"
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("총 자산",   f"${acct['equity']:,.2f}")
    c2.metric("현금",      f"${acct['cash']:,.2f}")
    c3.metric("매수 가능", f"${acct['buying_power']:,.2f}")
    c4.metric("오늘 손익", f"${pnl:+,.2f}", delta=f"{pnl:+.2f}")
except Exception as e:
    st.error(f"계좌 정보 오류: {e}")
    acct = None

st.divider()

# ── 메인: 포지션 + 신호 ──────────────────────────────────────
col_pos, col_sig = st.columns([1, 1])

with col_pos:
    st.markdown('<div class="sec-title">보유 포지션</div>', unsafe_allow_html=True)
    try:
        positions = get_positions()
        if positions:
            rows = []
            for p in positions:
                pnl_v = float(p.unrealized_pl)
                pct   = float(p.unrealized_plpc) * 100
                color = "#00D278" if pnl_v >= 0 else "#FF4747"
                side_label = "롱" if float(p.qty) > 0 else "숏"
                rows.append(f"""
                <div class="row">
                  <div>
                    <div style="font-weight:600;font-size:15px;color:#F5F5F5">{p.symbol} <span style="font-size:12px;color:#8E8E93">{side_label}</span></div>
                    <div style="font-size:12px;color:#8E8E93">{p.qty}주 · 평균가 ${float(p.avg_entry_price):.2f} · 현재 ${float(p.current_price):.2f}</div>
                  </div>
                  <div style="text-align:right">
                    <div style="font-weight:700;color:{color}">{pnl_v:+.2f}</div>
                    <div style="font-size:12px;color:{color}">{pct:+.2f}%</div>
                  </div>
                </div>""")
            st.markdown(f'<div class="card">{"".join(rows)}</div>', unsafe_allow_html=True)
        else:
            st.markdown('<div class="card" style="color:#8E8E93;text-align:center;padding:32px">포지션 없음</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"포지션 오류: {e}")

with col_sig:
    st.markdown('<div class="sec-title">종목 신호 (현재)</div>', unsafe_allow_html=True)
    try:
        rows = []
        for sym in TRADE_SYMBOLS:
            df_sym = get_bars(sym, days=5)
            sig, reason_sym, conf = get_signal(df_sym)
            badge = "badge-buy" if sig == Signal.BUY else "badge-sell" if sig == Signal.SELL else "badge-hold"
            label = "매수" if sig == Signal.BUY else "매도" if sig == Signal.SELL else "홀드"
            conf_str = f" {conf}" if sig != Signal.HOLD else ""
            short_reason = reason_sym[:30] + "…" if len(reason_sym) > 30 else reason_sym
            rows.append(f"""
            <div class="row">
              <div>
                <div style="font-weight:600;font-size:14px;color:#F5F5F5">{sym}</div>
                <div style="font-size:11px;color:#8E8E93;margin-top:2px">{short_reason}</div>
              </div>
              <span class="badge {badge}">{label}{conf_str}</span>
            </div>""")
        st.markdown(f'<div class="card">{"".join(rows)}</div>', unsafe_allow_html=True)
    except Exception as e:
        st.error(f"신호 오류: {e}")

st.divider()

# ── 실거래 내역 ──────────────────────────────────────────────
st.markdown('<div class="sec-title">실거래 내역</div>', unsafe_allow_html=True)

log_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs", "trades.csv")

col_btn, _ = st.columns([1, 5])
if col_btn.button("알파카에서 불러오기", type="primary"):
    with st.spinner("불러오는 중..."):
        try:
            from src.fetch_history import fetch_and_save
            fetch_and_save()
            st.success("완료!")
            st.rerun()
        except Exception as e:
            st.error(f"오류: {e}")

if os.path.exists(log_path):
    df_log = pd.read_csv(log_path, encoding="utf-8-sig")
    if not df_log.empty:
        pnl_series   = pd.to_numeric(df_log["수익금($)"], errors="coerce").fillna(0)
        total_profit = pnl_series.sum()
        win_count    = (pnl_series > 0).sum()
        loss_count   = (pnl_series < 0).sum()
        win_rate     = win_count / len(df_log) * 100

        # 오늘 거래만 필터
        today_str = date.today().strftime("%Y-%m-%d")
        today_mask = df_log["날짜"].str.startswith(today_str)
        today_pnl  = pnl_series[today_mask].sum()
        today_cnt  = today_mask.sum()

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("누적 수익금",  f"${total_profit:+.2f}")
        m2.metric("총 거래",      f"{len(df_log)}건")
        m3.metric("승 / 패",      f"{win_count}W / {loss_count}L")
        m4.metric("승률",         f"{win_rate:.1f}%")
        m5.metric("오늘 손익",    f"${today_pnl:+.2f} ({today_cnt}건)")

        def color_pnl(val):
            try:
                v = float(val)
                c = "#00D278" if v >= 0 else "#FF4747"
                return f"color: {c}; font-weight: 600"
            except:
                return ""

        styled = df_log.style.map(color_pnl, subset=["수익금($)", "수익률(%)"])
        st.dataframe(styled, use_container_width=True, hide_index=True,
                     height=min(500, 35 + len(df_log) * 35))
    else:
        st.markdown('<div class="card" style="color:#8E8E93;text-align:center;padding:24px">거래 내역 없음</div>', unsafe_allow_html=True)
else:
    st.markdown('<div class="card" style="color:#8E8E93;text-align:center;padding:24px">위 버튼으로 알파카에서 불러오세요</div>', unsafe_allow_html=True)

# ── 자동 새로고침 ────────────────────────────────────────────
if auto_refresh:
    import time
    time.sleep(60)
    st.rerun()
