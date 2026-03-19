from v30_rr_filter import apply_rr_filter
import json,os,pickle
import numpy as np
import pandas as pd

INSTRUMENTS={
    "NIFTY":     {"type":"index","lot":75,"token":"99926000"},
    "BANKNIFTY": {"type":"index","lot":30,"token":"99926009"},
    "SENSEX":    {"type":"index","lot":10,"token":"99919000"},
    "FINNIFTY":  {"type":"index","lot":65,"token":"99926037"},
    "MIDCPNIFTY":{"type":"index","lot":120,"token":"99926074"},
    "CRUDEOIL":  {"type":"commodity","lot":100,"token":"472790"},
    "GOLDM":     {"type":"commodity","lot":10,"token":"477904"},
    "SILVERM":   {"type":"commodity","lot":30,"token":"457533"},
    "LT":        {"type":"stock","lot":450,"token":"11483"},
    "NTPC":      {"type":"stock","lot":4500,"token":"11630"},
    "MARUTI":    {"type":"stock","lot":100,"token":"10999"},
    "BHARTIARTL":{"type":"stock","lot":950,"token":"10604"},
    "SBIN":      {"type":"stock","lot":1500,"token":"3045"},
    "TATAMOTORS":{"type":"stock","lot":1350,"token":"3456"},
    "RELIANCE":  {"type":"stock","lot":250,"token":"2885"},
    "HINDUNILVR":{"type":"stock","lot":300,"token":"1394"},
    "TCS":       {"type":"stock","lot":150,"token":"11536"},
    "TATASTEEL": {"type":"stock","lot":5500,"token":"3499"},
}
BROKERAGE=25

def get_lots(instrument,capital,sl_points=None):
    INDEX=["NIFTY","BANKNIFTY","FINNIFTY","MIDCPNIFTY","SENSEX"]
    COMMODITY=["CRUDEOIL","GOLDM","SILVERM"]
    if instrument in INDEX or instrument in COMMODITY:
        if capital<3000:return 1
        elif capital<=50000:return 2
        elif capital<=75000:return 3
        elif capital<=100000:return 4
        else:return 2+int((capital-50001)/25000)+1
    return 1

def load_data(symbol):
    all_candles=[]
    info=INSTRUMENTS.get(symbol,{})
    token=info.get("token","")
    for year in [2022,2023,2024]:
        for fname in [
            f"historical_data/{symbol}_{year}_5min.json",
            f"historical_data/{token}_{year}_5min.json"
        ]:
            if os.path.exists(fname):
                all_candles.extend(json.load(open(fname)))
                break
    return all_candles

def to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:df.columns=["time","open","high","low","close","volume"]
    for col in ["open","high","low","close","volume"]:
        df[col]=pd.to_numeric(df[col],errors="coerce")
    return df.dropna().reset_index(drop=True)

def calc_rsi(s,p=14):
    d=s.diff();g=d.clip(lower=0).rolling(p).mean();l=-d.clip(upper=0).rolling(p).mean()
    return 100-(100/(1+g/l))

def calc_macd(s):
    e12=s.ewm(span=12).mean();e26=s.ewm(span=26).mean();m=e12-e26
    return m,m.ewm(span=9).mean()

def get_trend(df):
    try:
        c=df["close"];s20=c.rolling(20).mean().iloc[-1]
        s50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else s20
        cur=c.iloc[-1]
        if cur>s20 and s20>s50:return 1
        elif cur<s20 and s20<s50:return -1
        return 0
    except:return 0

def get_wyckoff(df):
    try:
        c=df["close"].values;v=df["volume"].values
        h=df["high"].values;l=df["low"].values
        if len(c)<60:return "UNKNOWN"
        rv=v[-20:].mean();ov=v[-60:-20].mean();vol_dec=rv<ov*0.8
        s20=pd.Series(c).rolling(20).mean().values
        s50=pd.Series(c).rolling(50).mean().values
        above=c[-1]>s50[-1]
        con=(h[-20:].max()-l[-20:].min())<(h[-60:-20].max()-l[-60:-20].min())*0.6
        spring=l[-20:].min()<l[-60:-20].min() and c[-1]>l[-60:-20].min()
        upthrust=h[-20:].max()>h[-60:-20].max() and c[-1]<h[-60:-20].max()
        if con and not above and (vol_dec or spring):return "ACCUM"
        elif c[-1]>s20[-1] and s20[-1]>s50[-1]:return "MARKUP"
        elif con and above and (vol_dec or upthrust):return "DIST"
        elif c[-1]<s20[-1] and s20[-1]<s50[-1]:return "MARK"
        return "TRANS"
    except:return "UNKNOWN"

