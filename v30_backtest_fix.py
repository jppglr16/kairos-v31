import json,os,time,logging
import pandas as pd
import numpy as np

log=logging.getLogger(__name__)

def candles_to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:
        df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    df=df.dropna()
    return df.reset_index(drop=True)

def calc_rsi(series,period=14):
    delta=series.diff()
    gain=delta.clip(lower=0).rolling(period).mean()
    loss=-delta.clip(upper=0).rolling(period).mean()
    rs=gain/loss
    return 100-(100/(1+rs))

def calc_macd(series):
    ema12=series.ewm(span=12).mean()
    ema26=series.ewm(span=26).mean()
    macd=ema12-ema26
    signal=macd.ewm(span=9).mean()
    return macd,signal

def generate_bt_signal(df5,df15):
    try:
        c=df5['close']
        h=df5['high']
        l=df5['low']
        v=df5['volume']

        # RSI
        rsi=calc_rsi(c).iloc[-1]

        # MACD
        macd,signal=calc_macd(c)
        macd_hist=macd.iloc[-1]-signal.iloc[-1]

        # Trend
        sma20=c.rolling(20).mean().iloc[-1]
        sma50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else sma20
        current=c.iloc[-1]

        # ATR
        atr=(h-l).tail(14).mean()

        # Volume surge
        vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.3

        # BUY conditions
        buy_score=0
        if rsi<45:buy_score+=2
        if rsi>40 and rsi<60:buy_score+=1
        if macd_hist>0:buy_score+=2
        if current>sma20:buy_score+=2
        if sma20>sma50:buy_score+=1
        if vol_surge:buy_score+=1

        # SELL conditions
        sell_score=0
        if rsi>55:sell_score+=2
        if rsi>60:sell_score+=1
        if macd_hist<0:sell_score+=2
        if current<sma20:sell_score+=2
        if sma20<sma50:sell_score+=1
        if vol_surge:sell_score+=1

        if buy_score>=5 and buy_score>sell_score:
            return 'BUY',buy_score,atr
        elif sell_score>=5 and sell_score>buy_score:
            return 'SELL',sell_score,atr
        return None,0,atr
    except:
        return None,0,0

def run_backtest_fixed(instrument,df,capital=50000):
    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)

    results=[]
    wins=0;losses=0;total_pnl=0
    in_trade=False
    entry_price=0;trade_action=''
    sl=0;t1=0;t2=0
    entry_idx=0

    for i in range(60,len(df)-20):
        df5=df.iloc[i-60:i]
        df15=df.iloc[max(0,i-180):i:3]

        if not in_trade:
            action,score,atr=generate_bt_signal(df5,df15)
            if action and atr>0:
                entry_price=df5['close'].iloc[-1]
                sl_pts=atr*1.5
                t1_pts=sl_pts*1.5
                t2_pts=sl_pts*2.5
                in_trade=True
                trade_action=action
                sl=sl_pts;t1=t1_pts;t2=t2_pts
                entry_idx=i
        else:
            current_row=df.iloc[i]
            bars_in_trade=i-entry_idx
            pnl=0;exit_reason=''

            if trade_action=='BUY':
                if current_row['low']<=entry_price-sl:
                    pnl=-sl*lot;exit_reason='SL'
                elif current_row['high']>=entry_price+t2:
                    pnl=t2*lot;exit_reason='T2'
                elif current_row['high']>=entry_price+t1:
                    # Trail SL to breakeven
                    sl=0
                elif bars_in_trade>=20:
                    pnl=(current_row['close']-entry_price)*lot
                    exit_reason='TIMEOUT'
            else:
                if current_row['high']>=entry_price+sl:
                    pnl=-sl*lot;exit_reason='SL'
                elif current_row['low']<=entry_price-t2:
                    pnl=t2*lot;exit_reason='T2'
                elif current_row['low']<=entry_price-t1:
                    sl=0
                elif bars_in_trade>=20:
                    pnl=(entry_price-current_row['close'])*lot
                    exit_reason='TIMEOUT'

            if exit_reason:
                total_pnl+=pnl
                if pnl>0:wins+=1
                else:losses+=1
                results.append({
                    'action':trade_action,
                    'entry':round(entry_price,2),
                    'pnl':round(pnl,2),
                    'reason':exit_reason,
                    'bars':bars_in_trade
                })
                in_trade=False

    total_trades=wins+losses
    win_rate=round((wins/total_trades)*100,1) if total_trades>0 else 0
    avg_win=round(np.mean([r['pnl'] for r in results if r['pnl']>0]),2) if wins>0 else 0
    avg_loss=round(np.mean([r['pnl'] for r in results if r['pnl']<=0]),2) if losses>0 else 0
    profit_factor=round(abs(sum(r['pnl'] for r in results if r['pnl']>0)/sum(r['pnl'] for r in results if r['pnl']<0)),2) if losses>0 else 0

    summary={
        'instrument':instrument,
        'total_trades':total_trades,
        'wins':wins,'losses':losses,
        'win_rate':win_rate,
        'total_pnl':round(total_pnl,2),
        'avg_pnl':round(total_pnl/total_trades,2) if total_trades>0 else 0,
        'avg_win':avg_win,
        'avg_loss':avg_loss,
        'profit_factor':profit_factor,
    }
    print(f'\n[BT] ===== {instrument} RESULTS =====')
    print(f'[BT] Total Trades: {total_trades}')
    print(f'[BT] Wins: {wins} | Losses: {losses}')
    print(f'[BT] Win Rate: {win_rate}%')
    print(f'[BT] Total PnL: Rs.{total_pnl:,.0f}')
    print(f'[BT] Avg Win: Rs.{avg_win:,.0f}')
    print(f'[BT] Avg Loss: Rs.{avg_loss:,.0f}')
    print(f'[BT] Profit Factor: {profit_factor}')
    return summary

