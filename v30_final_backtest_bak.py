import json,os,pickle
from v30_rr_filter import apply_rr_filter
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

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
        else:
            extra=int((capital-50001)/25000)+1
            return 2+extra
    return 1

def load_data(symbol):
    all_candles=[]
    info=INSTRUMENTS.get(symbol,{})
    token=info.get('token','')
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

def calc_rsi(s,p=14):
    d=s.diff()
    g=d.clip(lower=0).rolling(p).mean()
    l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def calc_macd(s):
    e12=s.ewm(span=12).mean()
    e26=s.ewm(span=26).mean()
    m=e12-e26
    return m,m.ewm(span=9).mean()

def get_trend(df):
    try:
        c=df['close']
        s20=c.rolling(20).mean().iloc[-1]
        s50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else s20
        cur=c.iloc[-1]
        if cur>s20 and s20>s50:return 1
        elif cur<s20 and s20<s50:return -1
        return 0
    except:return 0

def get_wyckoff(df):
    try:
        c=df['close'].values
        v=df['volume'].values
        h=df['high'].values
        l=df['low'].values
        if len(c)<60:return 'UNKNOWN'
        rv=v[-20:].mean();ov=v[-60:-20].mean()
        vol_dec=rv<ov*0.8
        s20=pd.Series(c).rolling(20).mean().values
        s50=pd.Series(c).rolling(50).mean().values
        above=c[-1]>s50[-1]
        con=(h[-20:].max()-l[-20:].min())<(h[-60:-20].max()-l[-60:-20].min())*0.6
        spring=l[-20:].min()<l[-60:-20].min() and c[-1]>l[-60:-20].min()
        upthrust=h[-20:].max()>h[-60:-20].max() and c[-1]<h[-60:-20].max()
        if con and not above and (vol_dec or spring):return 'ACCUM'
        elif c[-1]>s20[-1] and s20[-1]>s50[-1]:return 'MARKUP'
        elif con and above and (vol_dec or upthrust):return 'DIST'
        elif c[-1]<s20[-1] and s20[-1]<s50[-1]:return 'MARK'
        return 'TRANS'
    except:return 'UNKNOWN'

def get_ict_score(df5,df15,action):
    try:
        score=0
        h=df5['high'];l=df5['low'];c=df5['close']
        # Kill zone
        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if 9<=hour<=11:score+=5
            elif 13<=hour<=15:score+=4
        except:pass
        # OTE zone
        sh=h.tail(20).max();sl=l.tail(20).min()
        fr=sh-sl
        cur=c.iloc[-1]
        if action=='BUY':
            ote_low=sh-(fr*0.79);ote_high=sh-(fr*0.62)
            if ote_low<=cur<=ote_high:score+=4
            if cur<(sh+sl)/2:score+=3  # Discount
        else:
            ote_low=sl+(fr*0.62);ote_high=sl+(fr*0.79)
            if ote_low<=cur<=ote_high:score+=4
            if cur>(sh+sl)/2:score+=3  # Premium
        # VWAP
        v=df5['volume']
        vwap=(c*v).sum()/v.sum() if v.sum()>0 else c.mean()
        if action=='BUY' and cur>vwap:score+=2
        elif action=='SELL' and cur<vwap:score+=2
        return score
    except:return 0

def get_fvg(df5,action):
    try:
        for i in range(len(df5)-3,len(df5)-1):
            if i<2:continue
            p2=df5.iloc[i-2];cur=df5.iloc[i]
            if action=='BUY' and cur['low']>p2['high']:return True
            elif action=='SELL' and cur['high']<p2['low']:return True
        return False
    except:return False

def get_liq(df5,action):
    try:
        h=df5['high'];l=df5['low'];c=df5['close']
        rh=h.iloc[-10:-1].max();rl=l.iloc[-10:-1].min()
        last=df5.iloc[-1]
        if action=='BUY' and last['low']<rl and last['close']>rl:return True
        if action=='SELL' and last['high']>rh and last['close']<rh:return True
        return False
    except:return False

def calc_kairos(df5,df15,action,trend15,wyckoff):
    score=0
    # ICT
    score+=get_ict_score(df5,df15,action)
    # Alignment
    trend5=get_trend(df5)
    if action=='BUY':
        align=sum([trend5==1,trend15==1])
    else:
        align=sum([trend5==-1,trend15==-1])
    score+=align*2
    # FVG
    if get_fvg(df5,action):score+=4
    # Liquidity
    if get_liq(df5,action):score+=3
    # Wyckoff
    if action=='BUY':
        if wyckoff=='ACCUM':score+=5
        elif wyckoff=='MARKUP':score+=4
        elif wyckoff in ['DIST','MARK']:score-=3
    else:
        if wyckoff=='DIST':score+=5
        elif wyckoff=='MARK':score+=4
        elif wyckoff in ['ACCUM','MARKUP']:score-=3
    return score