def get_ict_score(df5,action):
    try:
        score=0
        h=df5["high"];l=df5["low"];c=df5["close"]
        try:
            hour=int(str(df5["time"].iloc[-1])[11:13])
            if 9<=hour<=11:score+=5
            elif 13<=hour<=15:score+=4
        except:pass
        sh=h.tail(20).max();sl=l.tail(20).min()
        fr=sh-sl;cur=c.iloc[-1]
        if action=="BUY":
            ote_low=sh-(fr*0.79);ote_high=sh-(fr*0.62)
            if ote_low<=cur<=ote_high:score+=4
            if cur<(sh+sl)/2:score+=3
        else:
            ote_low=sl+(fr*0.62);ote_high=sl+(fr*0.79)
            if ote_low<=cur<=ote_high:score+=4
            if cur>(sh+sl)/2:score+=3
        v=df5["volume"];vwap=(c*v).sum()/v.sum() if v.sum()>0 else c.mean()
        if action=="BUY" and cur>vwap:score+=2
        elif action=="SELL" and cur<vwap:score+=2
        return score
    except:return 0

def get_fvg(df5,action):
    try:
        for i in range(len(df5)-3,len(df5)-1):
            if i<2:continue
            p2=df5.iloc[i-2];cur=df5.iloc[i]
            if action=="BUY" and cur["low"]>p2["high"]:return True
            elif action=="SELL" and cur["high"]<p2["low"]:return True
        return False
    except:return False

def get_liq(df5,action):
    try:
        h=df5["high"];l=df5["low"];c=df5["close"]
        rh=h.iloc[-10:-1].max();rl=l.iloc[-10:-1].min()
        last=df5.iloc[-1]
        if action=="BUY" and last["low"]<rl and last["close"]>rl:return True
        if action=="SELL" and last["high"]>rh and last["close"]<rh:return True
        return False
    except:return False


def get_trend_precise(df):
    """
    Uptrend = Higher Highs + Higher Lows
    Downtrend = Lower Highs + Lower Lows
    Confirmed by EMA
    """
    try:
        c=df["close"];h=df["high"];l=df["low"]
        if len(c)<30:return 0

        # Find swing highs and lows
        swing_highs=[]
        swing_lows=[]
        for i in range(3,len(df)-3):
            if h.iloc[i]==h.iloc[i-3:i+4].max():
                swing_highs.append(float(h.iloc[i]))
            if l.iloc[i]==l.iloc[i-3:i+4].min():
                swing_lows.append(float(l.iloc[i]))

        # Check HH+HL or LH+LL
        hh=hl=lh=ll=False
        if len(swing_highs)>=2:
            hh=swing_highs[-1]>swing_highs[-2]
            lh=swing_highs[-1]<swing_highs[-2]
        if len(swing_lows)>=2:
            hl=swing_lows[-1]>swing_lows[-2]
            ll=swing_lows[-1]<swing_lows[-2]

        # EMA confirmation
        ema20=c.ewm(span=20).mean().iloc[-1]
        ema50=c.ewm(span=50).mean().iloc[-1] if len(c)>=50 else ema20
        cur=float(c.iloc[-1])

        # Strong uptrend: HH+HL + price above EMAs
        if hh and hl and cur>ema20 and ema20>ema50:return 1
        # Strong downtrend: LH+LL + price below EMAs
        elif lh and ll and cur<ema20 and ema20<ema50:return -1
        # Weak uptrend: just HH+HL
        elif hh and hl:return 1
        # Weak downtrend: just LH+LL
        elif lh and ll:return -1
        return 0
    except:return 0

