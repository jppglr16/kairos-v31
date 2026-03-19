import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime

INSTRUMENTS={
    'NIFTY':     {'type':'index','lot':75,'token':'99926000'},
    'BANKNIFTY': {'type':'index','lot':30,'token':'99926009'},
    'SENSEX':    {'type':'index','lot':10,'token':'99919000'},
    'FINNIFTY':  {'type':'index','lot':65,'token':'99926037'},
    'MIDCPNIFTY':{'type':'index','lot':120,'token':'99926074'},
    'CRUDEOIL':  {'type':'commodity','lot':100,'token':'472790'},
    'GOLDM':     {'type':'commodity','lot':10,'token':'477904'},
    'SILVERM':   {'type':'commodity','lot':30,'token':'457533'},
    'LT':        {'type':'stock','lot':450,'token':'11483'},
    'NTPC':      {'type':'stock','lot':4500,'token':'11630'},
    'MARUTI':    {'type':'stock','lot':100,'token':'10999'},
    'BHARTIARTL':{'type':'stock','lot':950,'token':'10604'},
    'SBIN':      {'type':'stock','lot':1500,'token':'3045'},
    'TATAMOTORS':{'type':'stock','lot':1350,'token':'3456'},
    'RELIANCE':  {'type':'stock','lot':250,'token':'2885'},
    'HINDUNILVR':{'type':'stock','lot':300,'token':'1394'},
    'TCS':       {'type':'stock','lot':150,'token':'11536'},
    'TATASTEEL': {'type':'stock','lot':5500,'token':'3499'},
}
BROKERAGE=25

def get_lots(instrument,capital):
    INDEX=['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']
    COMMODITY=['CRUDEOIL','GOLDM','SILVERM']
    if instrument in INDEX or instrument in COMMODITY:
        if capital<3000:return 1
        elif capital<=50000:return 2
        elif capital<=75000:return 3
        elif capital<=100000:return 4
        else:return 2+int((capital-50001)/25000)+1
    return 1

def load_data(symbol):
    all_candles=[]
    token=INSTRUMENTS.get(symbol,{}).get('token','')
    for year in [2022,2023,2024]:
        for fname in [
            f'historical_data/{symbol}_{year}_5min.json',
            f'historical_data/{token}_{year}_5min.json'
        ]:
            if os.path.exists(fname):
                all_candles.extend(json.load(open(fname)))
                break
    return all_candles

def to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:
        df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna().reset_index(drop=True)

def load_ml(symbol):
    for f in [f'ml_models/{symbol}_model.pkl','ml_models/NIFTY_model.pkl']:
        if os.path.exists(f):
            try:return pickle.load(open(f,'rb'))
            except:pass
    return None

def get_ml_prob(symbol,df5,df15,action,atr):
    try:
        data=load_ml(symbol)
        if not data:return 0.5
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        d=c.diff();g=d.clip(lower=0).rolling(14).mean()
        ll=-d.clip(upper=0).rolling(14).mean()
        rsi=float((100-(100/(1+g/ll))).iloc[-1])
        e12=c.ewm(span=12).mean();e26=c.ewm(span=26).mean();m=e12-e26
        mh=float((m-m.ewm(span=9).mean()).iloc[-1])
        from v31_strategy import get_trend_v31
        t5=get_trend_v31(df5);t15=get_trend_v31(df15)
        vr=float(v.iloc[-1])/float(v.rolling(20).mean().iloc[-1]) if float(v.rolling(20).mean().iloc[-1])>0 else 1
        cur=float(c.iloc[-1])
        features=[
            (cur-float(c.iloc[-2]))/float(c.iloc[-2]),
            (cur-float(c.iloc[-6]))/float(c.iloc[-6]) if len(c)>6 else 0,
            (cur-float(c.iloc[-11]))/float(c.iloc[-11]) if len(c)>11 else 0,
            rsi/100,(rsi-50)/50,
            mh/atr if atr>0 else 0,1 if mh>0 else -1,
            min(vr,3)/3,1 if vr>1.5 else 0,
            t5,t15,1 if t5==t15 else 0,
            1 if cur>float(c.rolling(20).mean().iloc[-1]) else 0,
            atr/cur if cur>0 else 0,
            1 if action=='BUY' else -1,
        ]
        model=data['model'];scaler=data['scaler']
        n=model.n_features_in_
        while len(features)<n:features.append(0)
        return float(model.predict_proba(scaler.transform([features[:n]]))[0][1])
    except:return 0.5