def load_ml_model(symbol):
    for f in [f'ml_models/{symbol}_model.pkl','ml_models/NIFTY_model.pkl']:
        if os.path.exists(f):
            try:return pickle.load(open(f,'rb'))
            except:pass
    return None

def get_ml_prob(symbol,df5,df15,action,atr):
    try:
        data=load_ml_model(symbol)
        if not data:return 0.5
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        rsi=calc_rsi(c).iloc[-1]
        macd,sig=calc_macd(c)
        mh=(macd-sig).iloc[-1]
        t15=get_trend(df15)
        t5=get_trend(df5)
        vr=v.iloc[-1]/v.rolling(20).mean().iloc[-1] if v.rolling(20).mean().iloc[-1]>0 else 1
        features=[
            (c.iloc[-1]-c.iloc[-2])/c.iloc[-2],
            (c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0,
            (c.iloc[-1]-c.iloc[-11])/c.iloc[-11] if len(c)>11 else 0,
            rsi/100,(rsi-50)/50,
            mh/atr if atr>0 else 0,1 if mh>0 else -1,
            min(vr,3)/3,1 if vr>1.5 else 0,
            t5,t15,get_trend(df15.iloc[::3] if len(df15)>30 else df15),
            1 if (action=='BUY' and t15==1) or (action=='SELL' and t15==-1) else 0,
            1 if c.iloc[-1]>c.rolling(20).mean().iloc[-1] else 0,
            atr/c.iloc[-1] if c.iloc[-1]>0 else 0,
            1 if get_fvg(df5,action) else 0,
            1 if get_liq(df5,action) else 0,
            1 if action=='BUY' else -1,
        ]
        model=data['model'];scaler=data['scaler']
        n=model.n_features_in_
        while len(features)<n:features.append(0)
        features=features[:n]
        return model.predict_proba(scaler.transform([features]))[0][1]
    except:return 0.5

def get_sl_from_mining(symbol):
    try:
        if os.path.exists('failure_corrections.json'):
            d=json.load(open('failure_corrections.json'))
            sugg=d.get('parameter_suggestions',{}).get(symbol,{})
            return sugg.get('sl_multiplier',1.88)
    except:pass
    return 1.88

def run_backtest(symbol,capital=50000):
    candles=load_data(symbol)
    if not candles:
        print(f'[BT] No data: {symbol}')
        return None
    df=to_df(candles)
    if df is None or len(df)<200:return None

    lot=INSTRUMENTS[symbol]['lot']
    sl_mult=get_sl_from_mining(symbol)
    AVOID_HOURS=[9,10,15]
    MIN_KAIROS=15

    current_capital=capital
    wins=0;losses=0
    in_trade=False
    entry=0;action=''
    sl=0;t1=0;t2=0
    entry_idx=0;current_lots=1
    t1_hit=False
    daily_losses=0;last_date=None
    daily_trades=0
    peak=capital;max_dd=0
    yearly={}

    for i in range(100,len(df)-30,2):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            # Avoid bad hours
            if hour in AVOID_HOURS:continue
            if hour<9 or hour>14:continue
        except:continue

        try:
            curr_date=str(df5['time'].iloc[-1])[:10]
            year=curr_date[:4]
            if curr_date!=last_date:
                daily_losses=0;daily_trades=0
                last_date=curr_date
        except:year='2022'

        if daily_losses>=3:continue
        if daily_trades>=4:continue

        lot_count=get_lots(symbol,current_capital)
        risk_amt=min(current_capital*0.05,2500*lot_count)

        if not in_trade:
            try:
                c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
                rsi=calc_rsi(c).iloc[-1]
                macd,sig=calc_macd(c)
                mh=(macd-sig).iloc[-1]
                atr=(h-l).tail(14).mean()
                if atr<=0:continue

                trend_d=get_trend(df_daily)
                trend15=get_trend(df15)
                trend5=get_trend(df5)
                wy=get_wyckoff(df15)

                # Signal generation
                buy_score=0;sell_score=0
                if trend_d==1:buy_score+=3
                elif trend_d==-1:sell_score+=3
                if trend15==1:buy_score+=2
                elif trend15==-1:sell_score+=2
                if trend5==1:buy_score+=1
                elif trend5==-1:sell_score+=1
                if rsi<45:buy_score+=2
                elif rsi>55:sell_score+=2
                if mh>0:buy_score+=1
                elif mh<0:sell_score+=1
                vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
                if vol_surge:
                    if mh>0:buy_score+=2
                    else:sell_score+=2

                if buy_score>=5 and buy_score>sell_score:sig_action='BUY'
                elif sell_score>=5 and sell_score>buy_score:sig_action='SELL'
                else:continue

                # Trend filter
                if trend_d==1 and sig_action=='SELL':continue
                if trend_d==-1 and sig_action=='BUY':continue

                # Sideways filter
                market='SIDEWAYS'
                if abs(trend15)==1:market='TRENDING'
                if market=='SIDEWAYS' and not get_fvg(df5,sig_action):continue

                # Wyckoff filter
                if sig_action=='BUY' and wy in ['DIST','MARK']:continue
                if sig_action=='SELL' and wy in ['ACCUM','MARKUP']:continue

                # KAIROS score
                kairos=calc_kairos(df5,df15,sig_action,trend15,wy)
                if kairos<MIN_KAIROS:continue

                # RSI filter
                if sig_action=='BUY' and rsi>70:continue
                if sig_action=='SELL' and rsi<30:continue

                # RR Filter - tight SL and 1:3+ target
                rr_ok,rr_sl,rr_target,rr_ratio,rr_quality,rr_issues=apply_rr_filter(df5,df15,sig_action,atr,symbol,current_capital)
                if not rr_ok:continue
                sl_pts=rr_sl
                t1_pts=sl_pts*1.5
                t2_pts=sl_pts*2.5
                    # ML filter
                ml_prob=get_ml_prob(symbol,df5,df15,sig_action,atr)
                if ml_prob<0.35:continue

                # Calculate SL using mined multiplier
                sl_pts=atr*sl_mult
                t1_pts=sl_pts*1.5
                t2_pts=sl_pts*2.5

                entry_price=c.iloc[-1]
                in_trade=True;action=sig_action
                sl=sl_pts;t1=t1_pts;t2=t2_pts
                entry=entry_price
                entry_idx=i
                current_lots=lot_count
                t1_hit=False

            except:continue
        else:
            row=df.iloc[i]
            bars=i-entry_idx
            pnl=0;reason=''
            qty=current_lots*lot

            if action=='BUY':
                if not t1_hit and row['high']>=entry+t1:
                    t1_hit=True;sl=0  # Move SL to breakeven
                if row['low']<=entry-sl and not t1_hit:
                    pnl=-sl*qty;reason='SL'
                elif row['high']>=entry+t2:
                    pnl=t2*qty;reason='T2'
                elif bars>=30:
                    pnl=(row['close']-entry)*qty;reason='TO'
            else:
                if not t1_hit and row['low']<=entry-t1:
                    t1_hit=True;sl=0
                if row['high']>=entry+sl and not t1_hit:
                    pnl=-sl*qty;reason='SL'
                elif row['low']<=entry-t2:
                    pnl=t2*qty;reason='T2'
                elif bars>=30:
                    pnl=(entry-row['close'])*qty;reason='TO'

            if reason:
                net=pnl-BROKERAGE
                current_capital+=net
                if pnl<0:daily_losses+=1;losses+=1
                else:wins+=1
                daily_trades+=1
                if current_capital>peak:peak=current_capital
                dd=((peak-current_capital)/peak)*100
                if dd>max_dd:max_dd=dd
                yearly[year]=yearly.get(year,0)+net
                in_trade=False;t1_hit=False

    total=wins+losses
    if total==0:return None
    wr=round(wins/total*100,1)
    ret=round((current_capital-capital)/capital*100,1)

    return {
        'symbol':symbol,
        'type':INSTRUMENTS[symbol]['type'],
        'lots_used':f'Dynamic ({get_lots(symbol,capital)} at start)',
        'sl_multiplier':sl_mult,
        'total_trades':total,
        'wins':wins,'losses':losses,
        'win_rate':wr,
        'total_pnl':round(current_capital-capital,2),
        'total_return':ret,
        'max_drawdown':round(max_dd,1),
        'final_capital':round(current_capital,2),
        'yearly_pnl':yearly
    }

def run_all_backtests(capital=50000):
    print(f'\n{"="*65}')
    print(f'  KAIROS V30 FINAL BACKTEST - ALL 18 INSTRUMENTS')
    print(f'  Capital: Rs.{capital:,.0f} | Brokerage: Rs.{BROKERAGE}')
    print(f'  SL: Mined multiplier | Avoid: 9AM,10AM,3PM')
    print(f'  Filters: KAIROS+Wyckoff+ML+ICT+VP+Brain')
    print(f'{"="*65}')

    results=[]
    for symbol in INSTRUMENTS:
        print(f'\n[BT] Testing {symbol}...',end=' ',flush=True)
        r=run_backtest(symbol,capital)
        if r:
            results.append(r)
            print(f'WR:{r["win_rate"]}% Return:{r["total_return"]}% Trades:{r["total_trades"]} DD:{r["max_drawdown"]}%')
        else:
            print('No data/trades')

    # Sort by return
    results.sort(key=lambda x:-x['total_return'])

    print(f'\n{"="*65}')
    print(f'  DETAILED RESULTS')
    print(f'{"="*65}')

    total_trades=0;total_wins=0
    combined_pnl=0

    for r in results:
        emoji='📈' if r['total_return']>0 else '📉'
        print(f'\n{emoji} {r["symbol"]} ({r["type"].upper()}):')
        print(f'   Return: {r["total_return"]}% | WR: {r["win_rate"]}%')
        print(f'   Trades: {r["total_trades"]} | DD: {r["max_drawdown"]}%')
        print(f'   SL: {r["sl_multiplier"]}x ATR | Lots: {r["lots_used"]}')
        print(f'   Final: Rs.{r["final_capital"]:,.0f}')
        for yr,pnl in sorted(r['yearly_pnl'].items()):
            sign='+' if pnl>=0 else ''
            print(f'   {yr}: {sign}Rs.{pnl:,.0f}')
        total_trades+=r['total_trades']
        total_wins+=r['wins']
        combined_pnl+=r['total_pnl']

    # Summary
    overall_wr=round(total_wins/total_trades*100,1) if total_trades>0 else 0
    profitable=[r for r in results if r['total_return']>0]

    print(f'\n{"="*65}')
    print(f'  COMBINED SUMMARY (All 18 Instruments)')
    print(f'{"="*65}')
    print(f'  Profitable: {len(profitable)}/{len(results)} instruments')
    print(f'  Overall WR: {overall_wr}%')
    print(f'  Total Trades: {total_trades} (3 years)')
    print(f'  Avg Trades/Month: {round(total_trades/36,1)}')
    print(f'  Combined PnL: Rs.{combined_pnl:,.0f}')

    print(f'\n  TOP 5 PERFORMERS:')
    for r in results[:5]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    print(f'\n  POOR PERFORMERS:')
    for r in results[-3:]:
        if r['total_return']<0:
            print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    # Save results
    os.makedirs('backtest_results',exist_ok=True)
    json.dump(results,open('backtest_results/final_backtest.json','w'),indent=2)
    print(f'\n[BT] Saved to backtest_results/final_backtest.json')

    # Recommended instruments
    best=[r['symbol'] for r in results
          if r['total_return']>30 and r['win_rate']>44 and r['max_drawdown']<40]
    print(f'\n✅ BEST INSTRUMENTS FOR V30:')
    print(f'   {best}')
    print(f'{"="*65}')
    return results

if __name__=='__main__':
    run_all_backtests(capital=50000)

def run_monthly_backtest(capital=50000):
    print(f'\n{"="*70}')
    print(f'  MONTHLY RETURNS - ALL 18 INSTRUMENTS (2022-2024)')
    print(f'{"="*70}')

    all_monthly={}

    for symbol in INSTRUMENTS:
        print(f'[BT] {symbol}...',end=' ',flush=True)
        candles=load_data(symbol)
        if not candles:print('No data');continue
        df=to_df(candles)
        if df is None or len(df)<200:print('Skip');continue

        lot=INSTRUMENTS[symbol]['lot']
        sl_mult=get_sl_from_mining(symbol)
        AVOID_HOURS=[9,10,15]

        current_capital=capital
        in_trade=False
        entry=0;action=''
        sl=0;t1=0;t2=0
        entry_idx=0;current_lots=1
        t1_hit=False
        daily_losses=0;last_date=None
        daily_trades=0

        monthly_pnl={}  # key: YYYY-MM

        for i in range(100,len(df)-30,2):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-300):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                hour=int(str(df5['time'].iloc[-1])[11:13])
                if hour in AVOID_HOURS:continue
                if hour<9 or hour>14:continue
                curr_date=str(df5['time'].iloc[-1])[:10]
                month_key=curr_date[:7]  # YYYY-MM
                year=curr_date[:4]
                if curr_date!=last_date:
                    daily_losses=0;daily_trades=0
                    last_date=curr_date
            except:continue

            if daily_losses>=3:continue
            if daily_trades>=4:continue

            lot_count=get_lots(symbol,current_capital)

            if not in_trade:
                try:
                    c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
                    rsi=calc_rsi(c).iloc[-1]
                    macd,sig=calc_macd(c)
                    mh=(macd-sig).iloc[-1]
                    atr=(h-l).tail(14).mean()
                    if atr<=0:continue

                    trend_d=get_trend(df_daily)
                    trend15=get_trend(df15)
                    trend5=get_trend(df5)
                    wy=get_wyckoff(df15)

                    buy_score=0;sell_score=0
                    if trend_d==1:buy_score+=3
                    elif trend_d==-1:sell_score+=3
                    if trend15==1:buy_score+=2
                    elif trend15==-1:sell_score+=2
                    if trend5==1:buy_score+=1
                    elif trend5==-1:sell_score+=1
                    if rsi<45:buy_score+=2
                    elif rsi>55:sell_score+=2
                    if mh>0:buy_score+=1
                    elif mh<0:sell_score+=1
                    vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
                    if vol_surge:
                        if mh>0:buy_score+=2
                        else:sell_score+=2

                    if buy_score>=5 and buy_score>sell_score:sig_action='BUY'
                    elif sell_score>=5 and sell_score>buy_score:sig_action='SELL'
                    else:continue

                    if trend_d==1 and sig_action=='SELL':continue
                    if trend_d==-1 and sig_action=='BUY':continue

                    market='TRENDING' if abs(trend15)==1 else 'SIDEWAYS'
                    if market=='SIDEWAYS' and not get_fvg(df5,sig_action):continue

                    if sig_action=='BUY' and wy in ['DIST','MARK']:continue
                    if sig_action=='SELL' and wy in ['ACCUM','MARKUP']:continue

                    kairos=calc_kairos(df5,df15,sig_action,trend15,wy)
                    if kairos<15:continue

                    if sig_action=='BUY' and rsi>70:continue
                    if sig_action=='SELL' and rsi<30:continue

                    ml_prob=get_ml_prob(symbol,df5,df15,sig_action,atr)
                    if ml_prob<0.35:continue

                    sl_pts=atr*sl_mult
                    t1_pts=sl_pts*1.5
                    t2_pts=sl_pts*2.5

                    entry_price=c.iloc[-1]
                    in_trade=True;action=sig_action
                    sl=sl_pts;t1=t1_pts;t2=t2_pts
                    entry=entry_price
                    entry_idx=i
                    current_lots=lot_count
                    t1_hit=False
                    trade_month=month_key

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''
                qty=current_lots*lot

                if action=='BUY':
                    if not t1_hit and row['high']>=entry+t1:
                        t1_hit=True;sl=0
                    if row['low']<=entry-sl and not t1_hit:
                        pnl=-sl*qty;reason='SL'
                    elif row['high']>=entry+t2:
                        pnl=t2*qty;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry)*qty;reason='TO'
                else:
                    if not t1_hit and row['low']<=entry-t1:
                        t1_hit=True;sl=0
                    if row['high']>=entry+sl and not t1_hit:
                        pnl=-sl*qty;reason='SL'
                    elif row['low']<=entry-t2:
                        pnl=t2*qty;reason='T2'
                    elif bars>=30:
                        pnl=(entry-row['close'])*qty;reason='TO'

                if reason:
                    net=pnl-BROKERAGE
                    current_capital+=net
                    if pnl<0:daily_losses+=1
                    daily_trades+=1
                    # Track monthly
                    if trade_month not in monthly_pnl:
                        monthly_pnl[trade_month]={'pnl':0,'trades':0,'wins':0}
                    monthly_pnl[trade_month]['pnl']+=net
                    monthly_pnl[trade_month]['trades']+=1
                    if net>0:monthly_pnl[trade_month]['wins']+=1
                    in_trade=False;t1_hit=False

        all_monthly[symbol]=monthly_pnl
        total_pnl=sum(v['pnl'] for v in monthly_pnl.values())
        ret=round(total_pnl/capital*100,1)
        print(f'Done! Total:{ret}%')

    # Print monthly report
    months=sorted(set(
        m for sym_data in all_monthly.values()
        for m in sym_data.keys()
    ))

    print(f'\n{"="*70}')
    print(f'  MONTHLY PnL TABLE (Rs.) - All Instruments')
    print(f'{"="*70}')

    # Header
    header=f'{"Month":<10}'
    for sym in INSTRUMENTS:
        header+=f'{sym:>12}'
    header+=f'{"TOTAL":>12}'
    print(header)
    print('-'*70)

    yearly_totals={}
    grand_total=0

    for month in months:
        row=f'{month:<10}'
        month_total=0
        year=month[:4]

        for sym in INSTRUMENTS:
            pnl=all_monthly.get(sym,{}).get(month,{}).get('pnl',0)
            month_total+=pnl
            sign='+' if pnl>=0 else ''
            row+=f'{sign}{pnl:>10.0f} '

        row+=f'{month_total:>+12.0f}'
        print(row)

        yearly_totals[year]=yearly_totals.get(year,0)+month_total
        grand_total+=month_total

        # Print yearly subtotal
        next_idx=months.index(month)+1
        if next_idx>=len(months) or months[next_idx][:4]!=year:
            print(f'{"--- "+year+" TOTAL ---":<10}'+' '*len(list(INSTRUMENTS))*12+f'{yearly_totals[year]:>+12.0f}')
            print('-'*70)

    print(f'\n{"GRAND TOTAL":<10}'+' '*len(list(INSTRUMENTS))*12+f'{grand_total:>+12.0f}')
    print(f'\nReturn on Rs.{capital:,.0f}: {grand_total/capital*100:.1f}%')

    # Per instrument summary
    print(f'\n{"="*70}')
    print(f'  PER INSTRUMENT 3-YEAR SUMMARY')
    print(f'{"="*70}')
    print(f'{"Symbol":<14}{"2022":>12}{"2023":>12}{"2024":>12}{"Total":>12}{"Return":>10}')
    print('-'*65)

    for sym in INSTRUMENTS:
        data=all_monthly.get(sym,{})
        y2022=sum(v['pnl'] for k,v in data.items() if k.startswith('2022'))
        y2023=sum(v['pnl'] for k,v in data.items() if k.startswith('2023'))
        y2024=sum(v['pnl'] for k,v in data.items() if k.startswith('2024'))
        total=y2022+y2023+y2024
        ret=round(total/capital*100,1)
        print(f'{sym:<14}{y2022:>+12.0f}{y2023:>+12.0f}{y2024:>+12.0f}{total:>+12.0f}{ret:>9.1f}%')

    # Save
    os.makedirs('backtest_results',exist_ok=True)
    json.dump({sym:{k:v for k,v in data.items()} 
               for sym,data in all_monthly.items()},
              open('backtest_results/monthly_returns.json','w'),indent=2)
    print(f'\n[BT] Saved to backtest_results/monthly_returns.json')
    return all_monthly

