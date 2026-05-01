from src.backtest import run_scanner_backtest
import numpy as np
from collections import Counter

result = run_scanner_backtest(days=120, side_filter='both', strict_exit=False, cooldown_bars=2, use_vp=True)
trades = result.trades

longs  = [t for t in trades if t.side == 'long']
shorts = [t for t in trades if t.side == 'short']

def stats(ts):
    wins   = [t for t in ts if t.pnl > 0]
    losses = [t for t in ts if t.pnl <= 0]
    wr     = len(wins)/len(ts)*100
    avg_win  = np.mean([t.pnl for t in wins])   if wins   else 0
    avg_loss = abs(np.mean([t.pnl for t in losses])) if losses else 0
    payoff   = avg_win / avg_loss if avg_loss > 0 else 0
    pf       = sum(t.pnl for t in wins) / abs(sum(t.pnl for t in losses)) if losses and sum(t.pnl for t in losses)!=0 else 0
    total    = sum(t.pnl for t in ts)
    avg_pct  = np.mean([t.pnl_pct for t in ts])
    ret      = np.array([t.pnl_pct for t in ts])
    sharpe   = np.mean(ret)/np.std(ret)*np.sqrt(252) if np.std(ret)>0 else 0
    streak_l = max_l = 0
    for t in ts:
        if t.pnl <= 0: streak_l+=1; max_l=max(max_l,streak_l)
        else: streak_l=0
    return dict(n=len(ts), wins=len(wins), losses=len(losses), wr=wr,
                payoff=payoff, pf=pf, total=total, avg_pct=avg_pct,
                avg_win=avg_win, avg_loss=avg_loss, sharpe=sharpe, mcl=max_l)

def analyze(ts, label):
    d = stats(ts)
    reasons = Counter(t.reason for t in ts)
    print(f'\n  -- {label} ({d["n"]}건) --')
    print(f'  총 손익       : ${d["total"]:>+8.2f}')
    print(f'  승률          : {d["wr"]:.1f}%  ({d["wins"]}승 / {d["losses"]}패)')
    print(f'  손익비        : {d["payoff"]:.2f}')
    print(f'  프로핏팩터    : {d["pf"]:.2f}')
    print(f'  평균 수익%    : {d["avg_pct"]:+.2f}%')
    print(f'  평균 수익(승) : ${d["avg_win"]:.2f}')
    print(f'  평균 손실(패) : ${d["avg_loss"]:.2f}')
    print(f'  샤프          : {d["sharpe"]:.2f}')
    print(f'  최대연속손실  : {d["mcl"]}회')
    print(f'  확신도별:')
    for c in [1,2,3]:
        ct = [t for t in ts if t.confidence==c]
        if ct:
            cw = [t for t in ct if t.pnl>0]
            print(f'    {c}등급: {len(ct):3}건  승률 {len(cw)/len(ct)*100:.1f}%  손익 ${sum(t.pnl for t in ct):+.2f}')
    print(f'  청산 사유:')
    for r,cnt in reasons.most_common():
        pnls = [t.pnl for t in ts if t.reason==r]
        print(f'    {r:16s}: {cnt:3}건  평균 ${np.mean(pnls):+.2f}')

print('='*55)
print('  롱 vs 숏 비교 (2026 YTD, 82거래일)')
print('='*55)
analyze(longs,  'LONG  (매수)')
analyze(shorts, 'SHORT (공매도)')

print()
print('='*60)
print('  비교 요약표')
print('='*60)
L = stats(longs)
S = stats(shorts)
A = stats(trades)

rows = [
    ('거래 수',      f'{L["n"]}건',        f'{S["n"]}건',        f'{A["n"]}건'),
    ('승률',         f'{L["wr"]:.1f}%',    f'{S["wr"]:.1f}%',    f'{A["wr"]:.1f}%'),
    ('손익비',       f'{L["payoff"]:.2f}', f'{S["payoff"]:.2f}', f'{A["payoff"]:.2f}'),
    ('프로핏팩터',   f'{L["pf"]:.2f}',     f'{S["pf"]:.2f}',     f'{A["pf"]:.2f}'),
    ('평균수익%',    f'{L["avg_pct"]:+.2f}%', f'{S["avg_pct"]:+.2f}%', f'{A["avg_pct"]:+.2f}%'),
    ('총손익',       f'${L["total"]:+.2f}', f'${S["total"]:+.2f}', f'${A["total"]:+.2f}'),
    ('샤프',         f'{L["sharpe"]:.2f}', f'{S["sharpe"]:.2f}', f'{A["sharpe"]:.2f}'),
    ('최대연속손실', f'{L["mcl"]}회',       f'{S["mcl"]}회',       f'{A["mcl"]}회'),
]

print(f'  {"지표":14s}  {"LONG":>12}  {"SHORT":>12}  {"전체":>12}')
print(f'  {"-"*54}')
for label, lv, sv, av in rows:
    print(f'  {label:14s}  {lv:>12}  {sv:>12}  {av:>12}')
