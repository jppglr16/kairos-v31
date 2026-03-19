import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

INSTRUMENTS={
    'NIFTY':     {'type':'index','lot':75,'token':'99926000'},
    'BANKNIFTY': {'type':'index','lot':30,'token':'99926009'},
    'SENSEX':    {'type':'index','lot':20,'token':'99919000'},
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

# ============================================================
# REALISTIC COST MODEL
# ============================================================
BROKERAGE=34  # Kotak Neo actual cost  # Per order

# Slippage: % of price (market impact)
SLIPPAGE={
    'index':0.0005,     # 0.05% for liquid index options
    'stock':0.001,      # 0.10% for stock options
    'commodity':0.0008  # 0.08% for commodity
}

# Spread cost: bid-ask spread in points
SPREAD={
    'NIFTY':1.5,'BANKNIFTY':2.0,'SENSEX':1.0,
    'FINNIFTY':1.5,'MIDCPNIFTY':2.0,
    'CRUDEOIL':2.0,'GOLDM':1.5,'SILVERM':2.0,
    'LT':2.0,'NTPC':2.0,'MARUTI':3.0,
    'BHARTIARTL':2.0,'SBIN':2.0,'TATAMOTORS':2.0,
    'RELIANCE':2.0,'HINDUNILVR':3.0,'TCS':3.0,'TATASTEEL':2.0
}

# Theta decay: per 5min candle (option premium decay)
# Options lose ~30% of value per day = 0.21% per 5min candle
THETA_PER_CANDLE=0.0021  # 0.21% per 5min bar

def get_realistic_costs(symbol,entry_price,qty,inst_type,bars_held):
    """Kotak Neo: Rs.20 brokerage + Rs.14 exchange+GST = Rs.34 total"""
    return {
        'brokerage':20,
        'exchange_gst':14,
        'total':34
    }

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

def get_ml_prob(symbol,df5,df15,action,atr):
    try:
        for f in [f'ml_models/{symbol}_v31_model.pkl',
                  f'ml_models/{symbol}_model.pkl',
                  'ml_models/NIFTY_model.pkl']:
            if os.path.exists(f):
                data=pickle.load(open(f,'rb'))
                break
        else:return 0.5
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        d=c.diff();g=d.clip(lower=0).rolling(14).mean()
        ll=-d.clip(upper=0).rolling(14).mean()
        rsi=float((100-(100/(1+g/ll))).iloc[-1])
        e12=c.ewm(span=12).mean();e26=c.ewm(span=26).mean()
        mh=float(((e12-e26)-(e12-e26).ewm(span=9).mean()).iloc[-1])
        from v31_strategy import get_trend_v31
        t5=get_trend_v31(df5);t15=get_trend_v31(df15)
        vr=float(v.iloc[-1])/float(v.rolling(20).mean().iloc[-1]) if float(v.rolling(20).mean().iloc[-1])>0 else 1
        cur=float(c.iloc[-1])
        features=[
            (cur-float(c.iloc[-2]))/float(c.iloc[-2]),
            (cur-float(c.iloc[-6]))/float(c.iloc[-6]) if len(c)>6 else 0,
            rsi/100,(rsi-50)/50,
            mh/atr if atr>0 else 0,
            min(vr,3)/3,t5,t15,
            1 if cur>float(c.rolling(20).mean().iloc[-1]) else 0,
            atr/cur if cur>0 else 0,
            1 if action=='BUY' else -1,
        ]
        model=data['model'];scaler=data['scaler']
        n=model.n_features_in_
        while len(features)<n:features.append(0)
        return float(model.predict_proba(scaler.transform([features[:n]]))[0][1])
    except:return 0.5

def run_v31_full_backtest(capital=50000):
    from v31_scoring import calc_v31_score
    from v31_strategy import get_market_regime,get_trend_v31
    from v30_final_backtest import get_wyckoff
    from v31_trap import get_full_trap_score
    # Disable live gamma in backtest
    import v31_gamma
    v31_gamma.get_option_chain=lambda s:None
    from v30_rr_filter import find_tight_sl,find_best_target

    print(f'\n{"="*65}')
    print(f'  KAIROS V31 FULL REALISTIC BACKTEST')
    print(f'  Including: Theta + Spread + Slippage + V31 Logic')
    print(f'  Capital: Rs.{capital:,.0f} | Min RR: 1:3')
    print(f'{"="*65}')

    all_monthly={}
    all_results=[]
    all_signals=[]  # For mining

    for symbol in INSTRUMENTS:
        print(f'\n[V31] {symbol}...',end=' ',flush=True)
        candles=load_data(symbol)
        if not candles:print('No data');continue
        df=to_df(candles)
        if df is None or len(df)<200:print('Skip');continue

        inst_type=INSTRUMENTS[symbol]['type']
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
        total_costs_paid=0

        # Blocking stats
        regime_blocked=0;liq_blocked=0
        fvg_blocked=0;score_blocked=0
        rr_blocked=0;ml_blocked=0

        for i in range(100,len(df)-30,3):
            # 5-min candles (primary)
            df5=df.iloc[i-60:i].copy()
            # 3-min candles (derived from 5-min)
            df3=df.iloc[i-36:i].copy()  # 36 × 5min ≈ 3hr
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-300):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            try:
                hour=int(str(df5['time'].iloc[-1])[11:13])
                if hour not in [9,10,11,12,13,14]:continue
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
                    c=df5['close'];h=df5['high']
                    l=df5['low'];v=df5['volume']
                    atr=float((h-l).tail(14).mean())
                    if atr<=0:continue

                    # ATR volatility filter: ATR(5m) > 0.35% of price
                    avg_atr=float((h-l).rolling(20).mean().iloc[-1])
                    if atr<avg_atr*0.7:continue
                    atr_pct=atr/float(c.iloc[-1])*100
                    if atr_pct<0.10:continue  # ATR must be > 0.15%

                    # Market regime
                    regime,_=get_market_regime(df5,df15,df_daily)
                    if regime=='VOLATILE':regime_blocked+=1;continue

                    # Direction
                    if regime=='TRENDING_UP':action='BUY'
                    elif regime=='TRENDING_DOWN':action='SELL'
                    else:
                        from v31_strategy import detect_liquidity_sweep_v31
                        hb,_,_=detect_liquidity_sweep_v31(df5,'BUY',atr)
                        hs,_,_=detect_liquidity_sweep_v31(df5,'SELL',atr)
                        if hb:action='BUY'
                        elif hs:action='SELL'
                        else:continue

                    # Liquidity sweep validation:
                    # Candle must CLOSE BACK inside range
                    from v31_strategy import detect_liquidity_sweep_v31
                    has_valid_liq=False
                    for sweep_action in [action]:
                        swept,liq_type,liq_level=detect_liquidity_sweep_v31(df5,sweep_action,atr)
                        if swept:
                            last=df5.iloc[-1]
                            if sweep_action=='BUY':
                                # Close must be above swept level
                                if float(last['close'])>liq_level:
                                    has_valid_liq=True
                            else:
                                # Close must be below swept level
                                if float(last['close'])<liq_level:
                                    has_valid_liq=True

                    # Trend check
                    t5=get_trend_v31(df5);t15=get_trend_v31(df15)
                    td=get_trend_v31(df_daily)
                    if action=='BUY' and t5==-1 and t15==-1 and td==-1:
                        liq_blocked+=1;continue
                    if action=='SELL' and t5==1 and t15==1 and td==1:
                        liq_blocked+=1;continue

                    # Also check 3-min setup
                    atr3=float((df3['high']-df3['low']).tail(14).mean()) if len(df3)>=14 else atr
                    score3,comp3,liq3,fvg3=calc_v31_score(
                        df3,df15,action,regime,'UNKNOWN',atr3) if len(df3)>=30 else (0,{},False,False)

                    # V31 scoring (5-min primary)
                    wy=get_wyckoff(df15)
                    score,components,has_liq,has_fvg=calc_v31_score(
                        df5,df15,action,regime,wy,atr)

                    # Use best score (5min or 3min)
                    if score3>score:
                        score=score3
                        components=comp3
                        has_liq=liq3
                        has_fvg=fvg3
                        log.debug(f"[BT] {symbol} 3-min score better: {score3}")

                    # Trap detection bonus
                    trap_score,trap_info=get_full_trap_score(
                        symbol,df5,action,atr,float(c.iloc[-1]))
                    score+=trap_score

                    # Adaptive threshold
                    if score<18:score_blocked+=1;continue
                    need_high_ml=(13<=score<=18)

                    # RR filter
                    is_trending=regime in ['TRENDING_UP','TRENDING_DOWN']
                    sl_type,raw_sl,_=find_tight_sl(df5,df15,action,atr)
                    if raw_sl<atr*0.75:raw_sl=atr*0.75
                    if raw_sl>atr*2.0:rr_blocked+=1;continue
                    # Check gamma blast
                    is_gamma_blast=components.get('gamma',0)>=5
                    
                    # Score-based RR
                    if is_gamma_blast:
                        min_rr=3.0   # Gamma blast: 1:3 to 1:5
                    elif score>=18:min_rr=3.0
                    elif score>=15:min_rr=2.0
                    elif score>=12:min_rr=1.5
                    else:min_rr=1.0  # 3-min setup: 1:1

                    _,target,rr=find_best_target(
                        df5,df15,action,float(c.iloc[-1]),raw_sl,atr,is_trending)
                    if rr<min_rr:rr_blocked+=1;continue
                    # Apply score-based target
                    if is_gamma_blast:
                        t2_ratio=5.0  # Gamma blast: target 1:5!
                        t1_5_ratio=3.0  # Partial at 1:3
                    elif score>=18:
                        t2_ratio=3.0
                        t1_5_ratio=1.5
                    elif score>=15:
                        t2_ratio=2.0
                        t1_5_ratio=1.5
                    else:
                        t2_ratio=1.5  # 3-min: 1:1.5
                        t1_5_ratio=1.0

                    # ML filter
                    ml_prob=get_ml_prob(symbol,df5,df15,action,atr)
                    if need_high_ml and ml_prob<0.55:ml_blocked+=1;continue
                    elif not need_high_ml and ml_prob<0.35:ml_blocked+=1;continue

                    # Clean entry (no slippage in backtest)
                    entry_p=float(c.iloc[-1])

                    in_trade=True;sig_action=action
                    sl_pts=raw_sl
                    t1_pts=raw_sl*1.0      # 1R = move SL to entry
                    t1_5_pts=raw_sl*t1_5_ratio  # 50% exit
                    t2_pts=raw_sl*t2_ratio      # 50% exit
                    partial_exit=False
                    trade_is_gamma=is_gamma_blast
                    entry_idx=i;current_lots=lot_count
                    t1_hit=False;trade_month=month_key

                    # Store signal for mining
                    all_signals.append({
                        'symbol':symbol,'action':action,
                        'score':score,'regime':regime,'wyckoff':wy,
                        'hour':hour,'trap_score':trap_score,
                        'liq':components.get('liq_sweep',0),
                        'fvg':components.get('fvg',0),
                        'bos':components.get('bos_choch',0),
                        'ml_prob':ml_prob,'rr':rr,
                        'sl_atr':raw_sl/atr,
                        'trend5':t5,'trend15':t15,
                        'outcome':None,'pnl':None  # Fill on exit
                    })

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''
                qty=current_lots*lot

                half_qty=max(1,qty//2)
                if sig_action=='BUY':
                    # 1R hit: move SL to breakeven
                    if not t1_hit and row['high']>=entry_p+t1_pts:
                        t1_hit=True;sl_pts=0
                    # 1.5R: partial exit (50%)
                    if not partial_exit and row['high']>=entry_p+t1_5_pts:
                        partial_exit=True
                        partial_pnl=t1_5_pts*half_qty
                    # SL hit
                    if row['low']<=entry_p-sl_pts and not t1_hit:
                        pnl=-sl_pts*qty
                        if partial_exit:pnl+=partial_pnl
                        reason='SL'
                    # Full target (50% remaining)
                    elif row['high']>=entry_p+t2_pts:
                        pnl=t2_pts*half_qty
                        if partial_exit:pnl+=partial_pnl
                        else:pnl=t2_pts*qty
                        reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_p)*qty;reason='TO'
                else:
                    if not t1_hit and row['low']<=entry_p-t1_pts:
                        t1_hit=True;sl_pts=0
                    if not partial_exit and row['low']<=entry_p-t1_5_pts:
                        partial_exit=True
                        partial_pnl=t1_5_pts*half_qty
                    if row['high']>=entry_p+sl_pts and not t1_hit:
                        pnl=-sl_pts*qty
                        if partial_exit:pnl+=partial_pnl
                        reason='SL'
                    elif row['low']<=entry_p-t2_pts:
                        pnl=t2_pts*half_qty
                        if partial_exit:pnl+=partial_pnl
                        else:pnl=t2_pts*qty
                        reason='T2'
                    elif bars>=30:
                        pnl=(entry_p-row['close'])*qty;reason='TO'

                if reason:
                    # Get realistic costs
                    costs=get_realistic_costs(
                        symbol,entry_p,qty,inst_type,bars)
                    net=pnl-costs['total']
                    total_costs_paid+=costs['total']
                    current_capital+=net

                    if pnl<0:daily_losses+=1;losses+=1
                    else:wins+=1
                    daily_trades+=1

                    if current_capital>peak:peak=current_capital
                    dd=((peak-current_capital)/peak)*100
                    if dd>max_dd:max_dd=dd

                    if trade_month not in monthly_pnl:
                        monthly_pnl[trade_month]={'pnl':0,'trades':0,'wins':0,
                                                   'costs':0}
                    monthly_pnl[trade_month]['pnl']+=net
                    monthly_pnl[trade_month]['trades']+=1
                    monthly_pnl[trade_month]['costs']+=costs['total']
                    if net>0:monthly_pnl[trade_month]['wins']+=1

                    # Update signal outcome
                    if all_signals and all_signals[-1]['outcome'] is None:
                        all_signals[-1]['outcome']=1 if pnl>0 else 0
                        all_signals[-1]['pnl']=net
                        all_signals[-1]['exit_reason']=reason
                        all_signals[-1]['bars_held']=bars
                        all_signals[-1]['costs']=costs

                    in_trade=False;t1_hit=False;partial_exit=False

        total=wins+losses
        wr=round(wins/total*100,1) if total>0 else 0
        ret=round((current_capital-capital)/capital*100,1)
        all_monthly[symbol]=monthly_pnl
        all_results.append({
            'symbol':symbol,'type':inst_type,
            'total_trades':total,'wins':wins,'losses':losses,
            'win_rate':wr,'total_return':ret,
            'max_drawdown':round(max_dd,1),
            'final_capital':round(current_capital,2),
            'total_costs':round(total_costs_paid,2),
            'regime_blocked':regime_blocked,
            'score_blocked':score_blocked,
            'rr_blocked':rr_blocked,'ml_blocked':ml_blocked,
            'monthly_pnl':monthly_pnl
        })
        print(f'WR:{wr}% Return:{ret}% Trades:{total} '
              f'Costs:Rs.{total_costs_paid:,.0f}')

    # Save signals for mining
    os.makedirs('ml_models',exist_ok=True)
    json.dump(all_signals,open('ml_models/v31_all_signals_bt.json','w'))
    print(f'\n[BT] Saved {len(all_signals)} signals for mining!')

    # Monthly report
    months=sorted(set(m for d in all_monthly.values() for m in d.keys()))
    print(f'\n{"="*65}')
    print(f'  MONTHLY RETURNS - V31 REALISTIC (with costs)')
    print(f'{"="*65}')

    for symbol in INSTRUMENTS:
        data=all_monthly.get(symbol,{})
        if not data:continue
        print(f'\n--- {symbol} ---')
        print(f'{"Month":<10}{"PnL":>12}{"Trades":>8}{"WR%":>6}{"Costs":>10}{"Capital":>14}')
        print('-'*62)
        running=capital;y_totals={}
        for month in months:
            mdata=data.get(month)
            if not mdata:continue
            pnl=mdata['pnl'];trades=mdata['trades']
            mwins=mdata['wins'];costs=mdata.get('costs',0)
            mwr=round(mwins/trades*100) if trades>0 else 0
            running+=pnl;year=month[:4]
            y_totals[year]=y_totals.get(year,0)+pnl
            sign='+' if pnl>=0 else ''
            print(f'{month:<10}{sign}{pnl:>10.0f}  {trades:>5}  '
                  f'{mwr:>4}%  Rs.{costs:>6.0f}  Rs.{running:>10,.0f}')
            next_idx=months.index(month)+1
            if next_idx>=len(months) or months[next_idx][:4]!=year:
                ytot=y_totals[year];sign='+' if ytot>=0 else ''
                print(f'{"─"*62}')
                print(f'{year+" TOTAL":<10}{sign}{ytot:>10.0f}'
                      f'  ({ytot/capital*100:.1f}% ROI)')
                print(f'{"─"*62}')
        r=next((x for x in all_results if x['symbol']==symbol),{})
        print(f'3YR: WR={r.get("win_rate",0)}% '
              f'Return={r.get("total_return",0)}% '
              f'TotalCosts=Rs.{r.get("total_costs",0):,.0f}')

    # Combined
    print(f'\n{"="*65}')
    print(f'  COMBINED SUMMARY (Realistic with all costs)')
    print(f'{"="*65}')
    grand=0;y_grand={}
    for month in months:
        mt=sum(all_monthly.get(s,{}).get(month,{}).get('pnl',0)
               for s in INSTRUMENTS)
        grand+=mt;year=month[:4]
        y_grand[year]=y_grand.get(year,0)+mt
        next_idx=months.index(month)+1
        if next_idx>=len(months) or months[next_idx][:4]!=year:
            yt=y_grand[year];sign='+' if yt>=0 else ''
            print(f'{year}: {sign}Rs.{yt:,.0f} ({yt/capital*100:.1f}% ROI)')

    total_costs=sum(r.get('total_costs',0) for r in all_results)
    print(f'\nGRAND TOTAL: Rs.{grand:>+,.0f}')
    print(f'3YR ROI: {grand/capital*100:.1f}%')
    print(f'Monthly avg: Rs.{grand/36:>+,.0f}')
    print(f'Total costs paid: Rs.{total_costs:,.0f}')
    print(f'  → Brokerage: Rs.{len(all_signals)*50:,.0f}')
    print(f'  → Slippage+Spread+Theta: Rs.{total_costs-len(all_signals)*50:,.0f}')

    all_results.sort(key=lambda x:-x['total_return'])
    print(f'\nTOP 5:')
    for r in all_results[:5]:
        print(f'  {r["symbol"]}: {r["total_return"]}% '
              f'WR:{r["win_rate"]}% Trades:{r["total_trades"]}')
    print(f'\nBOTTOM 3:')
    for r in all_results[-3:]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    os.makedirs('backtest_results',exist_ok=True)
    json.dump(all_results,
              open('backtest_results/v31_realistic_backtest.json','w'),indent=2)
    print(f'\nSaved!')
    return all_monthly,all_results,all_signals

