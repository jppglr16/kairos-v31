import json,os,pickle,time
import numpy as np
import pandas as pd
from datetime import datetime

STOCKS_CONFIG={
    'LT':        {'token':'11483','lot':450},
    'NTPC':      {'token':'11630','lot':4500},
    'MARUTI':    {'token':'10999','lot':100},
    'BHARTIARTL':{'token':'10604','lot':950},
    'SBIN':      {'token':'3045','lot':1500},
    'TATAMOTORS':{'token':'3456','lot':1350},
    'RELIANCE':  {'token':'2885','lot':250},
    'HINDUNILVR':{'token':'1394','lot':300},
    'TCS':       {'token':'11536','lot':150},
    'TATASTEEL': {'token':'3499','lot':5500},
}

INDEX_CONFIG={
    'NIFTY':     {'token':'99926000','exchange':'NSE','lot':75},
    'BANKNIFTY': {'token':'99926009','exchange':'NSE','lot':30},
    'FINNIFTY':  {'token':'99926037','exchange':'NSE','lot':65},
    'MIDCPNIFTY':{'token':'99926074','exchange':'NSE','lot':120},
    'CRUDEOIL':  {'token':'472790','exchange':'MCX','lot':100},
    'GOLDM':     {'token':'477904','exchange':'MCX','lot':10},
    'SENSEX':    {'token':'99919000','exchange':'BSE','lot':10},
    'SILVERM':   {'token':'457533','exchange':'MCX','lot':30},
}

BROKERAGE=25  # Per order flat fee
MAX_LOTS=1

def load_data(symbol):
    all_candles=[]
    for year in [2022,2023,2024]:
        # Try symbol name first
        fname=f'historical_data/{symbol}_{year}_5min.json'
        if not os.path.exists(fname):
            # Try token
            token=STOCKS_CONFIG.get(symbol,{}).get('token','')
            if token:
                fname=f'historical_data/{token}_{year}_5min.json'
        if os.path.exists(fname):
            all_candles.extend(json.load(open(fname)))
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
    sig=m.ewm(span=9).mean()
    return m,sig

def get_trend(df):
    try:
        c=df['close']
        s20=c.rolling(20).mean().iloc[-1]
        s50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else s20
        cur=c.iloc[-1]
        if cur>s20 and s20>s50:return 'UP'
        elif cur<s20 and s20<s50:return 'DOWN'
        return 'SIDE'
    except:return 'SIDE'

def get_wyckoff(df):
    try:
        c=df['close'].values
        v=df['volume'].values
        h=df['high'].values
        l=df['low'].values
        recent_v=v[-20:].mean()
        old_v=v[-60:-20].mean() if len(v)>=60 else recent_v
        vol_dec=recent_v<old_v*0.8
        recent_range=h[-20:].max()-l[-20:].min()
        old_range=h[-60:-20].max()-l[-60:-20].min() if len(h)>=60 else recent_range
        consolidating=recent_range<old_range*0.6
        s20=pd.Series(c).rolling(20).mean().values
        s50=pd.Series(c).rolling(50).mean().values
        above_s50=c[-1]>s50[-1]
        spring=l[-20:].min()<l[-60:-20].min() and c[-1]>l[-60:-20].min() if len(l)>=60 else False
        upthrust=h[-20:].max()>h[-60:-20].max() and c[-1]<h[-60:-20].max() if len(h)>=60 else False
        if consolidating and not above_s50 and (vol_dec or spring):
            return 'ACCUM',spring
        elif c[-1]>s20[-1] and s20[-1]>s50[-1]:
            return 'MARKUP',False
        elif consolidating and above_s50 and (vol_dec or upthrust):
            return 'DIST',upthrust
        elif c[-1]<s20[-1] and s20[-1]<s50[-1]:
            return 'MARK',False
        return 'TRANS',False
    except:return 'UNKNOWN',False

def get_kill_zone():
    now=datetime.now()
    h,m=now.hour,now.minute
    t=h*60+m
    if 555<=t<=660:return 'NSE_OPEN',5
    elif 780<=t<=870:return 'AFTERNOON',4
    elif 390<=t<=570:return 'LONDON',3
    return 'NONE',0

