import requests
from datetime import datetime,timedelta
from v30_cache import cache

HEADERS={'User-Agent':'Mozilla/5.0','Accept':'application/json','Referer':'https://www.nseindia.com'}

def get_nse_session():
    s=requests.Session()
    s.get('https://www.nseindia.com',headers=HEADERS,timeout=10)
    return s

def get_key_levels(instrument):
    key=f'levels_{instrument}'
    v=cache.get(key)
    if v is not None:return v
    try:
        s=get_nse_session()
        sym={'NIFTY':'NIFTY 50','BANKNIFTY':'NIFTY BANK'}.get(instrument)
        if not sym:return {}
        r=s.get('https://www.nseindia.com/api/allIndices',headers=HEADERS,timeout=10)
        data=r.json()
        for idx in data.get('data',[]):
            if idx.get('index')==sym:
                current=float(idx.get('last',0))
                prev_close=float(idx.get('previousClose',0))
                year_high=float(idx.get('yearHigh',0))
                year_low=float(idx.get('yearLow',0))
                week_high=float(idx.get('weekHigh52',0))
                week_low=float(idx.get('weekLow52',0))
                levels={
                    'current':current,
                    'prev_close':prev_close,
                    'prev_high':prev_close*1.003,
                    'prev_low':prev_close*0.997,
                    'year_high':year_high,
                    'year_low':year_low,
                    'week_high':week_high,
                    'week_low':week_low,
                    # Pivot points
                    'pivot':(prev_close*1.003+prev_close*0.997+prev_close)/3,
                    'r1':2*((prev_close*1.003+prev_close*0.997+prev_close)/3)-prev_close*0.997,
                    'r2':(prev_close*1.003+prev_close*0.997+prev_close)/3+(prev_close*1.003-prev_close*0.997),
                    's1':2*((prev_close*1.003+prev_close*0.997+prev_close)/3)-prev_close*1.003,
                    's2':(prev_close*1.003+prev_close*0.997+prev_close)/3-(prev_close*1.003-prev_close*0.997),
                }
                cache.set(key,levels,3600)
                print(f'[LEVELS] {instrument} Pivot:{levels["pivot"]:.0f} R1:{levels["r1"]:.0f} S1:{levels["s1"]:.0f}')
                return levels
        return {}
    except Exception as e:
        print(f'[LEVELS] Error: {e}')
        return {}

def analyze_levels(instrument,current_price,action):
    levels=get_key_levels(instrument)
    if not levels:return True,{}
    result={}
    # Check if near resistance (for BUY) or support (for SELL)
    pivot=levels.get('pivot',0)
    r1=levels.get('r1',0)
    r2=levels.get('r2',0)
    s1=levels.get('s1',0)
    s2=levels.get('s2',0)
    year_high=levels.get('year_high',0)
    tolerance=0.002  # 0.2%
    result['pivot']=pivot
    result['r1']=r1;result['s1']=s1
    # Near resistance - avoid BUY
    if action=='BUY':
        if r1>0 and abs(current_price-r1)/r1<tolerance:
            return False,{**result,'reason':'AT_R1_RESISTANCE'}
        if r2>0 and abs(current_price-r2)/r2<tolerance:
            return False,{**result,'reason':'AT_R2_RESISTANCE'}
        if year_high>0 and abs(current_price-year_high)/year_high<tolerance:
            return False,{**result,'reason':'AT_YEAR_HIGH'}
        # Good BUY zone - near support
        if s1>0 and abs(current_price-s1)/s1<tolerance:
            result['at_support']=True
    # Near support - avoid SELL
    if action=='SELL':
        if s1>0 and abs(current_price-s1)/s1<tolerance:
            return False,{**result,'reason':'AT_S1_SUPPORT'}
        if s2>0 and abs(current_price-s2)/s2<tolerance:
            return False,{**result,'reason':'AT_S2_SUPPORT'}
        if year_high>0 and abs(current_price-year_high)/year_high<tolerance:
            result['at_resistance']=True
    return True,result

def analyze_gap(df5,instrument):
    try:
        if len(df5)<2:return None
        today_open=df5['open'].iloc[0]
        prev_close=df5['close'].iloc[-20] if len(df5)>=20 else df5['close'].iloc[0]
        gap_pct=((today_open-prev_close)/prev_close)*100
        if gap_pct>0.5:
            gap_type='GAP_UP'
        elif gap_pct<-0.5:
            gap_type='GAP_DOWN'
        else:
            gap_type='NO_GAP'
        # Gap fill probability
        current=df5['close'].iloc[-1]
        if gap_type=='GAP_UP' and current<today_open:
            gap_filling=True
        elif gap_type=='GAP_DOWN' and current>today_open:
            gap_filling=True
        else:
            gap_filling=False
        return {
            'gap_type':gap_type,
            'gap_pct':round(gap_pct,2),
            'gap_filling':gap_filling,
            'today_open':today_open,
            'bias':'BULLISH' if gap_type=='GAP_UP' and not gap_filling else
                   'BEARISH' if gap_type=='GAP_DOWN' and not gap_filling else
                   'REVERSAL'
        }
    except Exception as e:
        print(f'[GAP] Error: {e}')
        return None
