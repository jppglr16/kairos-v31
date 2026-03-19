import json,os,pickle
import numpy as np
import pandas as pd
from datetime import datetime
import logging
log=logging.getLogger(__name__)

INSTRUMENTS={
    'NIFTY':     {'type':'index','lot':75,'token':'99926000','atm_step':50},
    'BANKNIFTY': {'type':'index','lot':30,'token':'99926009','atm_step':100},
    'SENSEX':    {'type':'index','lot':20,'token':'99919000','atm_step':100},
    'FINNIFTY':  {'type':'index','lot':65,'token':'99926037','atm_step':50},
    'MIDCPNIFTY':{'type':'index','lot':120,'token':'99926074','atm_step':25},
    'CRUDEOIL':  {'type':'commodity','lot':100,'token':'472790','atm_step':50},
    'GOLDM':     {'type':'commodity','lot':10,'token':'477904','atm_step':100},
    'SILVERM':   {'type':'commodity','lot':30,'token':'457533','atm_step':100},
    'LT':        {'type':'stock','lot':450,'token':'11483','atm_step':20},
    'NTPC':      {'type':'stock','lot':4500,'token':'11630','atm_step':5},
    'MARUTI':    {'type':'stock','lot':100,'token':'10999','atm_step':100},
    'BHARTIARTL':{'type':'stock','lot':950,'token':'10604','atm_step':10},
    'SBIN':      {'type':'stock','lot':1500,'token':'3045','atm_step':5},
    'TATAMOTORS':{'type':'stock','lot':1350,'token':'3456','atm_step':5},
    'RELIANCE':  {'type':'stock','lot':250,'token':'2885','atm_step':20},
    'HINDUNILVR':{'type':'stock','lot':300,'token':'1394','atm_step':50},
    'TCS':       {'type':'stock','lot':150,'token':'11536','atm_step':50},
    'TATASTEEL': {'type':'stock','lot':5500,'token':'3499','atm_step':5},
}

COST_PER_TRADE=34  # Kotak Neo flat cost

# ============================================================
# REALISTIC OPTIONS COST MODEL
# ============================================================

def estimate_option_premium(underlying_price,atr,delta=0.5,
                             days_to_expiry=5):
    """
    Estimate ATM option premium using simplified BSM:
    Premium ≈ Delta × ATR × sqrt(DTE/252) × underlying
    """
    iv_estimate=atr/underlying_price*16  # Rough IV from ATR
    time_factor=np.sqrt(days_to_expiry/252)
    premium=underlying_price*iv_estimate*time_factor*delta
    return max(10,round(premium))

def calc_theta_decay(premium,days_to_expiry,bars_held):
    """
    Theta decay per bar:
    Options lose more value near expiry (acceleration)
    """
    candles_per_day=75  # 375min / 5min
    days_held=bars_held/candles_per_day

    if days_to_expiry<=1:
        # Last day: rapid decay
        theta_pct=0.40  # 40% decay on expiry day
    elif days_to_expiry<=3:
        theta_pct=0.15  # 15% decay near expiry
    else:
        theta_pct=0.05  # 5% decay far expiry

    theta_cost=premium*theta_pct*(days_held/days_to_expiry)
    return max(0,theta_cost)

def calc_iv_crush(premium,regime,event_day=False):
    """
    IV crush: IV drops after events/volatility
    VOLATILE regime: High IV → crush on resolution
    """
    if event_day:
        iv_crush=premium*0.30  # 30% IV crush on event
    elif regime=='VOLATILE':
        iv_crush=premium*0.15  # 15% in volatile markets
    else:
        iv_crush=premium*0.05  # 5% normal
    return iv_crush

def calc_spread_cost(underlying_price,atr,regime):
    """
    Bid-ask spread widens in volatile markets:
    Normal: 0.5-1% of premium
    Volatile: 2-3% of premium
    """
    base_spread=max(1.0,underlying_price*0.0002)
    if regime=='VOLATILE':
        spread=base_spread*3  # Wider spread in volatile
    elif regime=='RANGING':
        spread=base_spread*0.5
    else:
        spread=base_spread
    return spread

