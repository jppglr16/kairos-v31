import numpy as np
import pandas as pd
from datetime import datetime

def get_kill_zone():
    now=datetime.now()
    h,m=now.hour,now.minute
    t=h*60+m
    # Asian: 2:30-5:30 AM IST
    if 150<=t<=330:return 'ASIAN',1
    # London: 6:30-9:30 AM IST  
    elif 390<=t<=570:return 'LONDON',3
    # NSE Open: 9:15-11:00 AM IST
    elif 555<=t<=660:return 'NSE_OPEN',5
    # London Close/NY: 1:00-2:30 PM IST
    elif 780<=t<=870:return 'LONDON_NY',4
    # NY Close: 8:00-10:00 PM IST
    elif 1200<=t<=1320:return 'NY_CLOSE',2
    return 'NO_KILL_ZONE',0

def get_premium_discount(df):
    try:
        swing_high=df['high'].tail(50).max()
        swing_low=df['low'].tail(50).min()
        current=df['close'].iloc[-1]
        total_range=swing_high-swing_low
        if total_range<=0:return 'EQUILIBRIUM',50
        position=((current-swing_low)/total_range)*100
        if position>62:return 'PREMIUM',position
        elif position<38:return 'DISCOUNT',position
        return 'EQUILIBRIUM',position
    except:return 'EQUILIBRIUM',50

def get_ote_zone(df,action):
    try:
        if action=='BUY':
            swing_high=df['high'].tail(20).max()
            swing_low=df['low'].tail(20).min()
            fib_range=swing_high-swing_low
            ote_low=swing_high-(fib_range*0.79)
            ote_high=swing_high-(fib_range*0.62)
            current=df['close'].iloc[-1]
            in_ote=ote_low<=current<=ote_high
            return in_ote,round(ote_low,1),round(ote_high,1)
        else:
            swing_high=df['high'].tail(20).max()
            swing_low=df['low'].tail(20).min()
            fib_range=swing_high-swing_low
            ote_low=swing_low+(fib_range*0.62)
            ote_high=swing_low+(fib_range*0.79)
            current=df['close'].iloc[-1]
            in_ote=ote_low<=current<=ote_high
            return in_ote,round(ote_low,1),round(ote_high,1)
    except:return False,0,0

def get_imbalance(df):
    try:
        imbalances=[]
        for i in range(2,len(df)):
            p2=df.iloc[i-2]
            c=df.iloc[i]
            # Bullish imbalance (FVG up)
            if c['low']>p2['high']:
                imbalances.append({
                    'type':'BULL',
                    'high':c['low'],
                    'low':p2['high'],
                    'mid':(c['low']+p2['high'])/2
                })
            # Bearish imbalance (FVG down)
            elif c['high']<p2['low']:
                imbalances.append({
                    'type':'BEAR',
                    'high':p2['low'],
                    'low':c['high'],
                    'mid':(p2['low']+c['high'])/2
                })
        return imbalances[-3:] if imbalances else []
    except:return []

def get_breaker_block(df,action):
    try:
        # Find failed order blocks
        highs=df['high'].values
        lows=df['low'].values
        closes=df['close'].values
        for i in range(len(df)-10,len(df)-1):
            if action=='BUY':
                # Bearish OB that got broken = breaker (now support)
                if closes[i]<df['open'].values[i]:
                    if closes[-1]>highs[i]:
                        return {
                            'type':'BULL_BREAKER',
                            'high':highs[i],
                            'low':lows[i]
                        }
            else:
                # Bullish OB that got broken = breaker (now resistance)
                if closes[i]>df['open'].values[i]:
                    if closes[-1]<lows[i]:
                        return {
                            'type':'BEAR_BREAKER',
                            'high':highs[i],
                            'low':lows[i]
                        }
        return None
    except:return None

def get_weekly_monthly_levels(df):
    try:
        if len(df)<100:return {}
        # Weekly levels (last 5 days = ~75 candles in 5min)
        week_data=df.tail(75)
        week_high=week_data['high'].max()
        week_low=week_data['low'].min()
        # Monthly levels (last 22 days = ~330 candles)
        month_data=df.tail(min(330,len(df)))
        month_high=month_data['high'].max()
        month_low=month_data['low'].min()
        return {
            'week_high':round(week_high,1),
            'week_low':round(week_low,1),
            'month_high':round(month_high,1),
            'month_low':round(month_low,1),
        }
    except:return {}

def ict_analyze(df5,df15,action):
    try:
        score=0
        signals=[]
        # Kill zone
        kz,kz_score=get_kill_zone()
        score+=kz_score
        if kz_score>=4:signals.append(f'KILL_ZONE_{kz}')
        # Premium/Discount
        pd_zone,pd_pos=get_premium_discount(df15)
        if action=='BUY' and pd_zone=='DISCOUNT':
            score+=3;signals.append('DISCOUNT_ZONE')
        elif action=='SELL' and pd_zone=='PREMIUM':
            score+=3;signals.append('PREMIUM_ZONE')
        elif pd_zone=='EQUILIBRIUM':
            score+=1
        else:
            score-=2;signals.append('WRONG_ZONE')
        # OTE
        in_ote,ote_low,ote_high=get_ote_zone(df15,action)
        if in_ote:
            score+=4;signals.append('IN_OTE_ZONE')
        # Imbalance
        imbalances=get_imbalance(df5)
        current=df5['close'].iloc[-1]
        for imb in imbalances:
            if action=='BUY' and imb['type']=='BULL':
                if imb['low']<=current<=imb['high']:
                    score+=3;signals.append('IN_BULL_IMBALANCE')
            elif action=='SELL' and imb['type']=='BEAR':
                if imb['low']<=current<=imb['high']:
                    score+=3;signals.append('IN_BEAR_IMBALANCE')
        # Breaker block
        breaker=get_breaker_block(df5,action)
        if breaker:
            score+=2;signals.append(f'BREAKER_{breaker["type"]}')
        # Weekly/Monthly levels
        levels=get_weekly_monthly_levels(df15)
        if levels:
            if action=='BUY':
                if levels.get('week_low',0)>0:
                    dist=abs(current-levels['week_low'])/current
                    if dist<0.005:score+=2;signals.append('AT_WEEK_LOW')
            else:
                if levels.get('week_high',0)>0:
                    dist=abs(current-levels['week_high'])/current
                    if dist<0.005:score+=2;signals.append('AT_WEEK_HIGH')
        return score,signals,{
            'kill_zone':kz,
            'pd_zone':pd_zone,
            'pd_position':pd_pos,
            'in_ote':in_ote,
            'imbalances':len(imbalances),
            'breaker':breaker is not None
        }
    except Exception as e:
        print(f'[ICT] Error: {e}')
        return 0,[],{}