def check_fvg_precise(df5,action,atr):
    """
    Correct FVG:
    BULL FVG: Candle1.high < Candle3.low (gap between)
    BEAR FVG: Candle1.low > Candle3.high (gap between)
    Noise filter: gap_size > ATR * 0.2
    """
    try:
        min_gap=atr*0.2
        for i in range(2,min(len(df5),15)):
            c1=df5.iloc[-i-2]
            c3=df5.iloc[-i]
            if action=="BUY":
                gap=c3["low"]-c1["high"]
                if gap>min_gap:return True,gap
            else:
                gap=c1["low"]-c3["high"]
                if gap>min_gap:return True,gap
        return False,0
    except:return False,0

def check_liquidity_sweep(df5,action,atr):
    """
    Liquidity sweep with:
    - 30-50 candle lookback
    - Equal highs/lows detection
    - Session highs/lows
    """
    try:
        h=df5["high"];l=df5["low"];c=df5["close"]
        last=df5.iloc[-1]

        # Standard swing sweep (30-50 candle lookback)
        lookback=min(50,len(df5)-5)
        rh=h.iloc[-lookback:-1].max()
        rl=l.iloc[-lookback:-1].min()

        swept=False
        sweep_type=""

        if action=="BUY":
            # Swept lows and recovered
            if last["low"]<rl and last["close"]>rl:
                swept=True;sweep_type="SWEEP_LOW"

            # Equal lows (within 0.1% tolerance)
            prev_lows=l.iloc[-lookback:-1]
            for prev_l in prev_lows:
                if abs(last["low"]-prev_l)/prev_l<0.001:
                    if last["close"]>prev_l:
                        swept=True;sweep_type="EQUAL_LOWS"
                        break

            # Session low sweep (9:15-10:00 AM low)
            try:
                session_l=l.iloc[:6].min()  # First 6 candles = 9:15-9:45
                if last["low"]<session_l and last["close"]>session_l:
                    swept=True;sweep_type="SESSION_LOW"
            except:pass

        else:  # SELL
            # Swept highs and recovered
            if last["high"]>rh and last["close"]<rh:
                swept=True;sweep_type="SWEEP_HIGH"

            # Equal highs
            prev_highs=h.iloc[-lookback:-1]
            for prev_h in prev_highs:
                if abs(last["high"]-prev_h)/prev_h<0.001:
                    if last["close"]<prev_h:
                        swept=True;sweep_type="EQUAL_HIGHS"
                        break

            # Session high sweep
            try:
                session_h=h.iloc[:6].max()
                if last["high"]>session_h and last["close"]<session_h:
                    swept=True;sweep_type="SESSION_HIGH"
            except:pass

        return swept,sweep_type
    except:return False,""

def check_volatility(df5):
    """
    Low volatility filter:
    Current ATR must be > 20-period ATR average
    Avoids fake signals in choppy/low-vol markets
    """
    try:
        h=df5["high"];l=df5["low"]
        current_atr=float((h-l).tail(14).mean())
        avg_atr=float((h-l).rolling(20).mean().iloc[-1])
        return current_atr>avg_atr*0.8,current_atr,avg_atr
    except:return True,0,0

def get_session_score(df5):
    """
    9-11 AM = Best (+4)
    1-3 PM = Good (+2)
    Others = 0
    9 AM / 3 PM = -1 (avoid)
    """
    try:
        hour=int(str(df5["time"].iloc[-1])[11:13])
        if 10<=hour<=11:return 4,"BEST_SESSION"
        elif 9==hour:return -1,"AVOID_OPEN"
        elif 13<=hour<=14:return 2,"GOOD_SESSION"
        elif 15==hour:return -1,"AVOID_CLOSE"
        else:return 0,"NEUTRAL_SESSION"
    except:return 0,"UNKNOWN"

