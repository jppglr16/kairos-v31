
def calc_mcx_score(df5,df15,action,regime,atr,instrument):
    """
    MCX Specific Scoring:
    - No gamma walls (NSE only)
    - ATR% based (not absolute)
    - Evening session bonus
    - Global market correlation
    - Lower threshold: 13+ = trade
    """
    try:
        c=df5["close"];h=df5["high"];l=df5["low"];v=df5["volume"]
        cur=float(c.iloc[-1])
        score=0
        components={}

        # ATR as % of price
        atr_pct=atr/cur*100 if cur>0 else 0

        # === STRUCTURE ===
        # Liquidity sweep (adjusted for MCX)
        from v31_strategy import detect_liquidity_sweep_v31
        has_liq,liq_type,liq_level=detect_liquidity_sweep_v31(df5,action,atr)
        if has_liq:
            score+=5
            components["liq_sweep"]=5
        else:
            components["liq_sweep"]=0

        # BOS/ChoCh
        bos_score=0
        try:
            rh=float(h.tail(20).max());rl=float(l.tail(20).min())
            ph=float(h.tail(40).iloc[:20].max());pl=float(l.tail(40).iloc[:20].min())
            if action=="BUY":
                if rh>ph:bos_score=4
                elif rl>pl:bos_score=2
            else:
                if rl<pl:bos_score=4
                elif rh<ph:bos_score=2
        except:pass
        score+=bos_score
        components["bos_choch"]=bos_score

        # Must have structure
        if score==0:
            return 0,components,False,False

        # === IMBALANCE ===
        fvg_score=0
        try:
            for i in range(len(df5)-3,max(0,len(df5)-15),-1):
                c1=float(df5["high"].iloc[i])
                c3=float(df5["low"].iloc[i+2])
                if action=="BUY" and c3>c1:
                    fvg_score=4;break
                c1l=float(df5["low"].iloc[i])
                c3h=float(df5["high"].iloc[i+2])
                if action=="SELL" and c3h<c1l:
                    fvg_score=4;break
        except:pass
        score+=fvg_score
        components["fvg"]=fvg_score

        # Must have imbalance
        if fvg_score==0:
            return 0,components,False,False

        # === TREND ===
        trend_score=0
        try:
            ema20=float(c.ewm(span=20).mean().iloc[-1])
            ema50=float(c.ewm(span=50).mean().iloc[-1]) if len(c)>=50 else ema20
            if action=="BUY" and cur>ema20>ema50:trend_score=4
            elif action=="SELL" and cur<ema20<ema50:trend_score=4
            elif action=="BUY" and cur>ema20:trend_score=2
            elif action=="SELL" and cur<ema20:trend_score=2
        except:pass
        score+=trend_score
        components["trend"]=trend_score

        # === VOLATILITY BONUS (MCX specific) ===
        vol_score=0
        if atr_pct>0.5:vol_score=3   # Good volatility
        elif atr_pct>0.3:vol_score=2
        elif atr_pct>0.2:vol_score=1
        score+=vol_score
        components["volatility"]=vol_score

        # === SESSION BONUS (MCX best times) ===
        from datetime import datetime
        hour=datetime.now().hour
        session_score=0
        if 21<=hour<=23:session_score=4  # US market prime time
        elif 18<=hour<=21:session_score=3  # US pre-market
        elif 9<=hour<=11:session_score=2   # Morning
        score+=session_score
        components["session"]=session_score

        # === VOLUME CONFIRMATION ===
        vol_conf=0
        try:
            avg_vol=float(v.tail(20).mean())
            cur_vol=float(v.iloc[-1])
            if avg_vol>0 and cur_vol>avg_vol*1.3:
                vol_conf=3
            elif avg_vol>0 and cur_vol>avg_vol:
                vol_conf=1
        except:pass
        score+=vol_conf
        components["volume"]=vol_conf

        # MCX thresholds (lower than NSE)
        # Score >= 13 = trade
        # Score 10-12 = need ML > 0.6
        can_trade=score>=13
        need_ml=10<=score<13

        log_str=f'[MCX SCORE] {instrument} {action}: {score} {components}'
        import logging
        logging.getLogger(__name__).info(log_str)

        return score,components,can_trade,need_ml

    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f'MCX scoring error: {e}')
        return 0,{},False,False