def run_all_backtests():
    from v30_backtest import load_historical_data,candles_to_df
    all_results={}
    for instrument in ['NIFTY','BANKNIFTY','CRUDEOIL']:
        all_candles=[]
        for year in [2022,2023,2024]:
            candles=load_historical_data(instrument,year)
            all_candles.extend(candles)
        if not all_candles:
            print(f'[BT] No data for {instrument}')
            continue
        df=candles_to_df(all_candles)
        if df is None:continue
        print(f'[BT] Running {instrument} backtest on {len(df)} candles...')
        result=run_backtest_fixed(instrument,df)
        all_results[instrument]=result
        os.makedirs('backtest_results',exist_ok=True)
        json.dump(result,open(f'backtest_results/{instrument}_backtest.json','w'),indent=2)
    return all_results

def train_ml_from_results():
    try:
        from sklearn.ensemble import RandomForestClassifier,GradientBoostingClassifier
        from sklearn.model_selection import train_test_split,cross_val_score
        from sklearn.preprocessing import StandardScaler
        import pickle

        all_features=[];all_labels=[]
        for instrument in ['NIFTY','BANKNIFTY','CRUDEOIL']:
            fname=f'backtest_results/{instrument}_backtest.json'
            if not os.path.exists(fname):continue
            data=json.load(open(fname))
            for i,trade in enumerate(data.get('results',[])):
                features=[
                    trade.get('pnl',0)/1000,
                    1 if trade.get('action')=='BUY' else -1,
                    trade.get('bars',0)/20,
                    1 if trade.get('reason')=='T2' else 0,
                ]
                label=1 if trade.get('pnl',0)>0 else 0
                all_features.append(features)
                all_labels.append(label)

        if len(all_features)<50:
            print(f'[ML] Need more trades: {len(all_features)}')
            return None

        X=np.array(all_features)
        y=np.array(all_labels)
        scaler=StandardScaler()
        X=scaler.fit_transform(X)

        X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.2,random_state=42)

        # Try multiple models
        models={
            'RandomForest':RandomForestClassifier(n_estimators=200,random_state=42),
            'GradientBoosting':GradientBoostingClassifier(n_estimators=100,random_state=42),
        }
        best_score=0;best_model=None;best_name=''
        for name,model in models.items():
            model.fit(X_train,y_train)
            score=model.score(X_test,y_test)
            cv_score=cross_val_score(model,X,y,cv=5).mean()
            print(f'[ML] {name}: Test={score*100:.1f}% CV={cv_score*100:.1f}%')
            if score>best_score:
                best_score=score
                best_model=model
                best_name=name

        pickle.dump({'model':best_model,'scaler':scaler},open('v30_ml_model.pkl','wb'))
        print(f'[ML] Best model: {best_name} accuracy: {best_score*100:.1f}%')
        print(f'[ML] Model saved!')
        return best_model,best_score
    except Exception as e:
        print(f'[ML] Error: {e}')
        return None

