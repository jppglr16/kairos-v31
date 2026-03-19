import pandas as pd
def calc_rsi(s,p=14):
    d=s.diff();g=d.clip(lower=0).rolling(p).mean();l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))
def calc_macd(s,f=12,sl=26,sg=9):
    ef=s.ewm(span=f).mean();es=s.ewm(span=sl).mean();m=ef-es;sig=m.ewm(span=sg).mean()
    return m,sig,m-sig
def get_momentum_signal(df):
    c=df['close'];v=df['volume']
    rsi=calc_rsi(c).iloc[-1];m,sig,hist=calc_macd(c)
    mv=m.iloc[-1];sv=sig.iloc[-1];hv=hist.iloc[-1]
    vs=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
    r={'rsi':rsi,'macd':mv,'macd_signal':sv,'macd_hist':hv,'vol_surge':vs,'momentum':None,'strength':0,'overbought':rsi>70,'oversold':rsi<30}
    if rsi>50 and mv>sv and hv>0:r['momentum']='BULLISH';r['strength']=1+(1 if vs else 0)+(1 if rsi>60 else 0)
    elif rsi<50 and mv<sv and hv<0:r['momentum']='BEARISH';r['strength']=1+(1 if vs else 0)+(1 if rsi<40 else 0)
    return r
def detect_market_condition(df15):
    h=df15['high'].tail(20).max();l=df15['low'].tail(20).min();c=df15['close'].iloc[-1]
    atr=(df15['high']-df15['low']).tail(14).mean()
    if h-l<atr*3:return 'SIDEWAYS'
    return 'UPTREND' if c>(h+l)/2 else 'DOWNTREND'