def calc_v31_score(df5,df15,action,regime,wy,atr):
    """
    V31 Final Scoring System:
    
    MANDATORY STRUCTURE (at least one):
    → Liquidity Sweep OR BOS/ChoCh
    
    MANDATORY ENTRY (at least one):
    → FVG OR OTE zone
    
    Adaptive thresholds:
    Score >= 22 → TRADE
    Score 18-21 → TRADE only if ML > 0.7
    Score < 18 → SKIP
    """
    try:
        c=df5["close"];h=df5["high"];l=df5["low"];v=df5["volume"]
        cur=float(c.iloc[-1])
        score=0
        components={}

        # === STRUCTURE TRIGGER ===
        # Liquidity Sweep = 5pts
        from v31_strategy import detect_liquidity_sweep_v31
        has_liq,liq_type,liq_level=detect_liquidity_sweep_v31(df5,action,atr)
        if has_liq:
            score+=5
            components["liq_sweep"]=5
        else:
            components["liq_sweep"]=0

        # BOS/ChoCh = 4pts
        bos_score=0
        try:
            rh=float(h.tail(20).max());rl=float(l.tail(20).min())
            ph=float(h.tail(40).iloc[:20].max());pl=float(l.tail(40).iloc[:20].min())
            if action=="BUY":
                if rh>ph:bos_score=4   # BOS
                elif rl>pl:bos_score=2  # ChoCh
            else:
                if rl<pl:bos_score=4
                elif rh<ph:bos_score=2
        except:pass
        score+=bos_score
        components["bos_choch"]=bos_score

        # MANDATORY: Liq Sweep OR BOS must exist
        if components["liq_sweep"]==0 and components["bos_choch"]==0:
            return 0,components,False,False

        # === ENTRY SIGNAL ===
        # FVG = 4pts
        from v31_strategy import detect_fvg_v31
        has_fvg,fvg_data=detect_fvg_v31(df5,action,atr)
        if has_fvg:
            score+=4
            components["fvg"]=4
        else:
            components["fvg"]=0

        # OTE zone = 3pts
        ote_score=0
        try:
            sh=float(h.tail(20).max());sl_val=float(l.tail(20).min())
            fr=sh-sl_val
            if action=="BUY":
                ote_low=sh-(fr*0.79);ote_high=sh-(fr*0.62)
                if ote_low<=cur<=ote_high:ote_score=3
            else:
                ote_low=sl_val+(fr*0.62);ote_high=sl_val+(fr*0.79)
                if ote_low<=cur<=ote_high:ote_score=3
        except:pass
        score+=ote_score
        components["ote"]=ote_score

        # MANDATORY: FVG OR OTE must exist
        # EXCEPTION: If both Liq+BOS present = strong structure
        strong_structure=(components["liq_sweep"]>=5 and components["bos_choch"]>=4)
        if components["fvg"]==0 and components["ote"]==0 and not strong_structure:
            return 0,components,has_liq,has_fvg

        # === ADDITIONAL SCORING ===
        # Trend Alignment = 4pts
        from v31_strategy import get_trend_v31
        t5=get_trend_v31(df5);t15=get_trend_v31(df15)
        t_daily=get_trend_v31(df15.iloc[::3] if len(df15)>30 else df15)
        if action=="BUY":
            talign=sum([t5==1,t15==1,t_daily==1])*1.33
        else:
            talign=sum([t5==-1,t15==-1,t_daily==-1])*1.33
        talign_score=min(4,round(talign))
        score+=talign_score
        components["trend"]=talign_score

        # VWAP = 2pts
        try:
            vwap=float((c*v).sum()/v.sum()) if float(v.sum())>0 else float(c.mean())
            if action=="BUY" and cur>vwap:score+=2
            elif action=="SELL" and cur<vwap:score+=2
            components["vwap"]=2 if (action=="BUY" and cur>vwap) or (action=="SELL" and cur<vwap) else 0
        except:components["vwap"]=0

        # Wyckoff = 2pts
        wy_score=0
        if action=="BUY":
            if wy in ["ACCUM","MARKUP"]:wy_score=2
            elif wy in ["DIST","MARK"]:wy_score=-2
        else:
            if wy in ["DIST","MARK"]:wy_score=2
            elif wy in ["ACCUM","MARKUP"]:wy_score=-2
        score+=wy_score
        components["wyckoff"]=wy_score

        # Session = 2-4pts
        try:
            hour=int(str(df5["time"].iloc[-1])[11:13])
            if hour==10 or hour==11:sess_score=4
            elif hour==13 or hour==14:sess_score=2
            elif hour==9 or hour==15:sess_score=-1
            else:sess_score=0
            score+=sess_score
            components["session"]=sess_score
        except:components["session"]=0

        # Gamma Wall = 0-6pts
        gamma_score=0
        try:
            from v31_gamma import check_gamma_signal,check_oi_trap
            gamma_sig=check_gamma_signal("UNKNOWN",cur,df5,atr)
            if gamma_sig and gamma_sig["action"]==action:
                gamma_score=min(6,gamma_sig["strength"])
            oi_trap=check_oi_trap("UNKNOWN",cur,df5)
            if oi_trap and oi_trap["action"]==action:
                gamma_score+=min(7,oi_trap["strength"])
            gamma_score=min(13,gamma_score)
        except:pass
        score+=gamma_score
        components["gamma"]=gamma_score

        # Liquidity Trap = 0-9pts (NEW!)
        trap_score=0
        trap_info=None
        try:
            from v31_trap import get_full_trap_score
            trap_score,trap_info=get_full_trap_score(
                "UNKNOWN",df5,action,atr,cur)
            score+=trap_score
            components["trap"]=trap_score
        except:
            components["trap"]=0

        return max(0,score),components,has_liq,has_fvg

    except Exception as e:
        return 0,{},False,False