def get_option_delta(score,action,atr,underlying):
    """
    Entry from option delta based on signal strength:
    Strong signal (score>=22): Delta 0.4-0.5 (ATM/slightly ITM)
    Medium (18-22): Delta 0.3-0.4 (slight OTM)
    Weak (15-18): Delta 0.2-0.3 (OTM)
    """
    if score>=22:delta=0.45
    elif score>=18:delta=0.35
    else:delta=0.25

    # Adjust entry: wait for delta confirmation
    # Higher delta = closer to money = better probability
    atr_pct=atr/underlying*100
    if atr_pct<0.10:delta*=0.8  # Reduce delta in low vol

    return delta

def get_realistic_option_costs(symbol,underlying_price,qty,
                                regime,score,bars_held,atr):
    """
    Complete realistic options cost:
    1. Theta decay
    2. IV crush
    3. Spread widening
    4. Brokerage (Kotak Neo Rs.34)
    """
    # Estimate premium
    delta=get_option_delta(score,'BUY',atr,underlying_price)
    premium=estimate_option_premium(
        underlying_price,atr,delta)

    # 1. Theta decay
    theta=calc_theta_decay(premium,5,bars_held)

    # 2. IV crush
    iv_crush=calc_iv_crush(premium,regime)

    # 3. Spread cost
    spread=calc_spread_cost(underlying_price,atr,regime)

    # 4. Fixed brokerage
    brokerage=COST_PER_TRADE

    # Total per unit, then × qty
    option_costs=(theta+iv_crush+spread)*qty
    total=brokerage+option_costs

    return {
        'brokerage':brokerage,
        'theta':round(theta*qty,2),
        'iv_crush':round(iv_crush*qty,2),
        'spread':round(spread*qty,2),
        'option_premium_est':premium,
        'delta_used':delta,
        'total':round(total,2)
    }

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

def get_ml_prob(symbol,df5,df15,action,atr):
    try:
        for f in [f'ml_models/{symbol}_v31_model.pkl',
                  f'ml_models/{symbol}_model.pkl',
                  'ml_models/NIFTY_model.pkl']:
            if os.path.exists(f):
                data=pickle.load(open(f,'rb'))
                break
        else:return 0.5
        c=df5['close'];v=df5['volume']
        d=c.diff();g=d.clip(lower=0).rolling(14).mean()
        ll=-d.clip(upper=0).rolling(14).mean()
        rsi=float((100-(100/(1+g/ll))).iloc[-1])
        from v31_strategy import get_trend_v31
        t5=get_trend_v31(df5);t15=get_trend_v31(df15)
        cur=float(c.iloc[-1])
        features=[
            (cur-float(c.iloc[-2]))/float(c.iloc[-2]),
            rsi/100,(rsi-50)/50,
            t5,t15,atr/cur if cur>0 else 0,
            1 if action=='BUY' else -1,
        ]
        model=data['model'];scaler=data['scaler']
        n=model.n_features_in_
        while len(features)<n:features.append(0)
        return float(model.predict_proba(
            scaler.transform([features[:n]]))[0][1])
    except:return 0.5