def generate_bt_signal_advanced(df5, df15):
    try:
        c=df5['close']
        h=df5['high']
        l=df5['low']
        v=df5['volume']
        if len(c)<50:return None,0,0

        # RSI
        rsi=calc_rsi(c).iloc[-1]

        # MACD
        macd,signal=calc_macd(c)
        macd_hist=(macd-signal).iloc[-1]
        macd_cross_up=macd.iloc[-1]>signal.iloc[-1] and macd.iloc[-2]<=signal.iloc[-2]
        macd_cross_dn=macd.iloc[-1]<signal.iloc[-1] and macd.iloc[-2]>=signal.iloc[-2]

        # Moving averages
        sma20=c.rolling(20).mean()
        sma50=c.rolling(50).mean()
        ema9=c.ewm(span=9).mean()
        current=c.iloc[-1]

        # ATR
        atr=(h-l).tail(14).mean()

        # Volume
        vol_avg=v.rolling(20).mean().iloc[-1]
        vol_surge=v.iloc[-1]>vol_avg*1.5

        # Bollinger Bands
        bb_mid=sma20.iloc[-1]
        bb_std=c.rolling(20).std().iloc[-1]
        bb_upper=bb_mid+2*bb_std
        bb_lower=bb_mid-2*bb_std

        # Stochastic
        low14=l.rolling(14).min()
        high14=h.rolling(14).max()
        stoch=((c-low14)/(high14-low14)*100).iloc[-1]

        # Swing highs/lows
        swing_high=h.tail(20).max()
        swing_low=l.tail(20).min()

        # BOS detection
        prev_high=h.iloc[-10:-1].max()
        prev_low=l.iloc[-10:-1].min()
        bos_up=current>prev_high
        bos_dn=current<prev_low

        # Trend strength
        trend_up=sma20.iloc[-1]>sma50.iloc[-1] and current>sma20.iloc[-1]
        trend_dn=sma20.iloc[-1]<sma50.iloc[-1] and current<sma20.iloc[-1]

        # Candle pattern
        last_candle=df5.iloc[-1]
        bullish_candle=last_candle['close']>last_candle['open']
        bearish_candle=last_candle['close']<last_candle['open']
        candle_body=abs(last_candle['close']-last_candle['open'])
        candle_range=last_candle['high']-last_candle['low']
        strong_candle=candle_body>candle_range*0.6

        # BUY scoring
        buy_score=0
        if rsi>40 and rsi<60:buy_score+=1
        if rsi<45:buy_score+=2
        if macd_hist>0:buy_score+=2
        if macd_cross_up:buy_score+=3
        if trend_up:buy_score+=2
        if bos_up:buy_score+=2
        if current>bb_mid:buy_score+=1
        if current<bb_lower:buy_score+=2  # Oversold bounce
        if stoch<30:buy_score+=2
        if vol_surge:buy_score+=2
        if bullish_candle and strong_candle:buy_score+=2
        if current>ema9.iloc[-1]:buy_score+=1

        # SELL scoring
        sell_score=0
        if rsi>60 and rsi<80:sell_score+=1
        if rsi>65:sell_score+=2
        if macd_hist<0:sell_score+=2
        if macd_cross_dn:sell_score+=3
        if trend_dn:sell_score+=2
        if bos_dn:sell_score+=2
        if current<bb_mid:sell_score+=1
        if current>bb_upper:sell_score+=2  # Overbought
        if stoch>70:sell_score+=2
        if vol_surge:sell_score+=2
        if bearish_candle and strong_candle:sell_score+=2
        if current<ema9.iloc[-1]:sell_score+=1

        # Minimum score threshold - higher = better quality
        min_score=12

        if buy_score>=min_score and buy_score>sell_score:
            return 'BUY',buy_score,atr
        elif sell_score>=min_score and sell_score>buy_score:
            return 'SELL',sell_score,atr

        return None,0,atr
    except Exception as e:
        return None,0,0