def calc_kairos_v2(df5,df15,action,wy):
    """
    KAIROS V2 - Precise scoring
    
    MANDATORY (all must be TRUE):
    1. Liquidity sweep present
    2. FVG present (valid, non-noise)
    3. Trend aligned (HH+HL or LH+LL)
    4. Volatility OK (not choppy market)
    
    SCORING:
    Liquidity sweep: 5pts
    BOS/ChoCh:      4pts
    FVG:            4pts
    Trend alignment:4pts
    OTE zone:       3pts
    VWAP:           2pts
    Wyckoff:        2pts
    Session:        2pts
    Max = 26 pts
    """
    try:
        c=df5["close"];h=df5["high"];l=df5["low"];v=df5["volume"]
        atr=float((h-l).tail(14).mean())
        if atr<=0:return 0

        # MANDATORY CHECK 1: Volatility
        vol_ok,curr_atr,avg_atr=check_volatility(df5)
        if not vol_ok:return 0

        # MANDATORY CHECK 2: Trend aligned
        trend5=get_trend_precise(df5)
        trend15=get_trend_precise(df15)
        if action=="BUY":
            trend_ok=(trend5==1 or trend15==1) and not (trend5==-1 and trend15==-1)
        else:
            trend_ok=(trend5==-1 or trend15==-1) and not (trend5==1 and trend15==1)
        if not trend_ok:return 0

        # MANDATORY CHECK 3: FVG OR Liquidity sweep (at least one)
        has_fvg,gap_size=check_fvg_precise(df5,action,atr)
        has_liq,sweep_type=check_liquidity_sweep(df5,action,atr)
        if not has_fvg and not has_liq:return 0

        # All mandatory passed! Now score
        score=0

        # 1. Liquidity sweep = 5pts
        score+=5

        # 2. BOS/ChoCh = 4pts
        try:
            rh=h.tail(20).max();rl=l.tail(20).min()
            ph=h.tail(40).iloc[:20].max();pl=l.tail(40).iloc[:20].min()
            if action=="BUY":
                if rh>ph:score+=4   # BOS upside
                elif rl>pl:score+=2  # ChoCh (HL)
            else:
                if rl<pl:score+=4   # BOS downside
                elif rh<ph:score+=2  # ChoCh (LH)
        except:pass

        # 3. FVG = 4pts (already confirmed)
        score+=4

        # 4. Trend alignment = 4pts
        if action=="BUY":
            align_score=sum([trend5==1,trend15==1])*2
        else:
            align_score=sum([trend5==-1,trend15==-1])*2
        score+=align_score

        # 5. OTE zone = 3pts
        try:
            sh=h.tail(20).max();sl_val=l.tail(20).min()
            fr=sh-sl_val;cur=float(c.iloc[-1])
            if action=="BUY":
                ote_low=sh-(fr*0.79);ote_high=sh-(fr*0.62)
                if ote_low<=cur<=ote_high:score+=3
            else:
                ote_low=sl_val+(fr*0.62);ote_high=sl_val+(fr*0.79)
                if ote_low<=cur<=ote_high:score+=3
        except:pass

        # 6. VWAP = 2pts
        try:
            vwap=(c*v).sum()/v.sum() if v.sum()>0 else float(c.mean())
            cur=float(c.iloc[-1])
            if action=="BUY" and cur>vwap:score+=2
            elif action=="SELL" and cur<vwap:score+=2
        except:pass

        # 7. Wyckoff = 2pts
        try:
            if action=="BUY":
                if wy in ["ACCUM","MARKUP"]:score+=2
                elif wy in ["DIST","MARK"]:score-=2
            else:
                if wy in ["DIST","MARK"]:score+=2
                elif wy in ["ACCUM","MARKUP"]:score-=2
        except:pass

        # 8. Session = max 4pts (best) or 2pts (good)
        sess_score,sess_name=get_session_score(df5)
        score+=sess_score

        return max(0,score)

    except Exception as e:
        return 0

def calc_kairos_v2_alias(df5,df15,action,trend15,wy):
    return calc_kairos_v2(df5,df15,action,wy)