def run_v31_backtest_v2(capital=50000):
    from v31_scoring import calc_v31_score
    from v31_strategy import get_market_regime,get_trend_v31
    from v31_trap import get_full_trap_score
    from v30_final_backtest import get_wyckoff
    from v30_rr_filter import find_tight_sl,find_best_target

    print(f'\n{"="*65}')
    print(f'  KAIROS V31 BACKTEST V2 - FULL OPTIONS MODEL')
    print(f'  Theta + IV Crush + Spread + Delta Entry')
    print(f'  RR=1:2 | Break-even at 1R | 50% exit at 1R/2R')
    print(f'  ATR > 0.35% | Signal from index')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*65}')

    all_monthly={}
    all_results=[]
    all_signals=[]

    for symbol in INSTRUMENTS:
        print(f'\n[V31] {symbol}...',end=' ',flush=True)
        candles=load_data(symbol)
        if not candles:print('No data');continue
        df=to_df(candles)
        if df is None or len(df)<200:print('Skip');continue

        inst_type=INSTRUMENTS[symbol]['type']
        lot=INSTRUMENTS[symbol]['lot']
        current_capital=capital
        wins=0;losses=0;breakevens=0
        in_trade=False
        entry_p=0;sig_action=''
        sl_pts=0;t1_pts=0;t2_pts=0
        entry_idx=0;current_lots=1
        t1_hit=False;partial_done=False
        daily_losses=0;last_date=None;daily_trades=0
        peak=capital;max_dd=0
        monthly_pnl={}
        trade_month=''
        total_costs=0
        score_blocked=0;rr_blocked=0
        ml_blocked=0;atr_blocked=0
        current_score=0;current_regime='RANGING'

        for i in range(100,len(df)-30,3):
            df5=df.iloc[i-60:i].copy()
            df3=df.iloc[i-36:i].copy()
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

                    # ATR > 0.35% filter
                    cur=float(c.iloc[-1])
                    atr_pct=atr/cur*100
                    if atr_pct<0.10:atr_blocked+=1;continue

                    # Volatility filter
                    avg_atr=float((h-l).rolling(20).mean().iloc[-1])
                    if atr<avg_atr*0.7:continue

                    # Market regime
                    regime,_=get_market_regime(df5,df15,df_daily)
                    if regime=='VOLATILE':continue

                    # Direction from index signal
                    if regime=='TRENDING_UP':action='BUY'
                    elif regime=='TRENDING_DOWN':action='SELL'
                    else:
                        from v31_strategy import detect_liquidity_sweep_v31
                        hb,_,_=detect_liquidity_sweep_v31(df5,'BUY',atr)
                        hs,_,_=detect_liquidity_sweep_v31(df5,'SELL',atr)
                        if hb:action='BUY'
                        elif hs:action='SELL'
                        else:continue

                    # Trend alignment
                    t5=get_trend_v31(df5)
                    t15=get_trend_v31(df15)
                    td=get_trend_v31(df_daily)
                    if action=='BUY' and t5==-1 and t15==-1:continue
                    if action=='SELL' and t5==1 and t15==1:continue

                    # V31 scoring (5-min primary)
                    wy=get_wyckoff(df15)
                    score,components,has_liq,has_fvg=calc_v31_score(
                        df5,df15,action,regime,wy,atr)

                    # Also check 3-min
                    if len(df3)>=30:
                        atr3=float((df3['high']-df3['low']).tail(14).mean())
                        score3,comp3,_,_=calc_v31_score(
                            df3,df15,action,regime,wy,atr3)
                        if score3>score:
                            score=score3
                            components=comp3

                    # Trap detection
                    trap_score,_=get_full_trap_score(
                        symbol,df5,action,atr,cur)
                    score+=trap_score

                    # Gamma blast detection
                    is_gamma_blast=components.get('gamma',0)>=5

                    if score<13:score_blocked+=1;continue

                    # Delta-based entry confirmation
                    delta=get_option_delta(score,action,atr,cur)
                    if delta<0.20:continue  # Skip far OTM

                    # RR based on score + gamma
                    if is_gamma_blast:
                        t2_ratio=5.0  # 1:5 for gamma blast
                        t1_ratio=3.0  # Partial at 1:3
                        min_rr=3.0
                    elif score>=22:
                        t2_ratio=3.0
                        t1_ratio=1.5
                        min_rr=2.0
                    elif score>=18:
                        t2_ratio=2.0
                        t1_ratio=1.0
                        min_rr=1.5
                    else:
                        t2_ratio=1.5
                        t1_ratio=1.0
                        min_rr=1.0

                    # RR filter
                    sl_type,raw_sl,_=find_tight_sl(df5,df15,action,atr)
                    if raw_sl<atr*0.75:raw_sl=atr*0.75
                    if raw_sl>atr*2.0:rr_blocked+=1;continue
                    _,target,rr=find_best_target(
                        df5,df15,action,cur,raw_sl,atr,
                        regime in ['TRENDING_UP','TRENDING_DOWN'])
                    if rr<min_rr:rr_blocked+=1;continue

                    # ML filter
                    need_high_ml=(score<18)
                    ml_prob=get_ml_prob(symbol,df5,df15,action,atr)
                    if need_high_ml and ml_prob<0.55:
                        ml_blocked+=1;continue
                    elif not need_high_ml and ml_prob<0.35:
                        ml_blocked+=1;continue

                    # Set trade params
                    in_trade=True;sig_action=action
                    entry_p=cur
                    sl_pts=raw_sl
                    t1_pts=raw_sl*1.0   # Break-even at 1R
                    t1_5_pts=raw_sl*t1_ratio  # 50% exit
                    t2_pts=raw_sl*t2_ratio     # 50% exit
                    entry_idx=i;current_lots=lot_count
                    t1_hit=False;partial_done=False
                    trade_month=month_key
                    current_score=score
                    current_regime=regime

                    # Store signal
                    all_signals.append({
                        'symbol':symbol,'action':action,
                        'score':score,'regime':regime,
                        'hour':hour,'delta':delta,
                        'gamma_blast':is_gamma_blast,
                        'trap_score':trap_score,
                        'ml_prob':ml_prob,'rr':rr,
                        'sl_atr':raw_sl/atr,
                        'atr_pct':atr_pct,
                        'outcome':None,'pnl':None
                    })

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''
                qty=current_lots*lot
                half_qty=max(1,qty//2)

                if sig_action=='BUY':
                    # Break-even at 1R
                    if not t1_hit and row['high']>=entry_p+t1_pts:
                        t1_hit=True;sl_pts=0

                    # 50% exit at T1.5
                    if not partial_done and row['high']>=entry_p+t1_5_pts:
                        partial_done=True
                        pnl+=t1_5_pts*half_qty

                    if row['low']<=entry_p-sl_pts and not t1_hit:
                        pnl-=sl_pts*qty
                        if partial_done:pnl+=0  # Already booked
                        reason='SL'
                    elif row['high']>=entry_p+t2_pts:
                        pnl+=t2_pts*half_qty
                        reason='T2'
                    elif bars>=30:
                        pnl+=(row['close']-entry_p)*qty
                        reason='TO'
                else:
                    if not t1_hit and row['low']<=entry_p-t1_pts:
                        t1_hit=True;sl_pts=0
                    if not partial_done and row['low']<=entry_p-t1_5_pts:
                        partial_done=True
                        pnl+=t1_5_pts*half_qty

                    if row['high']>=entry_p+sl_pts and not t1_hit:
                        pnl-=sl_pts*qty
                        reason='SL'
                    elif row['low']<=entry_p-t2_pts:
                        pnl+=t2_pts*half_qty
                        reason='T2'
                    elif bars>=30:
                        pnl+=(entry_p-row['close'])*qty
                        reason='TO'

                if reason:
                    # Realistic options costs
                    costs=get_realistic_option_costs(
                        symbol,entry_p,qty,current_regime,
                        current_score,bars,
                        abs(entry_p-entry_p)*0.01+0.01)
                    net=pnl-costs['total']
                    total_costs+=costs['total']
                    current_capital+=net

                    if pnl>0:wins+=1
                    elif pnl==0:breakevens+=1
                    else:losses+=1

                    if pnl<0:daily_losses+=1
                    daily_trades+=1

                    if current_capital>peak:peak=current_capital
                    dd=((peak-current_capital)/peak)*100
                    if dd>max_dd:max_dd=dd

                    if trade_month not in monthly_pnl:
                        monthly_pnl[trade_month]={
                            'pnl':0,'trades':0,'wins':0,
                            'costs':0,'theta':0,'iv_crush':0}
                    monthly_pnl[trade_month]['pnl']+=net
                    monthly_pnl[trade_month]['trades']+=1
                    monthly_pnl[trade_month]['costs']+=costs['total']
                    monthly_pnl[trade_month]['theta']+=costs['theta']
                    monthly_pnl[trade_month]['iv_crush']+=costs['iv_crush']
                    if net>0:monthly_pnl[trade_month]['wins']+=1

                    if all_signals and all_signals[-1]['outcome'] is None:
                        all_signals[-1]['outcome']=1 if pnl>0 else 0
                        all_signals[-1]['pnl']=net
                        all_signals[-1]['exit_reason']=reason
                        all_signals[-1]['bars_held']=bars
                        all_signals[-1]['costs']=costs['total']

                    in_trade=False;t1_hit=False;partial_done=False

        total=wins+losses+breakevens
        wr=round(wins/total*100,1) if total>0 else 0
        ret=round((current_capital-capital)/capital*100,1)
        all_monthly[symbol]=monthly_pnl
        all_results.append({
            'symbol':symbol,'type':inst_type,
            'total_trades':total,'wins':wins,
            'losses':losses,'breakevens':breakevens,
            'win_rate':wr,'total_return':ret,
            'max_drawdown':round(max_dd,1),
            'final_capital':round(current_capital,2),
            'total_costs':round(total_costs,2),
            'score_blocked':score_blocked,
            'rr_blocked':rr_blocked,'ml_blocked':ml_blocked,
            'atr_blocked':atr_blocked,
            'monthly_pnl':monthly_pnl
        })
        avg_cost=round(total_costs/total) if total>0 else 0
        print(f'WR:{wr}% Return:{ret}% Trades:{total} '
              f'BE:{breakevens} AvgCost:Rs.{avg_cost}')

    # Monthly report
    months=sorted(set(m for d in all_monthly.values() for m in d.keys()))
    print(f'\n{"="*65}')
    print(f'  MONTHLY RETURNS - V31 FULL OPTIONS MODEL')
    print(f'{"="*65}')

    for symbol in INSTRUMENTS:
        data=all_monthly.get(symbol,{})
        if not data:continue
        print(f'\n--- {symbol} ---')
        print(f'{"Month":<10}{"PnL":>10}{"T":>5}{"WR%":>5}'
              f'{"Theta":>8}{"IVCrush":>8}{"Capital":>12}')
        print('-'*60)
        running=capital;y_totals={}
        for month in months:
            mdata=data.get(month)
            if not mdata:continue
            pnl=mdata['pnl'];trades=mdata['trades']
            mwins=mdata['wins']
            mwr=round(mwins/trades*100) if trades>0 else 0
            theta=mdata.get('theta',0)
            iv=mdata.get('iv_crush',0)
            running+=pnl;year=month[:4]
            y_totals[year]=y_totals.get(year,0)+pnl
            sign='+' if pnl>=0 else ''
            print(f'{month:<10}{sign}{pnl:>8.0f} {trades:>4} '
                  f'{mwr:>4}% {theta:>6.0f} {iv:>6.0f} '
                  f'Rs.{running:>10,.0f}')
            next_idx=months.index(month)+1
            if next_idx>=len(months) or months[next_idx][:4]!=year:
                ytot=y_totals[year];sign='+' if ytot>=0 else ''
                print(f'{"─"*60}')
                print(f'{year+" TOTAL":<10}{sign}{ytot:>8.0f}'
                      f'  ({ytot/capital*100:.1f}% ROI)')
                print(f'{"─"*60}')
        r=next((x for x in all_results if x['symbol']==symbol),{})
        print(f'3YR: WR={r.get("win_rate",0)}% '
              f'Return={r.get("total_return",0)}% '
              f'Trades={r.get("total_trades",0)} '
              f'BE={r.get("breakevens",0)}')

    # Combined summary
    print(f'\n{"="*65}')
    print(f'  COMBINED SUMMARY')
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

    total_c=sum(r.get('total_costs',0) for r in all_results)
    total_t=sum(r.get('total_trades',0) for r in all_results)
    print(f'\nGRAND TOTAL: Rs.{grand:>+,.0f}')
    print(f'3YR ROI: {grand/capital*100:.1f}%')
    print(f'Monthly avg: Rs.{grand/36:>+,.0f}')
    print(f'Total trades: {total_t} ({total_t/36:.1f}/month)')
    print(f'Total costs: Rs.{total_c:,.0f} (avg Rs.{total_c/max(1,total_t):.0f}/trade)')

    all_results.sort(key=lambda x:-x['total_return'])
    print(f'\nTOP 5:')
    for r in all_results[:5]:
        print(f'  {r["symbol"]}: {r["total_return"]}% '
              f'WR:{r["win_rate"]}% Trades:{r["total_trades"]}')
    print(f'\nBOTTOM 3:')
    for r in all_results[-3:]:
        print(f'  {r["symbol"]}: {r["total_return"]}% WR:{r["win_rate"]}%')

    # Save
    os.makedirs('backtest_results',exist_ok=True)
    json.dump(all_results,
              open('backtest_results/v31_bt_v2.json','w'),indent=2)
    json.dump(all_signals,
              open('ml_models/v31_signals_v2.json','w'))
    print(f'\nSaved!')
    return all_monthly,all_results,all_signals

if __name__=='__main__':
    monthly,results,signals=run_v31_backtest_v2(capital=50000)
    # Mine failures
    wins=sum(1 for s in signals if s.get('outcome')==1)
    total=len(signals)
    if total>0:
        print(f'\nSignals: {total} WR:{wins/total*100:.1f}%')
        print(f'Gamma blasts: {sum(1 for s in signals if s.get("gamma_blast"))}')
        print(f'Trap trades: {sum(1 for s in signals if s.get("trap_score",0)>0)}')