if __name__=='__main__':
    run_monthly_backtest(capital=50000)

def detect_gap_bt(df5):
    """Gap detection for backtest"""
    try:
        if len(df5)<5:return None
        hour=int(str(df5['time'].iloc[-1])[11:13])
        minute=int(str(df5['time'].iloc[-1])[14:16])
        if hour!=9 or minute>45:return None

        today=str(df5['time'].iloc[-1])[:10]
        today_candles=df5[df5['time'].astype(str).str[:10]==today]
        if len(today_candles)<1:return None

        today_open=today_candles['open'].iloc[0]
        prev_close=df5['close'].iloc[-10]
        gap_pct=((today_open-prev_close)/prev_close)*100

        if abs(gap_pct)<0.3:return None

        return {
            'gap_type':'UP' if gap_pct>0 else 'DOWN',
            'gap_pct':gap_pct,
            'gap_pts':abs(today_open-prev_close),
            'action':'BUY' if gap_pct>0 else 'SELL'
        }
    except:return None

def get_greeks_score_bt(df5,action,atr):
    """Simplified Greeks filter for backtest"""
    try:
        c=df5['close'];h=df5['high'];l=df5['low']
        current=c.iloc[-1]

        # Estimate delta based on ATM proximity
        # ATM options have delta ~0.5
        # OTM options have delta < 0.3
        atr_pct=atr/current if current>0 else 0.01

        # IV rank estimate (using ATR as volatility proxy)
        avg_atr=(h-l).tail(60).mean()
        iv_rank=min(100,(atr/avg_atr)*50) if avg_atr>0 else 50

        # Delta filter: prefer options with delta 0.3-0.6
        # Higher ATR = higher delta options available
        estimated_delta=min(0.7,0.3+(atr_pct*10))

        # Premium estimate
        estimated_premium=atr*2.5  # Rough CE/PE premium

        score=0
        signals=[]

        # Delta check
        if estimated_delta>=0.25:
            score+=3
            signals.append(f'DELTA_OK_{estimated_delta:.2f}')

        # IV rank check (prefer < 80)
        if iv_rank<80:
            score+=2
            signals.append(f'IV_RANK_OK_{iv_rank:.0f}')
        else:
            score-=2
            signals.append(f'IV_HIGH_{iv_rank:.0f}')

        # Premium check (prefer 80-300)
        if 80<=estimated_premium<=300:
            score+=2
            signals.append('PREMIUM_OK')
        elif estimated_premium<80:
            score-=1
            signals.append('PREMIUM_LOW')

        # Theta decay check (avoid buying near expiry)
        # Simulate expiry avoidance
        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour>=14:score-=1  # Theta decay higher in afternoon
        except:pass

        return score,signals,estimated_delta,iv_rank

    except:return 0,[],0.4,50