def run_advanced_backtest(instrument,capital=50000):
    from v30_backtest import load_historical_data,candles_to_df
    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)

    print(f'\n{"="*45}')
    print(f'  ADVANCED BACKTEST: {instrument}')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*45}')

    current_capital=capital
    grand_trades=0;grand_wins=0
    peak_capital=capital;max_drawdown=0

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None:continue

        year_start=current_capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;trade_action=''
        sl=0;t2=0;entry_idx=0;current_lots=1

        for i in range(60,len(df)-20):
            df5=df.iloc[i-60:i]
            df15=df.iloc[max(0,i-180):i:3]
            risk_amt=min(current_capital*0.05,2500)

            if not in_trade:
                action,score,atr=generate_bt_signal_advanced(df5,df15)
                if action and atr>0:
                    sl_pts=atr*1.5
                    lots=max(1,int(risk_amt/(sl_pts*lot)))
                    lots=min(lots,3)
                    entry_price=df5['close'].iloc[-1]
                    t1_pts=sl_pts*1.5
                    t2_pts=sl_pts*2.5
                    in_trade=True
                    trade_action=action
                    sl=sl_pts;t2=t2_pts
                    entry_idx=i
                    current_lots=lots
                    trail_sl=sl_pts
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''

                if trade_action=='BUY':
                    # Trail SL after T1
                    if row['high']>=entry_price+t2*0.6:
                        trail_sl=min(trail_sl,entry_price-row['low'])
                    if row['low']<=entry_price-sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['high']>=entry_price+t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=25:
                        pnl=(row['close']-entry_price)*lot*current_lots
                        reason='TIMEOUT'
                else:
                    if row['high']>=entry_price+sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['low']<=entry_price-t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=25:
                        pnl=(entry_price-row['close'])*lot*current_lots
                        reason='TIMEOUT'

                if reason:
                    current_capital+=pnl-120  # brokerage
                    if pnl>0:wins+=1
                    else:losses+=1
                    # Drawdown
                    if current_capital>peak_capital:peak_capital=current_capital
                    dd=((peak_capital-current_capital)/peak_capital)*100
                    if dd>max_drawdown:max_drawdown=dd
                    in_trade=False

        total=wins+losses
        wr=round((wins/total)*100,1) if total>0 else 0
        yr_pnl=current_capital-year_start
        yr_return=round((yr_pnl/year_start)*100,1)
        grand_trades+=total
        grand_wins+=wins

        print(f'\n  📅 {year}:')
        print(f'  Capital Start: Rs.{year_start:,.0f}')
        print(f'  Capital End:   Rs.{current_capital:,.0f}')
        print(f'  PnL:           Rs.{yr_pnl:,.0f}')
        print(f'  Return:        {yr_return}%')
        print(f'  Trades:        {total} | WR: {wr}%')

    total_return=round(((current_capital-capital)/capital)*100,1)
    grand_wr=round((grand_wins/grand_trades)*100,1) if grand_trades>0 else 0

    print(f'\n{"="*45}')
    print(f'  📊 3 YEAR SUMMARY: {instrument}')
    print(f'{"="*45}')
    print(f'  Start:        Rs.{capital:,.0f}')
    print(f'  Final:        Rs.{current_capital:,.0f}')
    print(f'  Total PnL:    Rs.{current_capital-capital:,.0f}')
    print(f'  Total Return: {total_return}%')
    print(f'  Win Rate:     {grand_wr}%')
    print(f'  Max Drawdown: {max_drawdown:.1f}%')
    print(f'  Total Trades: {grand_trades}')
    print(f'{"="*45}')