def calc_kairos(df5,df15,action,trend15,wy):
    score=get_ict_score(df5,action)
    trend5=get_trend(df5)
    if action=="BUY":align=sum([trend5==1,trend15==1])
    else:align=sum([trend5==-1,trend15==-1])
    score+=align*2
    if get_fvg(df5,action):score+=4
    if get_liq(df5,action):score+=3
    if action=="BUY":
        if wy=="ACCUM":score+=5
        elif wy=="MARKUP":score+=4
        elif wy in ["DIST","MARK"]:score-=3
    else:
        if wy=="DIST":score+=5
        elif wy=="MARK":score+=4
        elif wy in ["ACCUM","MARKUP"]:score-=3
    return score

def load_ml_model(symbol):
    for f in [f"ml_models/{symbol}_model.pkl","ml_models/NIFTY_model.pkl"]:
        if os.path.exists(f):
            try:return pickle.load(open(f,"rb"))
            except:pass
    return None

def get_ml_prob(symbol,df5,df15,action,atr):
    try:
        data=load_ml_model(symbol)
        if not data:return 0.5
        c=df5["close"];h=df5["high"];l=df5["low"];v=df5["volume"]
        rsi=calc_rsi(c).iloc[-1]
        macd_line,sig=calc_macd(c);mh=(macd_line-sig).iloc[-1]
        t15=get_trend(df15);t5=get_trend(df5)
        vr=v.iloc[-1]/v.rolling(20).mean().iloc[-1] if v.rolling(20).mean().iloc[-1]>0 else 1
        features=[
            (c.iloc[-1]-c.iloc[-2])/c.iloc[-2],
            (c.iloc[-1]-c.iloc[-6])/c.iloc[-6] if len(c)>6 else 0,
            (c.iloc[-1]-c.iloc[-11])/c.iloc[-11] if len(c)>11 else 0,
            rsi/100,(rsi-50)/50,
            mh/atr if atr>0 else 0,1 if mh>0 else -1,
            min(vr,3)/3,1 if vr>1.5 else 0,
            t5,t15,get_trend(df15.iloc[::3] if len(df15)>30 else df15),
            1 if (action=="BUY" and t15==1) or (action=="SELL" and t15==-1) else 0,
            1 if c.iloc[-1]>c.rolling(20).mean().iloc[-1] else 0,
            atr/c.iloc[-1] if c.iloc[-1]>0 else 0,
            1 if get_fvg(df5,action) else 0,
            1 if get_liq(df5,action) else 0,
            1 if action=="BUY" else -1,
        ]
        model=data["model"];scaler=data["scaler"]
        n=model.n_features_in_
        while len(features)<n:features.append(0)
        features=features[:n]
        return model.predict_proba(scaler.transform([features]))[0][1]
    except:return 0.5

def get_sl_from_mining(symbol):
    try:
        if os.path.exists("failure_corrections.json"):
            d=json.load(open("failure_corrections.json"))
            sugg=d.get("parameter_suggestions",{}).get(symbol,{})
            return sugg.get("sl_multiplier",1.88)
    except:pass
    return 1.88

def get_greeks_score(df5,action,atr):
    try:
        c=df5["close"];h=df5["high"];l=df5["low"]
        current=c.iloc[-1]
        atr_pct=atr/current if current>0 else 0.01
        avg_atr=(h-l).tail(60).mean()
        iv_rank=min(100,(atr/avg_atr)*50) if avg_atr>0 else 50
        estimated_delta=min(0.7,0.3+(atr_pct*10))
        estimated_premium=atr*2.5
        score=0
        if estimated_delta>=0.25:score+=3
        if iv_rank<80:score+=2
        else:score-=2
        if 80<=estimated_premium<=300:score+=2
        try:
            hour=int(str(df5["time"].iloc[-1])[11:13])
            if hour>=14:score-=1
        except:pass
        return score,estimated_delta,iv_rank
    except:return 0,0.4,50

