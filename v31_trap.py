import numpy as np
import logging
log=logging.getLogger(__name__)

def detect_liquidity_trap(df5,action,atr):
    """
    Liquidity Trap Detection:
    
    BREAKOUT TRAP (SELL setup):
    Price breaks above resistance
    BUT closes back below = TRAPPED BULLS
    → BUY PUT (SELL signal)
    
    BREAKDOWN TRAP (BUY setup):  
    Price breaks below support
    BUT closes back above = TRAPPED BEARS
    → BUY CALL (BUY signal)
    """
    try:
        h=df5['high'];l=df5['low'];c=df5['close'];v=df5['volume']
        last=df5.iloc[-1]
        prev=df5.iloc[-2] if len(df5)>1 else last

        # Key levels from recent structure
        lookback=min(30,len(df5)-5)
        resistance=float(h.iloc[-lookback:-1].max())
        support=float(l.iloc[-lookback:-1].min())

        # Equal highs/lows (liquidity pools)
        eq_high=None;eq_low=None
        highs=h.iloc[-lookback:-1].values
        lows=l.iloc[-lookback:-1].values

        # Find equal highs (within 0.1%)
        for i in range(len(highs)-1):
            for j in range(i+1,len(highs)):
                if abs(highs[i]-highs[j])/highs[j]<0.001:
                    eq_high=max(highs[i],highs[j])
                    break

        # Find equal lows (within 0.1%)
        for i in range(len(lows)-1):
            for j in range(i+1,len(lows)):
                if abs(lows[i]-lows[j])/lows[j]<0.001:
                    eq_low=min(lows[i],lows[j])
                    break

        vol_avg=float(v.rolling(20).mean().iloc[-1])
        vol_spike=float(last['volume'])>vol_avg*1.5

        trap_type=None
        trap_level=0
        trap_score=0

        # BREAKOUT TRAP (price swept above resistance/eq_high then closed back)
        check_levels=[resistance]
        if eq_high:check_levels.append(eq_high)

        for level in check_levels:
            if (float(last['high'])>level and
                float(last['close'])<level):
                # Classic breakout trap!
                trap_type='BREAKOUT_TRAP'
                trap_level=level
                trap_score=4
                if vol_spike:trap_score+=2  # Volume confirmed
                log.info(f'[TRAP] BREAKOUT TRAP at {level:.1f}! Score:{trap_score}')
                break

        # BREAKDOWN TRAP (price swept below support/eq_low then closed back)
        if not trap_type:
            check_levels=[support]
            if eq_low:check_levels.append(eq_low)

            for level in check_levels:
                if (float(last['low'])<level and
                    float(last['close'])>level):
                    trap_type='BREAKDOWN_TRAP'
                    trap_level=level
                    trap_score=4
                    if vol_spike:trap_score+=2
                    log.info(f'[TRAP] BREAKDOWN TRAP at {level:.1f}! Score:{trap_score}')
                    break

        # Programmatic trap (multi-candle)
        if not trap_type and len(df5)>=3:
            c1=df5.iloc[-3];c2=df5.iloc[-2];c3=df5.iloc[-1]

            # 3-candle breakout trap
            if (float(c2['high'])>resistance and
                float(c3['close'])<resistance and
                float(c3['close'])<float(c2['open'])):
                trap_type='PROGRAMMATIC_BREAKOUT'
                trap_level=resistance
                trap_score=3
                log.info(f'[TRAP] Programmatic breakout trap!')

            # 3-candle breakdown trap
            elif (float(c2['low'])<support and
                  float(c3['close'])>support and
                  float(c3['close'])>float(c2['open'])):
                trap_type='PROGRAMMATIC_BREAKDOWN'
                trap_level=support
                trap_score=3
                log.info(f'[TRAP] Programmatic breakdown trap!')

        if not trap_type:
            return None

        # Determine trade direction
        if trap_type in ['BREAKOUT_TRAP','PROGRAMMATIC_BREAKOUT']:
            trap_action='SELL'  # Trapped bulls → SELL
        else:
            trap_action='BUY'   # Trapped bears → BUY

        # Only return if trap matches our intended action
        if trap_action!=action:
            return None

        return {
            'type':trap_type,
            'level':trap_level,
            'score':trap_score,
            'vol_confirmed':vol_spike,
            'action':trap_action
        }

    except Exception as e:
        log.error(f'[TRAP] Error: {e}')
        return None

def get_trap_oi_score(symbol,current_price,action,df5):
    """
    OI Trap confirmation:
    Breakout + Call OI surge = TRAPPED BULLS → SELL
    Breakdown + Put OI surge = TRAPPED BEARS → BUY
    """
    try:
        from v31_gamma import get_gamma_walls
        walls=get_gamma_walls(symbol,current_price)
        if not walls:return 0

        call_oi=walls.get('call_oi',{})
        put_oi=walls.get('put_oi',{})
        if not call_oi or not put_oi:return 0

        step=100 if 'BANK' in symbol else 50
        atm=round(current_price/step)*step

        # ATM OI
        atm_call=sum(call_oi.get(atm+s,0) for s in [0,step,step*2])
        atm_put=sum(put_oi.get(atm-s,0) for s in [0,step,step*2])
        total_oi=atm_call+atm_put
        if total_oi==0:return 0

        call_pct=atm_call/total_oi
        put_pct=atm_put/total_oi

        oi_score=0

        # Breakout trap: Call OI dominant = retail bought calls = trap!
        if action=='SELL' and call_pct>0.65:
            oi_score=3
            log.info(f'[TRAP] OI confirms breakout trap! Call%={call_pct*100:.0f}%')

        # Breakdown trap: Put OI dominant = retail bought puts = trap!
        elif action=='BUY' and put_pct>0.65:
            oi_score=3
            log.info(f'[TRAP] OI confirms breakdown trap! Put%={put_pct*100:.0f}%')

        return oi_score

    except:return 0

def get_full_trap_score(symbol,df5,action,atr,current_price):
    """
    Complete trap scoring:
    Breakout/Breakdown trap: +4
    Volume confirmation: +2
    OI confirmation: +3
    Max: 9 pts
    """
    trap=detect_liquidity_trap(df5,action,atr)
    if not trap:return 0,None

    score=trap['score']

    # OI confirmation
    try:
        oi_score=get_trap_oi_score(symbol,current_price,action,df5)
        score+=oi_score
        trap['oi_score']=oi_score
    except:pass

    trap['total_score']=min(9,score)
    return trap['total_score'],trap