def run_smc_backtest(instrument,capital=50000):
    from v30_backtest import load_historical_data,candles_to_df
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)
    BROKERAGE=25

    print(f'\n{"="*45}')
    print(f'  SMC BACKTEST: {instrument}')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*45}')

    current_capital=capital
    grand_trades=0;grand_wins=0
    peak_capital=capital;max_drawdown=0

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None or len(df)<100:continue

        year_start=current_capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;trade_action=''
        sl=0;t2=0;entry_idx=0;current_lots=1

        for i in range(60,len(df)-20,3):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            if len(df5)<30 or len(df15)<10:continue

            risk_amt=min(current_capital*0.05,2500)

            if not in_trade:
                try:
                    # Full SMC analysis
                    smc=get_smc_signal(df5,df15)
                    mom=get_momentum_signal(df5)
                    market=detect_market_condition(df15)
                    fvg=detect_fvg(df5)
                    liq=detect_liq_sweep(df5)

                    if not smc['action']:continue
                    action=smc['action']

                    # Count confirmations
                    conf=count_conf(smc,mom,fvg,liq,action)

                    # Against trend needs more confirmations
                    against=(action=='BUY' and smc['trend15']=='DOWNTREND') or \
                            (action=='SELL' and smc['trend15']=='UPTREND')
                    min_conf=7 if against else 4

                    if conf<min_conf:continue

                    # ATR based SL
                    atr=(df5['high']-df5['low']).tail(14).mean()
                    if atr<=0:continue

                    sl_pts=atr*1.5
                    t1_pts=sl_pts*1.5
                    t2_pts=sl_pts*2.5 if market!='SIDEWAYS' else sl_pts*1.5

                    # Dynamic lots
                    lots=max(1,int(risk_amt/(sl_pts*lot)))
                    lots=min(lots,3)

                    entry_price=df5['close'].iloc[-1]
                    in_trade=True
                    trade_action=action
                    sl=sl_pts;t2=t2_pts
                    entry_idx=i
                    current_lots=lots
                    t1_hit=False

                except Exception as e:
                    continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''

                if trade_action=='BUY':
                    if not t1_hit and row['high']>=entry_price+(t2*0.6):
                        t1_hit=True
                        sl=0  # Move SL to breakeven
                    if row['low']<=entry_price-sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['high']>=entry_price+t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_price)*lot*current_lots
                        reason='TIMEOUT'
                else:
                    if not t1_hit and row['low']<=entry_price-(t2*0.6):
                        t1_hit=True
                        sl=0
                    if row['high']>=entry_price+sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['low']<=entry_price-t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(entry_price-row['close'])*lot*current_lots
                        reason='TIMEOUT'

                if reason:
                    net_pnl=pnl-BROKERAGE
                    current_capital+=net_pnl
                    if pnl>0:wins+=1
                    else:losses+=1
                    if current_capital>peak_capital:peak_capital=current_capital
                    dd=((peak_capital-current_capital)/peak_capital)*100
                    if dd>max_drawdown:max_drawdown=dd
                    in_trade=False
                    t1_hit=False

        total=wins+losses
        wr=round((wins/total)*100,1) if total>0 else 0
        yr_pnl=current_capital-year_start
        yr_return=round((yr_pnl/year_start)*100,1)
        grand_trades+=total
        grand_wins+=wins

        print(f'\n  📅 {year}:')
        print(f'  Capital Start:  Rs.{year_start:,.0f}')
        print(f'  Capital End:    Rs.{current_capital:,.0f}')
        print(f'  PnL (net):      Rs.{yr_pnl:,.0f}')
        print(f'  Return:         {yr_return}%')
        print(f'  Trades:         {total} | WR: {wr}%')

    total_return=round(((current_capital-capital)/capital)*100,1)
    grand_wr=round((grand_wins/grand_trades)*100,1) if grand_trades>0 else 0

    print(f'\n{"="*45}')
    print(f'  📊 3 YEAR SUMMARY: {instrument}')
    print(f'{"="*45}')
    print(f'  Start Capital:  Rs.{capital:,.0f}')
    print(f'  Final Capital:  Rs.{current_capital:,.0f}')
    print(f'  Total PnL:      Rs.{current_capital-capital:,.0f}')
    print(f'  Total Return:   {total_return}%')
    print(f'  Win Rate:       {grand_wr}%')
    print(f'  Max Drawdown:   {max_drawdown:.1f}%')
    print(f'  Total Trades:   {grand_trades}')
    print(f'  Brokerage paid: Rs.{grand_trades*BROKERAGE:,.0f}')
    print(f'{"="*45}')

