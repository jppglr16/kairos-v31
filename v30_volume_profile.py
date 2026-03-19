import numpy as np

def get_vp_signal(df5,df15,action):
    try:
        c=df15['close']
        v=df15['volume']
        vwap=(c*v).sum()/v.sum() if v.sum()>0 else c.mean()
        current=c.iloc[-1]
        score=0
        if action=='BUY' and current>vwap:score+=2
        elif action=='SELL' and current<vwap:score+=2
        return score,[]
    except:return 0,[]

def get_ict_zones(df):
    try:
        high=df['high'].max()
        low=df['low'].min()
        mid=(high+low)/2
        current=df['close'].iloc[-1]
        return {
            'equilibrium':mid,
            'premium':current>mid,
            'discount':current<mid,
            'ote_buy':False,
            'ote_sell':False
        }
    except:return None