def run_v31_backtest(capital=50000):
    from v31_strategy import (get_market_regime,detect_liquidity_sweep_v31,
                               detect_fvg_v31,detect_ob_v31,get_trend_v31)
    from v30_rr_filter import find_tight_sl,find_best_target

    print(f'\n{"="*65}')
    print(f'  KAIROS V31 BACKTEST - GAMMA+SMC+ML')
    print(f'  Liquidity Sweep + FVG/OB + Trend + RR Filter')
    print(f'  Capital: Rs.{capital:,.0f} | Min RR: 1:3')
    print(f'{"="*65}')

    all_monthly={}
    all_results=[]

    for symbol in INSTRUMENTS:
        print(f'\n[V31] {symbol}...',end=' ',flush=True)
        candles=load_data(symbol)
        if not candles:print('No data');continue
        df=to_df(candles)
        if df is None or len(df)<200:print('Skip');continue

        lot=INSTRUMENTS[symbol]['lot']
        current_capital=capital
        wins=0;losses=0
        in_trade=False
        entry_p=0;sig_action=''
        sl_pts=0;t1_pts=0;t2_pts=0
        entry_idx=0;current_lots=1;t1_hit=False
        daily_losses=0;last_date=None;daily_trades=0
        peak=capital;max_dd=0
        monthly_pnl={}
        trade_month=''
        liq_blocked=0;fvg_blocked=0
        rr_blocked=0;ml_blocked=0;trend_blocked=0

        for i in range(100,len(df)-30,2):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-300):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                hour=int(str(df5['time'].iloc[-1])[11:13])
                # Best sessions only
                if hour not in [10,11,13,14]:continue
                curr_date=str(df5['time'].iloc[-1])[:10]
                month_key=curr_date[:7]
                if curr_date!=last_date:
                    daily_losses=0;daily_trades=0;last_date=curr_date
            except:continue

            if daily_losses>=3:continue
            if daily_trades>=4:continue

            lot_count=get_lots(symbol,current_capital)

            if not in_trade:
                try:
                    c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
                    atr=float((h-l).tail(14).mean())
                    if atr<=0:continue

                    # Volatility filter
                    avg_atr=float((h-l).rolling(20).mean().iloc[-1])
                    if atr<avg_atr*0.7:continue

                    # Market regime
                    regime,_=get_market_regime(df5,df15,df_daily)
                    if regime=='VOLATILE':continue

                    # Determine action from regime
                    if regime=='TRENDING_UP':action='BUY'
                    elif regime=='TRENDING_DOWN':action='SELL'
                    else:
                        # Try both in ranging
                        has_b,_,_=detect_liquidity_sweep_v31(df5,'BUY',atr)
                        has_s,_,_=detect_liquidity_sweep_v31(df5,'SELL',atr)
                        if has_b:action='BUY'
                        elif has_s:action='SELL'
                        else:continue

                    # Trend alignment check
                    t5=get_trend_v31(df5)
                    t15=get_trend_v31(df15)
                    td=get_trend_v31(df_daily)
                    if action=='BUY' and t5==-1 and t15==-1 and td==-1:
                        trend_blocked+=1;continue
                    if action=='SELL' and t5==1 and t15==1 and td==1:
                        trend_blocked+=1;continue

                    # New adaptive scoring
                    from v31_scoring import calc_v31_score
                    from v31_strategy import get_wyckoff
                    wy=get_wyckoff(df15)
                    v31_score,components,has_liq,has_fvg=calc_v31_score(
                        df5,df15,action,regime,wy,atr)

                    # Adaptive thresholds
                    if v31_score<15:
                        liq_blocked+=1;continue
                    # Score 18-21: need high ML confidence
                    need_high_ml=(15<=v31_score<=20)
                    if not has_liq and not components.get("bos_choch",0):
                        liq_blocked+=1;continue
                    if not has_fvg and not components.get("ote",0):
                        fvg_blocked+=1;continue

                    # RR Filter
                    is_trending=regime in ['TRENDING_UP','TRENDING_DOWN']
                    sl_type,raw_sl,sl_price=find_tight_sl(df5,df15,action,atr)
                    if raw_sl<atr*0.75:raw_sl=atr*0.75
                    if raw_sl>atr*2.0:rr_blocked+=1;continue

                    tgt_type,target,rr=find_best_target(
                        df5,df15,action,float(c.iloc[-1]),raw_sl,atr,is_trending)
                    if rr<3.0:rr_blocked+=1;continue

                    # ML filter
                    ml_prob=get_ml_prob(symbol,df5,df15,action,atr)
                    # Adaptive ML threshold
                    if need_high_ml and ml_prob<0.70:ml_blocked+=1;continue
                    elif not need_high_ml and ml_prob<0.35:ml_blocked+=1;continue

                    # Enter trade
                    entry_p=float(c.iloc[-1])
                    in_trade=True;sig_action=action
                    sl_pts=raw_sl
                    t1_pts=raw_sl*1.5
                    t2_pts=raw_sl*rr
                    entry_idx=i;current_lots=lot_count
                    t1_hit=False;trade_month=month_key

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''
                qty=current_lots*lot

                if sig_action=='BUY':
                    if not t1_hit and row['high']>=entry_p+t1_pts:
                        t1_hit=True;sl_pts=0
                    if row['low']<=entry_p-sl_pts and not t1_hit:
                        pnl=-sl_pts*qty;reason='SL'
                    elif row['high']>=entry_p+t2_pts:
                        pnl=t2_pts*qty;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_p)*qty;reason='TO'
                else:
                    if not t1_hit and row['low']<=entry_p-t1_pts:
                        t1_hit=True;sl_pts=0
                    if row['high']>=entry_p+sl_pts and not t1_hit:
                        pnl=-sl_pts*qty;reason='SL'
                    elif row['low']<=entry_p-t2_pts:
                        pnl=t2_pts*qty;reason='T2'
                    elif bars>=30:
                        pnl=(entry_p-row['close'])*qty;reason='TO'

                if reason:
                    net=pnl-BROKERAGE
                    current_capital+=net
                    if pnl<0:daily_losses+=1;losses+=1
                    else:wins+=1
                    daily_trades+=1
                    if current_capital>peak:peak=current_capital
                    dd=((peak-current_capital)/peak)*100
                    if dd>max_dd:max_dd=dd
                    if trade_month not in monthly_pnl:
                        monthly_pnl[trade_month]={'pnl':0,'trades':0,'wins':0}
                    monthly_pnl[trade_month]['pnl']+=net
                    monthly_pnl[trade_month]['trades']+=1
                    if net>0:monthly_pnl[trade_month]['wins']+=1
                    in_trade=False;t1_hit=False

        total=wins+losses
        wr=round(wins/total*100,1) if total>0 else 0
        ret=round((current_capital-capital)/capital*100,1)
        all_monthly[symbol]=monthly_pnl
        all_results.append({
            'symbol':symbol,'type':INSTRUMENTS[symbol]['type'],
            'total_trades':total,'wins':wins,'losses':losses,
            'win_rate':wr,'total_return':ret,
            'max_drawdown':round(max_dd,1),
            'final_capital':round(current_capital,2),
            'liq_blocked':liq_blocked,'fvg_blocked':fvg_blocked,
            'rr_blocked':rr_blocked,'ml_blocked':ml_blocked,
            'monthly_pnl':monthly_pnl
        })
        print(f'WR:{wr}% Return:{ret}% Trades:{total} '
              f'Liq:{liq_blocked} FVG:{fvg_blocked} '
              f'RR:{rr_blocked} ML:{ml_blocked}')

    # Monthly report
    months=sorted(set(m for d in all_monthly.values() for m in d.keys()))
    print(f'\n{"="*65}')
    print(f'  MONTHLY RETURNS - V31 KAIROS')
    print(f'{"="*65}')

    for symbol in INSTRUMENTS:
        data=all_monthly.get(symbol,{})
        if not data:continue
        print(f'\n--- {symbol} ---')
        print(f'{"Month":<10}{"PnL":>12}{"Trades":>8}{"WR%":>6}{"Capital":>14}')
        print('-'*52)
        running=capital;y_totals={}
        for month in months:
            mdata=data.get(month)
            if not mdata:continue
            pnl=mdata['pnl'];trades=mdata['trades']
            mwins=mdata['wins']
            mwr=round(mwins/trades*100) if trades>0 else 0
            running+=pnl;year=month[:4]
            y_totals[year]=y_totals.get(year,0)+pnl
            sign='+' if pnl>=0 else ''
            print(f'{month:<10}{sign}{pnl:>10.0f}  {trades:>5}  {mwr:>4}%  Rs.{running:>10,.0f}')
            next_idx=months.index(month)+1
            if next_idx>=len(months) or months[next_idx][:4]!=year:
                ytot=y_totals[year];sign='+' if ytot>=0 else ''
                print(f'{"─"*52}')
                print(f'{year+" TOTAL":<10}{sign}{ytot:>10.0f}  ({ytot/capital*100:.1f}% ROI)')
                print(f'{"─"*52}')
        r=next((x for x in all_results if x['symbol']==symbol),{})
        print(f'3YR: WR={r.get("win_rate",0)}% Trades={r.get("total_trades",0)} Return={r.get("total_return",0)}%')

    # Combined
    print(f'\n{"="*65}')
    print(f'  COMBINED SUMMARY')
    print(f'{"="*65}')
    grand=0;y_grand={}
    for month in months:
        mt=sum(all_monthly.get(s,{}).get(month,{}).get('pnl',0) for s in INSTRUMENTS)
        grand+=mt;year=month[:4]
        y_grand[year]=y_grand.get(year,0)+mt
        next_idx=months.index(month)+1
        if next_idx>=len(months) or months[next_idx][:4]!=year:
            yt=y_grand[year];sign='+' if yt>=0 else ''
            print(f'{year}: {sign}Rs.{yt:,.0f} ({yt/capital*100:.1f}% ROI)')

    print(f'\nGRAND TOTAL: Rs.{grand:>+,.0f}')
    print(f'3YR ROI: {grand/capital*100:.1f}%')
    print(f'Monthly avg: Rs.{grand/36:>+,.0f}')

    all_results.sort(key=lambda x:-x['total_return'])
    print(f'\nTOP 5:')
    for r in all_results[:5]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}% Trades:{r["total_trades"]}')
    print(f'\nBOTTOM 3:')
    for r in all_results[-3:]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    os.makedirs('backtest_results',exist_ok=True)
    json.dump(all_results,open('backtest_results/v31_backtest.json','w'),indent=2)
    print(f'\nSaved to backtest_results/v31_backtest.json')
    return all_monthly,all_results

if __name__=='__main__':
    run_v31_backtest(capital=50000)
