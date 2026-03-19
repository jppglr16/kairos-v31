from v30_smc import get_smc_signal
from v30_momentum import get_momentum_signal,detect_market_condition
from v30_adaptive import AdaptiveEngine
from v30_ai import ai_analyze
from v30_cache import cached_vix
from v30_levels import analyze_levels,analyze_gap
from v30_ict import ict_analyze
from v30_volume_profile import get_vp_signal,get_ict_zones

from v30_rl import rl_should_trade,get_rl_agent
from v30_sizing import get_dynamic_lots,get_smart_sl
from v30_ml import extract_features
from datetime import datetime
adaptive=AdaptiveEngine()
def detect_fvg(df):
    for i in range(2,len(df)):
        p2=df.iloc[i-2];c=df.iloc[i]
        if c['low']>p2['high']:return {'type':'BULL_FVG','high':c['low'],'low':p2['high']}
        elif c['high']<p2['low']:return {'type':'BEAR_FVG','high':p2['low'],'low':c['high']}
    return None
def detect_liq_sweep(df):
    if len(df)<10:return None
    rh=df['high'].iloc[-10:-1].max();rl=df['low'].iloc[-10:-1].min();l=df.iloc[-1]
    if l['high']>rh and l['close']<rh:return 'BEAR_SWEEP'
    if l['low']<rl and l['close']>rl:return 'BULL_SWEEP'
    return None
def count_conf(smc,mom,fvg,liq,action):
    c=0
    if smc['action']==action:c+=smc['strength']
    if action=='BUY' and mom['momentum']=='BULLISH':c+=mom['strength']
    elif action=='SELL' and mom['momentum']=='BEARISH':c+=mom['strength']
    if fvg:
        if action=='BUY' and fvg['type']=='BULL_FVG':c+=2
        elif action=='SELL' and fvg['type']=='BEAR_FVG':c+=2
    if liq:
        if action=='BUY' and liq=='BULL_SWEEP':c+=3
        elif action=='SELL' and liq=='BEAR_SWEEP':c+=3
    if mom['vol_surge']:c+=2
    return c
