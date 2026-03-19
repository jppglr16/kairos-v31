import pandas as pd
def find_swing_highs(df,w=5):
    h=[]
    for i in range(w,len(df)-w):
        if df['high'].iloc[i]==df['high'].iloc[i-w:i+w+1].max():h.append((i,df['high'].iloc[i]))
    return h
def find_swing_lows(df,w=5):
    l=[]
    for i in range(w,len(df)-w):
        if df['low'].iloc[i]==df['low'].iloc[i-w:i+w+1].min():l.append((i,df['low'].iloc[i]))
    return l
def detect_bos(df):
    h=find_swing_highs(df);l=find_swing_lows(df)
    if len(h)<2 or len(l)<2:return 'SIDEWAYS'
    if h[-1][1]>h[-2][1] and l[-1][1]>l[-2][1]:return 'UPTREND'
    if h[-1][1]<h[-2][1] and l[-1][1]<l[-2][1]:return 'DOWNTREND'
    return 'SIDEWAYS'
def detect_choch(df):
    trend=detect_bos(df);r=df.tail(10)
    if trend=='UPTREND' and r['close'].iloc[-1]<r['low'].min():return 'BEARISH_CHOCH'
    if trend=='DOWNTREND' and r['close'].iloc[-1]>r['high'].max():return 'BULLISH_CHOCH'
    return None
def find_order_blocks(df,trend):
    obs=[]
    for i in range(len(df)-10,len(df)-1):
        c=df.iloc[i]
        if trend=='UPTREND' and c['close']<c['open']:obs.append({'type':'BULLISH_OB','high':c['high'],'low':c['low']})
        elif trend=='DOWNTREND' and c['close']>c['open']:obs.append({'type':'BEARISH_OB','high':c['high'],'low':c['low']})
    return obs[-1] if obs else None
def get_smc_signal(df5,df15):
    t5=detect_bos(df5);t15=detect_bos(df15);choch=detect_choch(df5)
    ob=find_order_blocks(df5,t15);price=df5['close'].iloc[-1]
    sig={'trend5':t5,'trend15':t15,'choch':choch,'ob':ob,'price':price,'action':None,'strength':0}
    if t5=='UPTREND' and t15=='UPTREND':sig['action']='BUY';sig['strength']=2
    elif t5=='DOWNTREND' and t15=='DOWNTREND':sig['action']='SELL';sig['strength']=2
    elif choch=='BULLISH_CHOCH' and ob and ob['type']=='BULLISH_OB' and ob['low']<=price<=ob['high']:sig['action']='BUY';sig['strength']=3
    elif choch=='BEARISH_CHOCH' and ob and ob['type']=='BEARISH_OB' and ob['low']<=price<=ob['high']:sig['action']='SELL';sig['strength']=3
    return sig