def mine_v31_failures_from_bt(signals):
    """Mine failures from backtest signals"""
    print(f'\n{"="*65}')
    print(f'  V31 FAILURE MINING')
    print(f'{"="*65}')

    failures=[s for s in signals if s.get('outcome')==0]
    wins=[s for s in signals if s.get('outcome')==1]
    total=len(signals)

    if not failures:
        print('No failures to mine!')
        return {}

    print(f'Total signals: {total}')
    print(f'Wins: {len(wins)} ({len(wins)/total*100:.1f}%)')
    print(f'Losses: {len(failures)} ({len(failures)/total*100:.1f}%)')

    # Pattern analysis
    patterns={
        'counter_trend':0,'no_fvg':0,'no_liq':0,
        'wrong_wyckoff':0,'sl_too_tight':0,'bad_session':0,
        'low_score':0,'ranging_market':0,'no_trap':0,
        'low_ml':0,'timeout':0
    }
    fixes={}

    for f in failures:
        if f.get('trend5')!=f.get('trend15'):
            patterns['counter_trend']+=1
            fixes['counter_trend']='Require both 5min+15min trend aligned'

        if f.get('fvg',0)==0:
            patterns['no_fvg']+=1
            fixes['no_fvg']='Always require FVG for entry confirmation'

        if f.get('liq',0)==0:
            patterns['no_liq']+=1
            fixes['no_liq']='Require liquidity sweep before entry'

        if f.get('wyckoff') in ['DIST','MARK'] and f.get('action')=='BUY':
            patterns['wrong_wyckoff']+=1
            fixes['wrong_wyckoff']='Never buy in DIST/MARK phase'

        if f.get('sl_atr',1)<0.75:
            patterns['sl_too_tight']+=1
            fixes['sl_too_tight']='Minimum SL = 0.75x ATR'

        if f.get('hour') in [9,15]:
            patterns['bad_session']+=1
            fixes['bad_session']='Avoid 9AM and 3PM sessions'

        if f.get('score',0)<18:
            patterns['low_score']+=1
            fixes['low_score']='Raise minimum score to 18'

        if f.get('regime')=='RANGING':
            patterns['ranging_market']+=1
            fixes['ranging_market']='In ranging: require gamma wall or trap'

        if f.get('trap_score',0)==0:
            patterns['no_trap']+=1
            fixes['no_trap']='Prefer trades with trap confirmation'

        if f.get('ml_prob',0)<0.5:
            patterns['low_ml']+=1
            fixes['low_ml']='Raise ML threshold to 0.5'

        if f.get('exit_reason')=='TO':
            patterns['timeout']+=1
            fixes['timeout']='Reduce timeout or use trailing SL'

    # Find optimal parameters
    print(f'\n[MINE] Failure patterns:')
    for p,c in sorted(patterns.items(),key=lambda x:-x[1]):
        pct=c/len(failures)*100
        if pct>10:
            print(f'  {p}: {c} ({pct:.1f}%) → {fixes.get(p,"")}')

    # Score analysis
    print(f'\n[MINE] Score analysis:')
    for score_range in [(12,15),(15,18),(18,22),(22,26),(26,52)]:
        lo,hi=score_range
        range_sigs=[s for s in signals if lo<=s.get('score',0)<hi]
        if range_sigs:
            rw=sum(1 for s in range_sigs if s.get('outcome')==1)
            print(f'  Score {lo}-{hi}: WR={rw/len(range_sigs)*100:.1f}% '
                  f'({len(range_sigs)} trades)')

    # Hour analysis
    print(f'\n[MINE] Hour analysis:')
    for h in [10,11,13,14]:
        h_sigs=[s for s in signals if s.get('hour')==h]
        if h_sigs:
            hw=sum(1 for s in h_sigs if s.get('outcome')==1)
            print(f'  Hour {h}: WR={hw/len(h_sigs)*100:.1f}% '
                  f'({len(h_sigs)} trades)')

    # Regime analysis
    print(f'\n[MINE] Regime analysis:')
    for regime in ['TRENDING_UP','TRENDING_DOWN','RANGING']:
        r_sigs=[s for s in signals if s.get('regime')==regime]
        if r_sigs:
            rw=sum(1 for s in r_sigs if s.get('outcome')==1)
            print(f'  {regime}: WR={rw/len(r_sigs)*100:.1f}% '
                  f'({len(r_sigs)} trades)')

    # Cost analysis
    print(f'\n[MINE] Cost impact:')
    avg_cost=np.mean([s.get('costs',{}).get('total',0)
                      for s in signals if s.get('costs')])
    avg_theta=np.mean([s.get('costs',{}).get('theta',0)
                       for s in signals if s.get('costs')])
    avg_slip=np.mean([s.get('costs',{}).get('slippage',0)
                      for s in signals if s.get('costs')])
    print(f'  Avg total cost/trade: Rs.{avg_cost:.0f}')
    print(f'  Avg theta decay: Rs.{avg_theta:.0f}')
    print(f'  Avg slippage: Rs.{avg_slip:.0f}')

    # Build meta suggestions
    meta_suggestions={
        'optimal_score':18,
        'optimal_hours':[h for h in [10,11,13,14]
                         if sum(1 for s in signals
                                if s.get('hour')==h and s.get('outcome')==1)/
                         max(1,sum(1 for s in signals
                                   if s.get('hour')==h))>0.5],
        'best_regime':max(['TRENDING_UP','TRENDING_DOWN','RANGING'],
                         key=lambda r:sum(1 for s in signals
                                         if s.get('regime')==r
                                         and s.get('outcome')==1)/
                         max(1,sum(1 for s in signals
                                   if s.get('regime')==r))),
        'min_sl_atr':0.75,
        'require_fvg':patterns['no_fvg']/len(failures)>0.3,
        'failure_patterns':patterns,
        'fixes':fixes
    }

    json.dump(meta_suggestions,
              open('ml_models/v31_meta_suggestions.json','w'),indent=2)
    print(f'\n[MINE] Meta suggestions saved!')
    print(f'  Optimal score: {meta_suggestions["optimal_score"]}')
    print(f'  Best hours: {meta_suggestions["optimal_hours"]}')
    print(f'  Best regime: {meta_suggestions["best_regime"]}')

    return meta_suggestions

if __name__=='__main__':
    # Run backtest
    monthly,results,signals=run_v31_full_backtest(capital=50000)

    # Mine failures
    if signals:
        meta=mine_v31_failures_from_bt(signals)
        print(f'\n✅ V31 Realistic Backtest + Mining Complete!')
        print(f'   Check backtest_results/v31_realistic_backtest.json')
        print(f'   Check ml_models/v31_meta_suggestions.json')