def generate_signal(df5,df15,instrument,capital):
    now=datetime.now();h,m=now.hour,now.minute
    if instrument in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']:
        if not((h==9 and m>=25)or(10<=h<=14)or(h==15 and m<=15)):return None
    elif instrument in ['CRUDEOIL','GOLDM']:
        if not((h==9)or(10<=h<=11)or(h==15 and m>=30)or h>=16):return None
    smc=get_smc_signal(df5,df15);mom=get_momentum_signal(df5)
    market=detect_market_condition(df15);fvg=detect_fvg(df5);liq=detect_liq_sweep(df5)
    if not smc['action']:return None
    action=smc['action']
    against=(action=='BUY' and smc['trend15']=='DOWNTREND')or(action=='SELL' and smc['trend15']=='UPTREND')
    conf=count_conf(smc,mom,fvg,liq,action)
    if conf<(7 if against else 4):return None
    price=df5['close'].iloc[-1]
    # Apply all filters
    levels_ok,levels_info=analyze_levels(instrument,price,action)
    if not levels_ok:
        print(f"[LEVELS] {instrument} blocked: {levels_info}")
        return None
    gap=analyze_gap(df5,instrument)
    if gap and gap["gap_filling"] and action!=("SELL" if gap["gap_type"]=="GAP_UP" else "BUY"):
        return None
    filters_ok,filter_results=apply_all_filters(instrument,action,price)
    if not filters_ok:
        print(f'[STRATEGY] {instrument} filtered: {filter_results}')
        return None
    # FII warning reduces confidence
    if filter_results.get('fii_warning')=='AGAINST_FII':
        conf-=2
        if conf<4:return None
    # AI analysis
    ai=ai_analyze(df5,df15,instrument,smc,mom)
    if ai and ai['action']!=action:conf-=2
    if conf<(7 if against else 4):return None
    # RL agent decision
    features=extract_features(df5,df15)
    rl_action,rl_boost=rl_should_trade(instrument,features,action)
    if rl_action=='SKIP':
        print(f'[RL] {instrument} RL says SKIP')
        return None
    conf+=rl_boost
    # Greeks + best strike
    if instrument in ['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY']:
        option_type='CE' if action=='BUY' else 'PE'
        best_strike,best_premium=get_best_strike_by_delta(instrument,option_type,0.4)
        if best_strike:
            greeks_ok,greeks_info=check_greeks_filter(instrument,best_strike,option_type,price)
            if not greeks_ok:
                print(f'[GREEKS] {instrument} filtered: {greeks_info}')
                return None
    elif instrument in ['CRUDEOIL','GOLDM']:
        option_type='FUT';best_strike=None;best_premium=0
    else:
        option_type='CE' if action=='BUY' else 'PE'
        best_strike=None;best_premium=0
    from v30_sizing import get_dynamic_lots,get_smart_sl
    agent=get_rl_agent(instrument)
    sl,sl_type=get_smart_sl(df5,df15,instrument,action,smc,features,agent)
    p=adaptive.params.get(instrument,{})
    sl=atr*p.get('atr_sl_mult',1.5)
    rr=1.5 if market=='SIDEWAYS' else p.get('trending_target_rr',2.5)
    trailing=market!='SIDEWAYS' and mom['strength']>=2
    ai_confidence=ai['confidence'] if ai else 50
    signal={
        'instrument':instrument,'action':action,'option_type':option_type,
        'price':price,'sl_points':sl,'target1':sl*rr,'target2':sl*rr*1.5,
        'use_trailing':trailing,'hold_overnight':market!='SIDEWAYS' and mom['strength']>=2 and conf>=6,
        'market_condition':market,'smc_strength':smc['strength'],
        'momentum_strength':mom['strength'],'confirmation_count':conf,
        'against_trend':against,'rsi':mom['rsi'],'ai_confidence':ai_confidence,
        'best_strike':best_strike,'best_premium':best_premium,
        'pcr':ai['pcr'] if ai else None,'sentiment':ai['sentiment'] if ai else 0,
        'rl_boost':rl_boost,'features':features,'timestamp':str(now)
    }
    # ICT Analysis
    ict_score,ict_signals,ict_info=ict_analyze(df5,df15,action)
    conf+=ict_score
    # Volume Profile
    vp_score,vp_signals=get_vp_signal(df5,df15,action)
    conf+=vp_score
    # Require minimum ICT score
    if ict_score<2:
        return None
    # Brain check
    brain_ok,brain_reason=brain.should_trade(instrument,signal,now.hour)
    if not brain_ok:
        print(f"[BRAIN] {instrument} blocked: {brain_reason}")
        return None
    # Get optimized SL
    # Brain check
    brain_ok,brain_reason=brain.should_trade(instrument,signal,now.hour)
    if not brain_ok:
        print(f"[BRAIN] {instrument} blocked: {brain_reason}")
        return None
    # Get optimized SL
    if not adaptive.should_trade(signal,instrument):return None
    return signal

def generate_sideways_signal(df5,df15,instrument,capital):
    """Special strategy for sideways markets"""
    try:
        now=datetime.now()
        h=now.hour
        if h<10 or h>14:return None

        c=df5['close'];hi=df5['high'];lo=df5['low']
        atr=(hi-lo).tail(14).mean()

        # Define range
        range_high=hi.tail(20).max()
        range_low=lo.tail(20).min()
        range_size=range_high-range_low
        current=c.iloc[-1]

        # Only trade if range is meaningful
        if range_size<atr*3:return None

        # Position in range
        pos=(current-range_low)/range_size

        from v30_train_kairos import calc_rsi
        rsi=calc_rsi(c).iloc[-1]

        # Buy at bottom of range (30% level)
        if pos<=0.25 and rsi<40:
            action='BUY'
            sl=atr*1.5
            target=range_size*0.5  # 50% of range
        # Sell at top of range (70% level)
        elif pos>=0.75 and rsi>60:
            action='SELL'
            sl=atr*1.5
            target=range_size*0.5
        else:
            return None

        return {
            'instrument':instrument,
            'action':action,
            'option_type':'CE' if action=='BUY' else 'PE',
            'price':current,
            'sl_points':sl,
            'target1':target*0.5,
            'target2':target,
            'use_trailing':False,
            'hold_overnight':False,
            'market_condition':'SIDEWAYS',
            'confirmation_count':3,
            'kairos_score':10,
            'kairos_grade':'C_SIDEWAYS',
            'strategy':'RANGE_TRADE',
            'timestamp':str(now)
        }
    except:return None
