import json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

LOT_SIZES={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SENSEX':10}
MARGINS={'NIFTY':6000,'BANKNIFTY':5000,'FINNIFTY':3000,'MIDCPNIFTY':2000,'CRUDEOIL':4000,'GOLDM':3000,'SENSEX':5000}

def get_dynamic_lots(capital,instrument,sl_points):
    try:
        lot=LOT_SIZES.get(instrument,25)
        margin=MARGINS.get(instrument,5000)
        # Risk based sizing
        if capital<50000:
            risk_amt=2500
        elif capital<200000:
            risk_amt=capital*0.05
        else:
            risk_amt=capital*0.03
        # SL based sizing
        sl_risk=sl_points*lot
        lots_by_risk=max(1,int(risk_amt/sl_risk)) if sl_risk>0 else 1
        # Margin based sizing
        lots_by_margin=max(1,int(capital*0.3/margin))
        # Take minimum for safety
        final_lots=min(lots_by_risk,lots_by_margin)
        # Cap at 5 lots max
        final_lots=min(final_lots,5)
        total_qty=final_lots*lot
        log.info(f'[SIZING] {instrument} Capital:{capital:.0f} SL:{sl_points:.0f} Lots:{final_lots} Qty:{total_qty}')
        return final_lots,total_qty
    except Exception as e:
        log.error(f'[SIZING] Error: {e}')
        return 1,LOT_SIZES.get(instrument,25)

def get_smart_sl(df5,df15,instrument,action,smc_signal,ml_features=None,rl_agent=None):
    try:
        price=df5['close'].iloc[-1]
        atr=(df5['high']-df5['low']).tail(14).mean()
        sl_candidates=[]

        # 1. SMC based SL - below/above order block
        ob=smc_signal.get('ob')
        if ob:
            if action=='BUY' and ob['type']=='BULLISH_OB':
                smc_sl=price-ob['low']
                if 0<smc_sl<atr*3:
                    sl_candidates.append(('SMC_OB',smc_sl))
            elif action=='SELL' and ob['type']=='BEARISH_OB':
                smc_sl=ob['high']-price
                if 0<smc_sl<atr*3:
                    sl_candidates.append(('SMC_OB',smc_sl))

        # 2. Swing high/low SL
        if action=='BUY':
            swing_low=df5['low'].tail(10).min()
            swing_sl=price-swing_low
            if 0<swing_sl<atr*3:
                sl_candidates.append(('SWING',swing_sl))
        else:
            swing_high=df5['high'].tail(10).max()
            swing_sl=swing_high-price
            if 0<swing_sl<atr*3:
                sl_candidates.append(('SWING',swing_sl))

        # 3. ATR based SL
        atr_sl=atr*1.5
        sl_candidates.append(('ATR',atr_sl))

        # 4. FVG based SL
        for i in range(len(df5)-3,len(df5)-1):
            p2=df5.iloc[i-2];c=df5.iloc[i]
            if action=='BUY' and c['low']>p2['high']:
                fvg_sl=price-p2['high']
                if 0<fvg_sl<atr*3:
                    sl_candidates.append(('FVG',fvg_sl))
                    break
            elif action=='SELL' and c['high']<p2['low']:
                fvg_sl=p2['low']-price
                if 0<fvg_sl<atr*3:
                    sl_candidates.append(('FVG',fvg_sl))
                    break

        # 5. RL suggested SL
        if rl_agent:
            episodes=rl_agent.state.get('episodes',0)
            if episodes>20:
                rl_sl=atr*(0.8+rl_agent.state.get('epsilon',1)*0.7)
                sl_candidates.append(('RL',rl_sl))

        if not sl_candidates:
            return atr*1.5,'ATR_DEFAULT'

        # Choose best SL
        # Priority: SMC > FVG > SWING > ATR > RL
        priority={'SMC_OB':1,'FVG':2,'SWING':3,'ATR':4,'RL':5}
        sl_candidates.sort(key=lambda x:priority.get(x[0],9))
        best_type,best_sl=sl_candidates[0]

        # Validate SL - not too tight or too wide
        min_sl=atr*0.5
        max_sl=atr*3.0
        best_sl=max(min_sl,min(best_sl,max_sl))

        log.info(f'[SL] {instrument} {action} SL:{best_sl:.0f} Type:{best_type} Candidates:{[(t,round(s,0)) for t,s in sl_candidates]}')
        return best_sl,best_type

    except Exception as e:
        log.error(f'[SL] Error: {e}')
        atr=(df5['high']-df5['low']).tail(14).mean()
        return atr*1.5,'ATR_FALLBACK'