def calc_kairos_score(df5,df15,action):
    score=0
    try:
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        rsi=calc_rsi(c).iloc[-1]
        macd,sig=calc_macd(c)
        macd_hist=(macd-sig).iloc[-1]
        atr=(h-l).tail(14).mean()
        vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
        trend5=get_trend(df5)
        trend15=get_trend(df15)
        sma20=c.rolling(20).mean().iloc[-1]
        current=c.iloc[-1]
        swing_high=h.tail(20).max()
        swing_low=l.tail(20).min()
        fvg=False
        for i in range(len(df5)-3,len(df5)-1):
            p2=df5.iloc[i-2];cur=df5.iloc[i]
            if action=='BUY' and cur['low']>p2['high']:fvg=True;break
            elif action=='SELL' and cur['high']<p2['low']:fvg=True;break

        # Wyckoff
        wy_phase,wy_special=get_wyckoff(df15)

        # K - Kill zone (use time-based for backtest)
        score+=2  # Average kill zone score

        # A - Alignment
        if action=='BUY':
            align=sum([trend5=='UP',trend15=='UP',macd_hist>0,current>sma20])
        else:
            align=sum([trend5=='DOWN',trend15=='DOWN',macd_hist<0,current<sma20])
        score+=align*2

        # I - Imbalance
        if fvg:score+=4

        # R - Rejection
        if action=='BUY':
            if current<=swing_low*1.005:score+=3
            if rsi<35:score+=3
        else:
            if current>=swing_high*0.995:score+=3
            if rsi>65:score+=3

        # O - Volume confirmation
        if vol_surge:score+=3

        # S - SMC strength
        if action=='BUY' and trend15=='UP':score+=3
        elif action=='SELL' and trend15=='DOWN':score+=3

        # W - Wyckoff
        if action=='BUY':
            if wy_phase=='ACCUM':score+=5
            if wy_special:score+=3  # Spring
            if wy_phase=='MARKUP':score+=4
            if wy_phase in ['DIST','MARK']:score-=3
        else:
            if wy_phase=='DIST':score+=5
            if wy_special:score+=3  # Upthrust
            if wy_phase=='MARK':score+=4
            if wy_phase in ['ACCUM','MARKUP']:score-=3

        # VP - VWAP
        vwap=(c*v).sum()/v.sum() if v.sum()>0 else c.mean()
        if action=='BUY' and current>vwap:score+=2
        elif action=='SELL' and current<vwap:score+=2

        return score,wy_phase
    except:return 0,'UNKNOWN'

def load_ml_model(symbol):
    for fname in [
        f'ml_models/{symbol}_full_model.pkl',
        f'ml_models/{symbol}_model.pkl',
        'ml_models/NIFTY_full_model.pkl',
        'ml_models/NIFTY_model.pkl'
    ]:
        if os.path.exists(fname):
            try:
                return pickle.load(open(fname,'rb'))
            except:pass
    return None