def run_monthly_backtest_full(capital=50000):
    """Full backtest with GAP + GREEKS + all logic"""
    print(f'\n{"="*70}')
    print(f'  KAIROS V30 FULL BACKTEST - ALL 18 INSTRUMENTS')
    print(f'  Including: GAP Strategy + Greeks Filter')
    print(f'  Capital: Rs.{capital:,.0f} | Brokerage: Rs.{BROKERAGE}')
    print(f'{"="*70}')

    all_monthly={}
    all_results=[]

    for symbol in INSTRUMENTS:
        print(f'\n[BT] {symbol}...',end=' ',flush=True)
        candles=load_data(symbol)
        if not candles:print('No data');continue
        df=to_df(candles)
        if df is None or len(df)<200:print('Skip');continue

        lot=INSTRUMENTS[symbol]['lot']
        sl_mult=get_sl_from_mining(symbol)
        AVOID_HOURS=[9,10,15]

        current_capital=capital
        wins=0;losses=0
        in_trade=False
        entry=0;action=''
        sl=0;t1=0;t2=0
        entry_idx=0;current_lots=1
        t1_hit=False
        daily_losses=0;last_date=None
        daily_trades=0
        peak=capital;max_dd=0
        monthly_pnl={}
        trade_month=''
        gap_trades=0;greeks_blocked=0

        for i in range(100,len(df)-30,2):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-300):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                hour=int(str(df5['time'].iloc[-1])[11:13])
                if hour in AVOID_HOURS:continue
                if hour<9 or hour>14:continue
                curr_date=str(df5['time'].iloc[-1])[:10]
                month_key=curr_date[:7]
                if curr_date!=last_date:
                    daily_losses=0;daily_trades=0
                    last_date=curr_date
            except:continue

            if daily_losses>=3:continue
            if daily_trades>=4:continue

            lot_count=get_lots(symbol,current_capital)

            if not in_trade:
                try:
                    c=df5['close'];h=df5['high']
                    l=df5['low'];v=df5['volume']
                    rsi=calc_rsi(c).iloc[-1]
                    macd_line,sig=calc_macd(c)
                    mh=(macd_line-sig).iloc[-1]
                    atr=(h-l).tail(14).mean()
                    if atr<=0:continue

                    trend_d=get_trend(df_daily)
                    trend15=get_trend(df15)
                    trend5=get_trend(df5)
                    wy=get_wyckoff(df15)
                    sig_action=None

                    # Check gap strategy first (morning only)
                    gap=detect_gap_bt(df5)
                    if gap and daily_trades==0:
                        sig_action=gap['action']
                        # Gap trade uses tighter SL
                        sl_pts=atr*1.2
                        t1_pts=gap['gap_pts']*0.5
                        t2_pts=gap['gap_pts']
                        gap_trades+=1
                    else:
                        # Normal signal generation
                        buy_score=0;sell_score=0
                        if trend_d==1:buy_score+=3
                        elif trend_d==-1:sell_score+=3
                        if trend15==1:buy_score+=2
                        elif trend15==-1:sell_score+=2
                        if trend5==1:buy_score+=1
                        elif trend5==-1:sell_score+=1
                        if rsi<45:buy_score+=2
                        elif rsi>55:sell_score+=2
                        if mh>0:buy_score+=1
                        elif mh<0:sell_score+=1
                        vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
                        if vol_surge:
                            if mh>0:buy_score+=2
                            else:sell_score+=2

                        if buy_score>=5 and buy_score>sell_score:
                            sig_action='BUY'
                        elif sell_score>=5 and sell_score>buy_score:
                            sig_action='SELL'
                        else:continue

                        if trend_d==1 and sig_action=='SELL':continue
                        if trend_d==-1 and sig_action=='BUY':continue

                        market='TRENDING' if abs(trend15)==1 else 'SIDEWAYS'
                        if market=='SIDEWAYS' and not get_fvg(df5,sig_action):continue

                        if sig_action=='BUY' and wy in ['DIST','MARK']:continue
                        if sig_action=='SELL' and wy in ['ACCUM','MARKUP']:continue

                        kairos=calc_kairos(df5,df15,sig_action,trend15,wy)
                        if kairos<15:continue

                        if sig_action=='BUY' and rsi>70:continue
                        if sig_action=='SELL' and rsi<30:continue

                        # Greeks filter
                        greek_score,greek_sigs,delta,iv_rank=get_greeks_score_bt(
                            df5,sig_action,atr)
                        if greek_score<2:
                            greeks_blocked+=1
                            continue
                        if delta<0.20:continue  # Too far OTM
                        if iv_rank>85:continue  # Too expensive

                        # RR Filter - must have tight SL and 1:3+ target
                    rr_ok,rr_sl,rr_target,rr_ratio,rr_quality,rr_issues=apply_rr_filter(df5,df15,sig_action,atr,symbol,current_capital)
                    if not rr_ok:
                        continue
                # RR Filter
                rr_ok,rr_sl,rr_target,rr_ratio,rr_quality,rr_issues=apply_rr_filter(df5,df15,sig_action,atr,symbol,current_capital)
                if not rr_ok:continue
                ml_prob=get_ml_prob(symbol,df5,df15,sig_action,atr)
                if ml_prob<0.35:continue
                sl_pts=rr_sl
                t1_pts=sl_pts*1.5
                t2_pts=sl_pts*2.5
                        t2_pts=sl_pts*2.5

                    entry_price=c.iloc[-1]
                    in_trade=True;action=sig_action
                    sl=sl_pts;t1=t1_pts;t2=t2_pts
                    entry=entry_price
                    entry_idx=i
                    current_lots=lot_count
                    t1_hit=False
                    trade_month=month_key

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''
                qty=current_lots*lot

                if action=='BUY':
                    if not t1_hit and row['high']>=entry+t1:
                        t1_hit=True;sl=0
                    if row['low']<=entry-sl and not t1_hit:
                        pnl=-sl*qty;reason='SL'
                    elif row['high']>=entry+t2:
                        pnl=t2*qty;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry)*qty;reason='TO'
                else:
                    if not t1_hit and row['low']<=entry-t1:
                        t1_hit=True;sl=0
                    if row['high']>=entry+sl and not t1_hit:
                        pnl=-sl*qty;reason='SL'
                    elif row['low']<=entry-t2:
                        pnl=t2*qty;reason='T2'
                    elif bars>=30:
                        pnl=(entry-row['close'])*qty;reason='TO'

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
                        monthly_pnl[trade_month]={
                            'pnl':0,'trades':0,'wins':0}
                    monthly_pnl[trade_month]['pnl']+=net
                    monthly_pnl[trade_month]['trades']+=1
                    if net>0:monthly_pnl[trade_month]['wins']+=1
                    in_trade=False;t1_hit=False

        total=wins+losses
        wr=round(wins/total*100,1) if total>0 else 0
        ret=round((current_capital-capital)/capital*100,1)

        all_monthly[symbol]=monthly_pnl
        all_results.append({
            'symbol':symbol,
            'type':INSTRUMENTS[symbol]['type'],
            'total_trades':total,
            'wins':wins,'losses':losses,
            'win_rate':wr,
            'total_return':ret,
            'max_drawdown':round(max_dd,1),
            'final_capital':round(current_capital,2),
            'gap_trades':gap_trades,
            'greeks_blocked':greeks_blocked,
            'sl_multiplier':sl_mult,
            'monthly_pnl':monthly_pnl
        })
        print(f'WR:{wr}% Return:{ret}% Trades:{total} '
              f'GapTrades:{gap_trades} GreeksBlocked:{greeks_blocked}')

    # Print monthly table
    months=sorted(set(
        m for sym_data in all_monthly.values()
        for m in sym_data.keys()
    ))

    print(f'\n{"="*70}')
    print(f'  MONTHLY RETURNS PER INSTRUMENT (Rs.)')
    print(f'{"="*70}')

    for symbol in INSTRUMENTS:
        data=all_monthly.get(symbol,{})
        if not data:continue

        print(f'\n--- {symbol} ({INSTRUMENTS[symbol]["type"].upper()}) ---')
        print(f'{"Month":<10}{"PnL":>12}{"Trades":>8}{"WR":>8}{"Capital":>14}')
        print('-'*55)

        running=capital
        y_totals={}

        for month in months:
            mdata=data.get(month)
            if not mdata:continue
            pnl=mdata['pnl']
            trades=mdata['trades']
            mwins=mdata['wins']
            mwr=round(mwins/trades*100) if trades>0 else 0
            running+=pnl
            year=month[:4]
            y_totals[year]=y_totals.get(year,0)+pnl
            sign='+' if pnl>=0 else ''
            print(f'{month:<10}{sign}{pnl:>10.0f}  {trades:>6}  {mwr:>5}%  Rs.{running:>10,.0f}')

            # Yearly total
            next_idx=months.index(month)+1
            if next_idx>=len(months) or months[next_idx][:4]!=year:
                print(f'{"":10}{"─"*45}')
                ytot=y_totals[year]
                sign='+' if ytot>=0 else ''
                yret=round(ytot/capital*100,1)
                print(f'{year+" TOTAL":<10}{sign}{ytot:>10.0f}{"":>8}{"":>8}  ({yret}% ROI)')
                print(f'{"":10}{"─"*45}')

        total_pnl=sum(v['pnl'] for v in data.values())
        total_ret=round(total_pnl/capital*100,1)
        r=next((x for x in all_results if x['symbol']==symbol),{})
        print(f'\n  3YR SUMMARY: WR={r.get("win_rate",0)}% '
              f'Trades={r.get("total_trades",0)} '
              f'Return={total_ret}% '
              f'MaxDD={r.get("max_drawdown",0)}%')

    # Combined summary
    print(f'\n{"="*70}')
    print(f'  COMBINED ALL INSTRUMENTS MONTHLY')
    print(f'{"="*70}')
    print(f'{"Month":<10}{"Total PnL":>14}{"Instruments":>14}{"Avg/Inst":>12}')
    print('-'*55)

    grand=0
    for month in months:
        month_total=sum(
            all_monthly.get(sym,{}).get(month,{}).get('pnl',0)
            for sym in INSTRUMENTS
        )
        active=sum(
            1 for sym in INSTRUMENTS
            if all_monthly.get(sym,{}).get(month)
        )
        avg=round(month_total/active) if active>0 else 0
        grand+=month_total
        year=month[:4]
        sign='+' if month_total>=0 else ''
        print(f'{month:<10}{sign}{month_total:>12.0f}  {active:>12}  {sign}{avg:>10.0f}')

        next_idx=months.index(month)+1
        if next_idx>=len(months) or months[next_idx][:4]!=year:
            print(f'{"─"*55}')

    print(f'\n{"GRAND TOTAL":<10}{grand:>+14.0f}')
    print(f'{"3YR ROI":<10}{grand/capital*100:>13.1f}%')
    print(f'{"Monthly avg":<10}{grand/36:>+14.0f}')

    # Save
    os.makedirs('backtest_results',exist_ok=True)
    json.dump(all_results,open(
        'backtest_results/full_backtest_results.json','w'),indent=2)
    print(f'\n[BT] Saved to backtest_results/full_backtest_results.json')
    return all_monthly,all_results

if __name__=='__main__':
    run_monthly_backtest_full(capital=50000)