def detect_gap(df5):
    try:
        hour=int(str(df5["time"].iloc[-1])[11:13])
        minute=int(str(df5["time"].iloc[-1])[14:16])
        if hour!=9 or minute>45:return None
        today=str(df5["time"].iloc[-1])[:10]
        today_c=df5[df5["time"].astype(str).str[:10]==today]
        if len(today_c)<1:return None
        today_open=today_c["open"].iloc[0]
        prev_close=df5["close"].iloc[-10]
        gap_pct=((today_open-prev_close)/prev_close)*100
        if abs(gap_pct)<0.3:return None
        return {"type":"UP" if gap_pct>0 else "DOWN",
                "pct":gap_pct,"pts":abs(today_open-prev_close),
                "action":"BUY" if gap_pct>0 else "SELL"}
    except:return None

def run_monthly_backtest_full(capital=50000):
    print(f"\n{'='*65}")
    print(f"  KAIROS V30 FULL BACKTEST - ALL 18 INSTRUMENTS")
    print(f"  SMC+ICT+KAIROS+Wyckoff+ML+Greeks+Gap+RR(1:3 min)")
    print(f"  Capital: Rs.{capital:,.0f} | Brokerage: Rs.{BROKERAGE}")
    print(f"{'='*65}")

    all_monthly={}
    all_results=[]
    AVOID_HOURS=[9,10,15]
    MIN_KAIROS=10

    for symbol in INSTRUMENTS:
        print(f"\n[BT] {symbol}...",end=" ",flush=True)
        candles=load_data(symbol)
        if not candles:print("No data");continue
        df=to_df(candles)
        if df is None or len(df)<200:print("Skip");continue

        lot=INSTRUMENTS[symbol]["lot"]
        current_capital=capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;sig_action=""
        sl_pts=0;t1_pts=0;t2_pts=0
        entry_idx=0;current_lots=1;t1_hit=False
        daily_losses=0;last_date=None;daily_trades=0
        peak=capital;max_dd=0
        monthly_pnl={}
        trade_month=""
        gap_trades=0;greeks_blocked=0;rr_blocked=0;ml_blocked=0

        for i in range(100,len(df)-30,2):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-300):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue
            try:
                hour=int(str(df5["time"].iloc[-1])[11:13])
                if hour in AVOID_HOURS:continue
                if hour<9 or hour>14:continue
                curr_date=str(df5["time"].iloc[-1])[:10]
                month_key=curr_date[:7]
                if curr_date!=last_date:
                    daily_losses=0;daily_trades=0;last_date=curr_date
            except:continue

            if daily_losses>=3:continue
            if daily_trades>=4:continue

            if not in_trade:
                try:
                    c=df5["close"];h=df5["high"];l=df5["low"];v=df5["volume"]
                    rsi=calc_rsi(c).iloc[-1]
                    macd_line,sig=calc_macd(c);mh=(macd_line-sig).iloc[-1]
                    atr=(h-l).tail(14).mean()
                    if atr<=0:continue
                    trend_d=get_trend(df_daily)
                    trend15=get_trend(df15)
                    trend5=get_trend(df5)
                    wy=get_wyckoff(df15)
                    action=None
                    raw_sl=0;raw_t2=0

                    # Gap strategy
                    gap=detect_gap(df5)
                    if gap and daily_trades==0:
                        action=gap["action"]
                        raw_sl=atr*1.2
                        raw_t2=gap["pts"]
                        gap_trades+=1
                    else:
                        buy_s=0;sell_s=0
                        if trend_d==1:buy_s+=3
                        elif trend_d==-1:sell_s+=3
                        if trend15==1:buy_s+=2
                        elif trend15==-1:sell_s+=2
                        if trend5==1:buy_s+=1
                        elif trend5==-1:sell_s+=1
                        if rsi<45:buy_s+=2
                        elif rsi>55:sell_s+=2
                        if mh>0:buy_s+=1
                        elif mh<0:sell_s+=1
                        vol_s=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5
                        if vol_s:
                            if mh>0:buy_s+=2
                            else:sell_s+=2
                        if buy_s>=4 and buy_s>sell_s:action="BUY"
                        elif sell_s>=4 and sell_s>buy_s:action="SELL"
                        else:continue
                        if trend_d==1 and action=="SELL":continue
                        if trend_d==-1 and action=="BUY":continue
                        market="TRENDING" if abs(trend15)==1 else "SIDEWAYS"
                        if market=="SIDEWAYS" and not get_fvg(df5,action):continue
                        if action=="BUY" and wy in ["DIST","MARK"]:continue
                        if action=="SELL" and wy in ["ACCUM","MARKUP"]:continue
                        kairos=calc_kairos_v2(df5,df15,action,wy)
                        if kairos<MIN_KAIROS:continue
                        if action=="BUY" and rsi>70:continue
                        if action=="SELL" and rsi<30:continue
                        greek_s,delta,iv_rank=get_greeks_score(df5,action,atr)
                        if greek_s<2:greeks_blocked+=1;continue
                        if delta<0.20:continue
                        if iv_rank>85:continue
                        rr_ok,rr_sl,rr_target,rr_ratio,rr_quality,rr_issues=apply_rr_filter(df5,df15,action,atr,symbol,capital,is_trending=(market=="TRENDING"))
                        if not rr_ok:rr_blocked+=1;continue
                        ml_prob=get_ml_prob(symbol,df5,df15,action,atr)
                        if ml_prob<0.35:ml_blocked+=1;continue
                        raw_sl=rr_sl
                        raw_t2=raw_sl*rr_ratio

                    lot_count=get_lots(symbol,current_capital,raw_sl)
                    entry_p=c.iloc[-1]
                    in_trade=True;sig_action=action
                    sl_pts=raw_sl;t1_pts=raw_sl*1.5;t2_pts=raw_t2
                    entry_price=entry_p;entry_idx=i
                    current_lots=lot_count;t1_hit=False
                    trade_month=month_key
                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=""
                qty=current_lots*lot
                if sig_action=="BUY":
                    if not t1_hit and row["high"]>=entry_price+t1_pts:
                        t1_hit=True;sl_pts=0
                    if row["low"]<=entry_price-sl_pts and not t1_hit:
                        pnl=-sl_pts*qty;reason="SL"
                    elif row["high"]>=entry_price+t2_pts:
                        pnl=t2_pts*qty;reason="T2"
                    elif bars>=30:
                        pnl=(row["close"]-entry_price)*qty;reason="TO"
                else:
                    if not t1_hit and row["low"]<=entry_price-t1_pts:
                        t1_hit=True;sl_pts=0
                    if row["high"]>=entry_price+sl_pts and not t1_hit:
                        pnl=-sl_pts*qty;reason="SL"
                    elif row["low"]<=entry_price-t2_pts:
                        pnl=t2_pts*qty;reason="T2"
                    elif bars>=30:
                        pnl=(entry_price-row["close"])*qty;reason="TO"
                if reason:
                    net=pnl-BROKERAGE
                    current_capital+=net
                    if pnl<0:daily_losses+=1;losses+=1
                    else:wins+=1
                    daily_trades+=1
                    if current_capital>peak:peak=current_capital
                    dd=((peak-current_capital)/peak)*100
                    if dd>max_dd:max_dd=dd
                    if trade_month not in monthly_pnl:
                        monthly_pnl[trade_month]={"pnl":0,"trades":0,"wins":0}
                    monthly_pnl[trade_month]["pnl"]+=net
                    monthly_pnl[trade_month]["trades"]+=1
                    if net>0:monthly_pnl[trade_month]["wins"]+=1
                    in_trade=False;t1_hit=False

        total=wins+losses
        wr=round(wins/total*100,1) if total>0 else 0
        ret=round((current_capital-capital)/capital*100,1)
        all_monthly[symbol]=monthly_pnl
        all_results.append({
            "symbol":symbol,"type":INSTRUMENTS[symbol]["type"],
            "total_trades":total,"wins":wins,"losses":losses,
            "win_rate":wr,"total_return":ret,
            "max_drawdown":round(max_dd,1),
            "final_capital":round(current_capital,2),
            "gap_trades":gap_trades,"greeks_blocked":greeks_blocked,
            "rr_blocked":rr_blocked,"ml_blocked":ml_blocked,
            "monthly_pnl":monthly_pnl
        })
        print(f"WR:{wr}% Return:{ret}% Trades:{total} "
              f"RR_blocked:{rr_blocked} ML_blocked:{ml_blocked}")

    # Monthly report
    months=sorted(set(m for d in all_monthly.values() for m in d.keys()))
    print(f"\n{'='*65}")
    print(f"  MONTHLY RETURNS PER INSTRUMENT")
    print(f"{'='*65}")
    for symbol in INSTRUMENTS:
        data=all_monthly.get(symbol,{})
        if not data:continue
        print(f"\n--- {symbol} ({INSTRUMENTS[symbol]['type'].upper()}) ---")
        print(f"{'Month':<10}{'PnL':>12}{'Trades':>8}{'WR%':>6}{'Capital':>14}")
        print("-"*52)
        running=capital;y_totals={}
        for month in months:
            mdata=data.get(month)
            if not mdata:continue
            pnl=mdata["pnl"];trades=mdata["trades"]
            mwins=mdata["wins"]
            mwr=round(mwins/trades*100) if trades>0 else 0
            running+=pnl;year=month[:4]
            y_totals[year]=y_totals.get(year,0)+pnl
            sign="+" if pnl>=0 else ""
            print(f"{month:<10}{sign}{pnl:>10.0f}  {trades:>5}  {mwr:>4}%  Rs.{running:>10,.0f}")
            next_idx=months.index(month)+1
            if next_idx>=len(months) or months[next_idx][:4]!=year:
                ytot=y_totals[year];sign="+" if ytot>=0 else ""
                yret=round(ytot/capital*100,1)
                print(f"{'─'*52}")
                print(f"{year+' TOTAL':<10}{sign}{ytot:>10.0f}  ({yret}% ROI)")
                print(f"{'─'*52}")
        r=next((x for x in all_results if x["symbol"]==symbol),{})
        print(f"3YR: WR={r.get('win_rate',0)}% Trades={r.get('total_trades',0)} "
              f"Return={r.get('total_return',0)}% MaxDD={r.get('max_drawdown',0)}%")

    # Combined
    print(f"\n{'='*65}")
    print(f"  COMBINED ALL INSTRUMENTS")
    print(f"{'='*65}")
    print(f"{'Month':<10}{'Total PnL':>14}{'Active':>8}{'Avg':>12}")
    print("-"*46)
    grand=0;y_grand={}
    for month in months:
        mt=sum(all_monthly.get(s,{}).get(month,{}).get("pnl",0) for s in INSTRUMENTS)
        active=sum(1 for s in INSTRUMENTS if all_monthly.get(s,{}).get(month))
        avg=round(mt/active) if active>0 else 0
        grand+=mt;year=month[:4]
        y_grand[year]=y_grand.get(year,0)+mt
        sign="+" if mt>=0 else ""
        print(f"{month:<10}{sign}{mt:>12.0f}  {active:>6}  {sign}{avg:>10.0f}")
        next_idx=months.index(month)+1
        if next_idx>=len(months) or months[next_idx][:4]!=year:
            yt=y_grand[year];sign="+" if yt>=0 else ""
            print(f"{'─'*46}")
            print(f"{year+' TOTAL':<10}{sign}{yt:>12.0f}  ({yt/capital*100:.1f}% ROI)")
            print(f"{'─'*46}")
    print(f"\nGRAND TOTAL: {grand:>+,.0f}")
    print(f"3YR ROI: {grand/capital*100:.1f}%")
    print(f"Avg/Month: {grand/36:>+,.0f}")
    all_results.sort(key=lambda x:-x["total_return"])
    print(f"\nTOP 5:")
    for r in all_results[:5]:
        print(f"  {r['symbol']}: {r['total_return']}% WR:{r['win_rate']}% Trades:{r['total_trades']}")
    print(f"\nBOTTOM 5:")
    for r in all_results[-5:]:
        print(f"  {r['symbol']}: {r['total_return']}% WR:{r['win_rate']}%")
    os.makedirs("backtest_results",exist_ok=True)
    json.dump(all_results,open("backtest_results/full_backtest.json","w"),indent=2)
    print(f"\nSaved!")
    return all_monthly,all_results

if __name__=="__main__":
    run_monthly_backtest_full(capital=50000)