def run_filtered_backtest(instrument,capital=50000):
    from v30_backtest import load_historical_data,candles_to_df
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)
    BROKERAGE=25

    print(f'\n{"="*45}')
    print(f'  FILTERED SMC BACKTEST: {instrument}')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*45}')

    current_capital=capital
    grand_trades=0;grand_wins=0
    peak_capital=capital;max_drawdown=0

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None:continue

        year_start=current_capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;trade_action=''
        sl=0;t2=0;entry_idx=0;current_lots=1
        daily_losses=0;last_date=None

        for i in range(60,len(df)-20,3):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            if len(df5)<30 or len(df15)<10:continue

            # Time filter - only 9:30 to 14:30
            try:
                candle_time=str(df5['time'].iloc[-1])
                hour=int(candle_time[11:13]) if len(candle_time)>11 else 10
                if hour<9 or hour>14:continue
            except:pass

            # Daily loss reset
            try:
                current_date=str(df5['time'].iloc[-1])[:10]
                if current_date!=last_date:
                    daily_losses=0
                    last_date=current_date
            except:pass

            # Max 3 losses per day
            if daily_losses>=3:continue

            risk_amt=min(current_capital*0.05,2500)

            if not in_trade:
                try:
                    smc=get_smc_signal(df5,df15)
                    mom=get_momentum_signal(df5)
                    market=detect_market_condition(df15)
                    fvg=detect_fvg(df5)
                    liq=detect_liq_sweep(df5)

                    if not smc['action']:continue

                    # Skip sideways market
                    if market=='SIDEWAYS' and not fvg and not liq:continue

                    action=smc['action']
                    against=(action=='BUY' and smc['trend15']=='DOWNTREND') or \
                            (action=='SELL' and smc['trend15']=='UPTREND')

                    conf=count_conf(smc,mom,fvg,liq,action)

                    # Stricter filters
                    min_conf=8 if against else 5
                    if conf<min_conf:continue

                    # Need momentum alignment
                    if action=='BUY' and mom['momentum']!='BULLISH':continue
                    if action=='SELL' and mom['momentum']!='BEARISH':continue

                    # RSI filter
                    if action=='BUY' and mom['rsi']>70:continue
                    if action=='SELL' and mom['rsi']<30:continue

                    atr=(df5['high']-df5['low']).tail(14).mean()
                    if atr<=0:continue

                    sl_pts=atr*1.5
                    t2_pts=sl_pts*2.5 if market!='SIDEWAYS' else sl_pts*1.5

                    lots=max(1,int(risk_amt/(sl_pts*lot)))
                    lots=min(lots,3)

                    entry_price=df5['close'].iloc[-1]
                    in_trade=True
                    trade_action=action
                    sl=sl_pts;t2=t2_pts
                    entry_idx=i
                    current_lots=lots
                    t1_hit=False

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''

                if trade_action=='BUY':
                    if not t1_hit and row['high']>=entry_price+(t2*0.5):
                        t1_hit=True;sl=0
                    if row['low']<=entry_price-sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['high']>=entry_price+t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_price)*lot*current_lots
                        reason='TIMEOUT'
                else:
                    if not t1_hit and row['low']<=entry_price-(t2*0.5):
                        t1_hit=True;sl=0
                    if row['high']>=entry_price+sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['low']<=entry_price-t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(entry_price-row['close'])*lot*current_lots
                        reason='TIMEOUT'

                if reason:
                    net_pnl=pnl-BROKERAGE
                    current_capital+=net_pnl
                    if pnl<0:daily_losses+=1
                    if pnl>0:wins+=1
                    else:losses+=1
                    if current_capital>peak_capital:peak_capital=current_capital
                    dd=((peak_capital-current_capital)/peak_capital)*100
                    if dd>max_drawdown:max_drawdown=dd
                    in_trade=False
                    t1_hit=False

        total=wins+losses
        wr=round((wins/total)*100,1) if total>0 else 0
        yr_pnl=current_capital-year_start
        yr_return=round((yr_pnl/year_start)*100,1)
        grand_trades+=total
        grand_wins+=wins

        print(f'\n  📅 {year}:')
        print(f'  Capital Start:  Rs.{year_start:,.0f}')
        print(f'  Capital End:    Rs.{current_capital:,.0f}')
        print(f'  PnL (net):      Rs.{yr_pnl:,.0f}')
        print(f'  Return:         {yr_return}%')
        print(f'  Trades:         {total} | WR: {wr}%')

    total_return=round(((current_capital-capital)/capital)*100,1)
    grand_wr=round((grand_wins/grand_trades)*100,1) if grand_trades>0 else 0

    print(f'\n{"="*45}')
    print(f'  📊 3 YEAR FILTERED SUMMARY: {instrument}')
    print(f'{"="*45}')
    print(f'  Start Capital:  Rs.{capital:,.0f}')
    print(f'  Final Capital:  Rs.{current_capital:,.0f}')
    print(f'  Total PnL:      Rs.{current_capital-capital:,.0f}')
    print(f'  Total Return:   {total_return}%')
    print(f'  Win Rate:       {grand_wr}%')
    print(f'  Max Drawdown:   {max_drawdown:.1f}%')
    print(f'  Total Trades:   {grand_trades}')
    print(f'  Brokerage:      Rs.{grand_trades*BROKERAGE:,.0f}')
    print(f'{"="*45}')