def get_ml_score(df5,df15,action,model_data):
    try:
        if not model_data:return 0.5
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        rsi=calc_rsi(c).iloc[-1]
        macd,sig=calc_macd(c)
        macd_hist=(macd-sig).iloc[-1]
        atr=(h-l).tail(14).mean()
        trend15=get_trend(df15)
        features=[
            (c.iloc[-1]-c.iloc[-2])/c.iloc[-2],
            (c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0,
            rsi/100,
            macd_hist/atr if atr>0 else 0,
            1 if v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5 else 0,
            1 if trend15=='UP' else -1 if trend15=='DOWN' else 0,
            1 if action=='BUY' else -1,
            (h-l).tail(14).mean()/c.iloc[-1],
            datetime.now().hour/24,
            1 if get_trend(df5)=='UP' else -1
        ]
        # Pad features to match model
        model=model_data['model']
        scaler=model_data['scaler']
        n_features=model.n_features_in_
        while len(features)<n_features:features.append(0)
        features=features[:n_features]
        f_scaled=scaler.transform([features])
        prob=model.predict_proba(f_scaled)[0][1]
        return prob
    except:return 0.5

def run_master_backtest(symbol,lot,capital=50000,mode='KAIROS'):
    candles=load_data(symbol)
    if not candles:
        print(f'[BT] No data: {symbol}')
        return None
    df=to_df(candles)
    if df is None or len(df)<200:return None

    ml_model=load_ml_model(symbol)
    if ml_model:
        print(f'[BT] {symbol}: Using ML model ({ml_model.get("accuracy",0)*100:.1f}% acc)')
    else:
        print(f'[BT] {symbol}: No ML model, using rules only')

    current_capital=capital
    wins=0;losses=0
    in_trade=False
    entry_price=0;trade_action=''
    sl=0;t2=0;entry_idx=0;current_lots=1
    daily_losses=0;last_date=None;t1_hit=False
    peak_capital=capital;max_drawdown=0
    yearly_pnl={};daily_trade_count=0

    # KAIROS threshold
    min_kairos=15 if mode=='KAIROS' else 10

    for i in range(100,len(df)-20,3):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        df_daily=df.iloc[max(0,i-300):i:12].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour<9 or hour>14:continue
        except:pass

        try:
            current_date=str(df5['time'].iloc[-1])[:10]
            year=current_date[:4]
            if current_date!=last_date:
                daily_losses=0;daily_trade_count=0
                last_date=current_date
        except:year='2022'

        if daily_losses>=3:continue
        if daily_trade_count>=2:continue  # Max 2 stock trades/day

        risk_amt=min(current_capital*0.05,2500)

        if not in_trade:
            try:
                c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
                rsi=calc_rsi(c).iloc[-1]
                macd,sig=calc_macd(c)
                macd_hist=(macd-sig).iloc[-1]
                atr=(h-l).tail(14).mean()
                if atr<=0:continue
                vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5

                trend_daily=get_trend(df_daily)
                trend15=get_trend(df15)

                # Determine action
                buy_score=0;sell_score=0
                if trend_daily=='UP':buy_score+=3
                elif trend_daily=='DOWN':sell_score+=3
                if trend15=='UP':buy_score+=2
                elif trend15=='DOWN':sell_score+=2
                if rsi<40:buy_score+=3
                elif rsi>60:sell_score+=3
                if macd_hist>0:buy_score+=2
                elif macd_hist<0:sell_score+=2
                if vol_surge:
                    if macd_hist>0:buy_score+=2
                    else:sell_score+=2

                if buy_score>sell_score and buy_score>=8:
                    action='BUY'
                elif sell_score>buy_score and sell_score>=8:
                    action='SELL'
                else:
                    continue

                # TREND FILTER - Only trade with daily trend
                if trend_daily=='UP' and action=='SELL':continue
                if trend_daily=='DOWN' and action=='BUY':continue

                # KAIROS SCORE
                kairos_score,wy_phase=calc_kairos_score(df5,df15,action)
                if kairos_score<min_kairos:continue

                # WYCKOFF filter
                if action=='BUY' and wy_phase in ['DIST','MARK']:continue
                if action=='SELL' and wy_phase in ['ACCUM','MARKUP']:continue

                # RSI filter
                if action=='BUY' and rsi>70:continue
                if action=='SELL' and rsi<30:continue

                # ML FILTER
                ml_prob=get_ml_score(df5,df15,action,ml_model)
                if ml_prob<0.40:continue

                # RL simulation (use KAIROS score as proxy)
                rl_confidence=kairos_score/30  # Normalize
                if rl_confidence<0.4:continue

                sl_pts=atr*1.5
                t2_pts=sl_pts*2.5
                lots=max(1,int(risk_amt/(sl_pts*lot)))
                lots=min(lots,MAX_LOTS)  # Max 1 lot

                entry_price=df5['close'].iloc[-1]
                in_trade=True;trade_action=action
                sl=sl_pts;t2=t2_pts
                entry_idx=i;current_lots=lots;t1_hit=False

            except:continue
        else:
            row=df.iloc[i]
            bars=i-entry_idx
            pnl=0;reason=''

            if trade_action=='BUY':
                if not t1_hit and row['high']>=entry_price+(t2*0.5):
                    t1_hit=True;sl=0
                if row['low']<=entry_price-sl:
                    pnl=-sl*lot*current_lots;reason='SL'
                elif row['high']>=entry_price+t2:
                    pnl=t2*lot*current_lots;reason='T2'
                elif bars>=30:
                    pnl=(row['close']-entry_price)*lot*current_lots;reason='TO'
            else:
                if not t1_hit and row['low']<=entry_price-(t2*0.5):
                    t1_hit=True;sl=0
                if row['high']>=entry_price+sl:
                    pnl=-sl*lot*current_lots;reason='SL'
                elif row['low']<=entry_price-t2:
                    pnl=t2*lot*current_lots;reason='T2'
                elif bars>=30:
                    pnl=(entry_price-row['close'])*lot*current_lots;reason='TO'

            if reason:
                net_pnl=pnl-BROKERAGE
                current_capital+=net_pnl
                if pnl<0:daily_losses+=1;losses+=1
                else:wins+=1
                daily_trade_count+=1
                if current_capital>peak_capital:peak_capital=current_capital
                dd=((peak_capital-current_capital)/peak_capital)*100
                if dd>max_drawdown:max_drawdown=dd
                yearly_pnl[year]=yearly_pnl.get(year,0)+net_pnl
                in_trade=False;t1_hit=False

    total=wins+losses
    if total==0:return None
    wr=round((wins/total)*100,1)
    total_return=round(((current_capital-capital)/capital)*100,1)

    return {
        'symbol':symbol,
        'total_trades':total,
        'wins':wins,'losses':losses,
        'win_rate':wr,
        'total_pnl':round(current_capital-capital,2),
        'total_return':total_return,
        'max_drawdown':round(max_drawdown,1),
        'yearly_pnl':yearly_pnl,
        'final_capital':round(current_capital,2),
        'ml_used':ml_model is not None
    }

def run_all(capital=50000):
    print(f'\n{"="*60}')
    print(f'  MASTER BACKTEST: KAIROS+WYCKOFF+ML+RL')
    print(f'  Capital: Rs.{capital:,.0f} | Brokerage: Rs.{BROKERAGE}')
    print(f'  Max Lots: {MAX_LOTS} | Min KAIROS: 15')
    print(f'{"="*60}')

    all_results=[]

    # Index instruments
    print('\n--- INDEX INSTRUMENTS ---')
    for symbol,info in INDEX_CONFIG.items():
        print(f'\n[BT] {symbol}...')
        result=run_master_backtest(symbol,info['lot'],capital)
        if result:
            all_results.append({**result,'type':'INDEX'})
            print(f'  WR:{result["win_rate"]}% Return:{result["total_return"]}% Trades:{result["total_trades"]} DD:{result["max_drawdown"]}%')

    # Stock instruments
    print('\n--- STOCK OPTIONS ---')
    for symbol,info in STOCKS_CONFIG.items():
        print(f'\n[BT] {symbol}...')
        result=run_master_backtest(symbol,info['lot'],capital)
        if result:
            all_results.append({**result,'type':'STOCK'})
            print(f'  WR:{result["win_rate"]}% Return:{result["total_return"]}% Trades:{result["total_trades"]} DD:{result["max_drawdown"]}%')

    # Summary
    print(f'\n{"="*60}')
    print(f'  FINAL RESULTS SUMMARY')
    print(f'{"="*60}')

    all_results.sort(key=lambda x:-x['total_return'])

    total_combined_pnl=0
    for r in all_results:
        emoji='📈' if r['total_return']>0 else '📉'
        print(f'\n{emoji} {r["symbol"]} ({r["type"]}):')
        print(f'  Return: {r["total_return"]}% | WR: {r["win_rate"]}%')
        print(f'  Trades: {r["total_trades"]} | DD: {r["max_drawdown"]}%')
        print(f'  ML Used: {r["ml_used"]}')
        for yr,pnl in sorted(r['yearly_pnl'].items()):
            print(f'  {yr}: Rs.{pnl:,.0f}')

    # Best performers
    profitable=[r for r in all_results if r['total_return']>0]
    print(f'\n{"="*60}')
    print(f'  ✅ PROFITABLE: {len(profitable)}/{len(all_results)} instruments')
    print(f'  Top 5:')
    for r in all_results[:5]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    # Save
    os.makedirs('backtest_results',exist_ok=True)
    json.dump(all_results,open('backtest_results/master_backtest.json','w'),indent=2)
    print(f'\n[BT] Saved to backtest_results/master_backtest.json')

    # Auto update V30 with best instruments
    best=[r['symbol'] for r in all_results if r['total_return']>50 and r['win_rate']>44 and r['max_drawdown']<60]
    print(f'\n✅ RECOMMENDED FOR V30:')
    print(f'{best}')
    return all_results

if __name__=='__main__':
    run_all(capital=50000)
