import json,pandas as pd,numpy as np
from margin_rules import can_sell,get_lots

candles=json.load(open('historical_data/NIFTY_2024_5min.json'))
df=pd.DataFrame(candles,columns=['time','open','high','low','close','volume'])
for c in ['open','high','low','close','volume']:df[c]=pd.to_numeric(df[c],errors='coerce')
df=df.dropna().reset_index(drop=True)
print(f'NIFTY 2024: {len(df)} candles')

from v31_scoring import calc_v31_score
from v31_strategy import get_market_regime,get_trend_v31,detect_liquidity_sweep_v31
from v30_final_backtest import get_wyckoff
from v30_rr_filter import find_tight_sl,find_best_target

def get_premium(atr):
    return max(60,min(350,round(atr*0.9)))

def get_option_sl_tgt(prem,score):
    sl=prem*0.40
    tgt=prem*1.5 if score>=22 else prem*1.0 if score>=18 else prem*0.75
    return sl,tgt

capital=50000;lot=75
wins=0;losses=0;breakevens=0
monthly={}

for i in range(100,len(df)-40,20):
    df5=df.iloc[i-60:i].copy()
    df15=df.iloc[max(0,i-180):i:3].copy()
    df_daily=df.iloc[max(0,i-300):i:12].copy()
    future36=df.iloc[i:min(i+36,len(df))].copy()
    if len(df5)<30 or len(future36)<5:continue
    try:
        hour=int(str(df5['time'].iloc[-1])[11:13])
        if hour not in [9,10,11,12,13,14]:continue
        curr_date=str(df5['time'].iloc[-1])[:10]
        mkey=curr_date[:7]
        if mkey not in monthly:
            monthly[mkey]={'buy_pnl':0,'buy_t':0,'buy_w':0,'be':0}
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        atr=float((h-l).tail(14).mean())
        cur=float(c.iloc[-1])
        if atr<5:continue
        vol_avg=float(v.rolling(20).mean().iloc[-1])
        vol_ok=vol_avg>0 and float(v.iloc[-1])>=vol_avg*1.3
        regime,_=get_market_regime(df5,df15,df_daily)
        if regime not in ['TRENDING_UP','TRENDING_DOWN']:continue
        action='BUY' if regime=='TRENDING_UP' else 'SELL'
        td=get_trend_v31(df_daily)
        if action=='BUY' and td==-1:continue
        if action=='SELL' and td==1:continue
        swept,liq_type,_=detect_liquidity_sweep_v31(df5,action,atr)
        if not swept:continue
        wy=get_wyckoff(df15)
        score,_,_,_=calc_v31_score(df5,df15,action,regime,wy,atr)
        if score<15:continue
        if vol_ok:score+=2
        sl_type,raw_sl,_=find_tight_sl(df5,df15,action,atr)
        if raw_sl<atr*0.75:raw_sl=atr*0.75
        if raw_sl>atr*2:continue
        prem=get_premium(atr)
        o_sl,o_tgt=get_option_sl_tgt(prem,score)
        ratio=3.0 if score>=22 else 2.0 if score>=18 else 1.5
        lots=get_lots(capital)
        qty=lots*lot;hqty=max(1,qty//2)
        entry=cur;t1=raw_sl;t1_5=raw_sl*1.5;t2=raw_sl*ratio
        t1_hit=False;partial_done=False
        pnl=0;partial_pnl=0;reason='TO';sl_cur=raw_sl
        for _,row in future36.iterrows():
            if action=='BUY':
                if not t1_hit and row['high']>=entry+t1:t1_hit=True;sl_cur=0
                if not partial_done and row['high']>=entry+t1_5:
                    partial_done=True;partial_pnl=o_tgt*0.5*hqty
                if row['low']<=entry-sl_cur and not t1_hit:
                    pnl=-o_sl*qty;reason='SL';break
                elif row['high']>=entry+t2:
                    pnl=o_tgt*hqty+(o_tgt*hqty if not partial_done else 0);reason='T2';break
            else:
                if not t1_hit and row['low']<=entry-t1:t1_hit=True;sl_cur=0
                if not partial_done and row['low']<=entry-t1_5:
                    partial_done=True;partial_pnl=o_tgt*0.5*hqty
                if row['high']>=entry+sl_cur and not t1_hit:
                    pnl=-o_sl*qty;reason='SL';break
                elif row['low']<=entry-t2:
                    pnl=o_tgt*hqty+(o_tgt*hqty if not partial_done else 0);reason='T2';break
        if reason=='TO':
            chg=abs(float(future36['close'].iloc[-1])-entry)/entry
            pnl=prem*chg*qty*0.3
        total_pnl=pnl+partial_pnl
        net=total_pnl-34;capital+=net
        monthly[mkey]['buy_pnl']+=net
        monthly[mkey]['buy_t']+=1
        if net>0:wins+=1;monthly[mkey]['buy_w']+=1
        elif t1_hit and abs(net)<50:breakevens+=1;monthly[mkey]['be']+=1
        else:losses+=1
    except:continue

buy_total=wins+losses+breakevens
wr=round(wins/buy_total*100,1) if buy_total>0 else 0
ret=round((capital-50000)/50000*100,1)
print(f'\n{"="*60}')
print(f'  NIFTY 2024 REALISTIC BACKTEST')
print(f'{"="*60}')
print(f'Trades:{buy_total} WR:{wr}% BE:{breakevens} Return:{ret}%')
print(f'Final: Rs.{capital:,.0f}')
print(f'\n{"Month":<10}{"PnL":>12}{"Trades":>8}{"WR%":>6}{"BE":>4}{"Capital":>12}')
print('-'*55)
running=50000
for m,d in sorted(monthly.items()):
    if d['buy_t']==0:continue
    running+=d['buy_pnl']
    mwr=round(d['buy_w']/d['buy_t']*100) if d['buy_t']>0 else 0
    sign='+' if d['buy_pnl']>=0 else ''
    bar='✅' if d['buy_pnl']>0 else '❌'
    print(f'{m:<10}{sign}{d["buy_pnl"]:>10,.0f}  {d["buy_t"]:>5}  {mwr:>4}%  {d["be"]:>2}  Rs.{running:>9,.0f} {bar}')
print(f'\nTotal: Rs.{capital-50000:>+,.0f} ({ret}%)')