def get_daily_trend(df):
    try:
        close=df['close']
        sma20=close.rolling(20).mean().iloc[-1]
        sma50=close.rolling(50).mean().iloc[-1] if len(close)>=50 else sma20
        current=close.iloc[-1]
        if current>sma20 and sma20>sma50:
            return 'UPTREND'
        elif current<sma20 and sma20<sma50:
            return 'DOWNTREND'
        return 'SIDEWAYS'
    except:
        return 'SIDEWAYS'

def run_trend_filtered_backtest(instrument,capital=50000):
    from v30_backtest import load_historical_data,candles_to_df
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)
    BROKERAGE=25

    print(f'\n{"="*45}')
    print(f'  TREND FILTERED BACKTEST: {instrument}')
    print(f'  Capital: Rs.{capital:,.0f}')
    print(f'{"="*45}')

    current_capital=capital
    grand_trades=0;grand_wins=0
    peak_capital=capital;max_drawdown=0

    for year in [2022,2023,2024]:
        candles=load_historical_data(instrument,year)
        if not candles:continue
        df=candles_to_df(candles)
        if df is None:continue

        year_start=current_capital
        wins=0;losses=0
        in_trade=False
        entry_price=0;trade_action=''
        sl=0;t2=0;entry_idx=0
        daily_losses=0;last_date=None
        t1_hit=False

        for i in range(100,len(df)-20,3):
            df5=df.iloc[i-60:i].copy()
            df15=df.iloc[max(0,i-180):i:3].copy()
            df_daily=df.iloc[max(0,i-200):i:12].copy()
            if len(df5)<30 or len(df15)<10:continue

            # Time filter
            try:
                candle_time=str(df5['time'].iloc[-1])
                hour=int(candle_time[11:13]) if len(candle_time)>11 else 10
                if hour<9 or hour>14:continue
            except:pass

            # Daily reset
            try:
                current_date=str(df5['time'].iloc[-1])[:10]
                if current_date!=last_date:
                    daily_losses=0
                    last_date=current_date
            except:pass

            if daily_losses>=3:continue

            risk_amt=min(current_capital*0.05,2500)

            if not in_trade:
                try:
                    # Get daily trend bias
                    daily_trend=get_daily_trend(df_daily)

                    smc=get_smc_signal(df5,df15)
                    mom=get_momentum_signal(df5)
                    market=detect_market_condition(df15)
                    fvg=detect_fvg(df5)
                    liq=detect_liq_sweep(df5)

                    if not smc['action']:continue

                    action=smc['action']

                    # TREND BIAS FILTER - Key improvement!
                    if daily_trend=='UPTREND' and action=='SELL':continue
                    if daily_trend=='DOWNTREND' and action=='BUY':continue

                    # Skip pure sideways
                    if market=='SIDEWAYS' and not fvg and not liq:continue

                    against=(action=='BUY' and smc['trend15']=='DOWNTREND') or \
                            (action=='SELL' and smc['trend15']=='UPTREND')
                    conf=count_conf(smc,mom,fvg,liq,action)
                    min_conf=8 if against else 5
                    if conf<min_conf:continue

                    # Momentum alignment
                    if action=='BUY' and mom['momentum']!='BULLISH':continue
                    if action=='SELL' and mom['momentum']!='BEARISH':continue

                    # RSI filter
                    if action=='BUY' and mom['rsi']>70:continue
                    if action=='SELL' and mom['rsi']<30:continue

                    atr=(df5['high']-df5['low']).tail(14).mean()
                    if atr<=0:continue

                    sl_pts=atr*1.5
                    t2_pts=sl_pts*2.5 if market!='SIDEWAYS' else sl_pts*1.5
                    lots=max(1,int(risk_amt/(sl_pts*lot)))
                    lots=min(lots,3)

                    entry_price=df5['close'].iloc[-1]
                    in_trade=True
                    trade_action=action
                    sl=sl_pts;t2=t2_pts
                    entry_idx=i
                    current_lots=lots
                    t1_hit=False

                except:continue
            else:
                row=df.iloc[i]
                bars=i-entry_idx
                pnl=0;reason=''

                if trade_action=='BUY':
                    if not t1_hit and row['high']>=entry_price+(t2*0.5):
                        t1_hit=True;sl=0
                    if row['low']<=entry_price-sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['high']>=entry_price+t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(row['close']-entry_price)*lot*current_lots
                        reason='TIMEOUT'
                else:
                    if not t1_hit and row['low']<=entry_price-(t2*0.5):
                        t1_hit=True;sl=0
                    if row['high']>=entry_price+sl:
                        pnl=-sl*lot*current_lots;reason='SL'
                    elif row['low']<=entry_price-t2:
                        pnl=t2*lot*current_lots;reason='T2'
                    elif bars>=30:
                        pnl=(entry_price-row['close'])*lot*current_lots
                        reason='TIMEOUT'

                if reason:
                    net_pnl=pnl-BROKERAGE
                    current_capital+=net_pnl
                    if pnl<0:daily_losses+=1
                    if pnl>0:wins+=1
                    else:losses+=1
                    if current_capital>peak_capital:peak_capital=current_capital
                    dd=((peak_capital-current_capital)/peak_capital)*100
                    if dd>max_drawdown:max_drawdown=dd
                    in_trade=False
                    t1_hit=False

        total=wins+losses
        wr=round((wins/total)*100,1) if total>0 else 0
        yr_pnl=current_capital-year_start
        yr_return=round((yr_pnl/year_start)*100,1)
        grand_trades+=total
        grand_wins+=wins

        print(f'\n  📅 {year}:')
        print(f'  Capital Start:  Rs.{year_start:,.0f}')
        print(f'  Capital End:    Rs.{current_capital:,.0f}')
        print(f'  PnL (net):      Rs.{yr_pnl:,.0f}')
        print(f'  Return:         {yr_return}%')
        print(f'  Trades:         {total} | WR: {wr}%')

    total_return=round(((current_capital-capital)/capital)*100,1)
    grand_wr=round((grand_wins/grand_trades)*100,1) if grand_trades>0 else 0

    print(f'\n{"="*45}')
    print(f'  📊 3 YEAR TREND FILTERED: {instrument}')
    print(f'{"="*45}')
    print(f'  Start Capital:  Rs.{capital:,.0f}')
    print(f'  Final Capital:  Rs.{current_capital:,.0f}')
    print(f'  Total PnL:      Rs.{current_capital-capital:,.0f}')
    print(f'  Total Return:   {total_return}%')
    print(f'  Win Rate:       {grand_wr}%')
    print(f'  Max Drawdown:   {max_drawdown:.1f}%')
    print(f'  Total Trades:   {grand_trades}')
    print(f'  Brokerage:      Rs.{grand_trades*BROKERAGE:,.0f}')
    print(f'{"="*45}')
