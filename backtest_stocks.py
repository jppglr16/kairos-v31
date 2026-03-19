import json,os
import pandas as pd
import numpy as np

STOCKS={
    'RELIANCE':  {'token':'2885','lot':250},
    'HDFCBANK':  {'token':'1333','lot':550},
    'ICICIBANK': {'token':'4963','lot':700},
    'SBIN':      {'token':'3045','lot':1500},
    'TCS':       {'token':'11536','lot':150},
    'INFY':      {'token':'1594','lot':400},
    'LT':        {'token':'11483','lot':450},
    'BAJFINANCE':{'token':'317','lot':125},
    'MARUTI':    {'token':'10999','lot':100},
    'TATAMOTORS':{'token':'3456','lot':1350},
    'WIPRO':     {'token':'3787','lot':1500},
    'AXISBANK':  {'token':'5900','lot':625},
    'KOTAKBANK': {'token':'1922','lot':400},
    'BHARTIARTL':{'token':'10604','lot':950},
    'SUNPHARMA': {'token':'3351','lot':350},
    'HINDUNILVR':{'token':'1394','lot':300},
    'NTPC':      {'token':'11630','lot':4500},
    'POWERGRID': {'token':'14977','lot':3400},
    'ONGC':      {'token':'2475','lot':1925},
    'TATASTEEL': {'token':'3499','lot':5500},
}

def load_stock_data(symbol):
    all_candles=[]
    for year in [2022,2023,2024]:
        fname=f'historical_data/{symbol}_{year}_5min.json'
        if not os.path.exists(fname):
            # Try with token
            for s,info in STOCKS.items():
                if s==symbol:
                    fname=f'historical_data/{info["token"]}_{year}_5min.json'
                    break
        if os.path.exists(fname):
            all_candles.extend(json.load(open(fname)))
    return all_candles

def candles_to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles)
    if len(df.columns)==6:
        df.columns=['time','open','high','low','close','volume']
    for col in ['open','high','low','close','volume']:
        df[col]=pd.to_numeric(df[col],errors='coerce')
    return df.dropna().reset_index(drop=True)

def calc_rsi(series,period=14):
    delta=series.diff()
    gain=delta.clip(lower=0).rolling(period).mean()
    loss=-delta.clip(upper=0).rolling(period).mean()
    return 100-(100/(1+gain/loss))

def calc_macd(series):
    ema12=series.ewm(span=12).mean()
    ema26=series.ewm(span=26).mean()
    macd=ema12-ema26
    signal=macd.ewm(span=9).mean()
    return macd,signal

def get_daily_trend(df):
    try:
        close=df['close']
        sma20=close.rolling(20).mean().iloc[-1]
        sma50=close.rolling(50).mean().iloc[-1] if len(close)>=50 else sma20
        current=close.iloc[-1]
        if current>sma20 and sma20>sma50:return 'UPTREND'
        elif current<sma20 and sma20<sma50:return 'DOWNTREND'
        return 'SIDEWAYS'
    except:return 'SIDEWAYS'

def generate_signal(df5,df15):
    try:
        c=df5['close'];h=df5['high'];l=df5['low'];v=df5['volume']
        if len(c)<50:return None,0,0

        rsi=calc_rsi(c).iloc[-1]
        macd,signal=calc_macd(c)
        macd_hist=(macd-signal).iloc[-1]
        sma20=c.rolling(20).mean().iloc[-1]
        sma50=c.rolling(50).mean().iloc[-1] if len(c)>=50 else sma20
        current=c.iloc[-1]
        atr=(h-l).tail(14).mean()
        vol_surge=v.iloc[-1]>v.rolling(20).mean().iloc[-1]*1.5

        # Daily trend
        daily_trend=get_daily_trend(df15)

        buy_score=0
        sell_score=0

        if daily_trend=='UPTREND':
            buy_score+=3
        elif daily_trend=='DOWNTREND':
            sell_score+=3

        if rsi<40:buy_score+=3
        elif rsi>60:sell_score+=3
        if macd_hist>0:buy_score+=2
        elif macd_hist<0:sell_score+=2
        if current>sma20:buy_score+=2
        elif current<sma20:sell_score+=2
        if current>sma50:buy_score+=1
        elif current<sma50:sell_score+=1
        if vol_surge:
            if macd_hist>0:buy_score+=2
            else:sell_score+=2

        # Swing high/low
        swing_high=h.tail(20).max()
        swing_low=l.tail(20).min()
        if current>swing_high*0.995:sell_score+=2
        if current<swing_low*1.005:buy_score+=2

        min_score=7
        if buy_score>=min_score and buy_score>sell_score:
            return 'BUY',buy_score,atr
        elif sell_score>=min_score and sell_score>buy_score:
            return 'SELL',sell_score,atr
        return None,0,atr
    except:
        return None,0,0

def run_stock_backtest(symbol,capital=50000):
    candles=load_stock_data(symbol)
    if not candles:
        print(f'[BT] No data for {symbol}')
        return None

    df=candles_to_df(candles)
    if df is None or len(df)<200:
        print(f'[BT] Insufficient data for {symbol}')
        return None

    lot=STOCKS.get(symbol,{}).get('lot',100)
    BROKERAGE=120
    current_capital=capital
    wins=0;losses=0
    in_trade=False
    entry_price=0;trade_action=''
    sl=0;t2=0;entry_idx=0
    daily_losses=0;last_date=None
    t1_hit=False
    peak_capital=capital;max_drawdown=0
    yearly_pnl={}

    for i in range(60,len(df)-20,3):
        df5=df.iloc[i-60:i].copy()
        df15=df.iloc[max(0,i-180):i:3].copy()
        if len(df5)<30 or len(df15)<10:continue

        try:
            hour=int(str(df5['time'].iloc[-1])[11:13])
            if hour<9 or hour>14:continue
        except:pass

        try:
            current_date=str(df5['time'].iloc[-1])[:10]
            year=current_date[:4]
            if current_date!=last_date:
                daily_losses=0;last_date=current_date
        except:year='2022'

        if daily_losses>=3:continue
        risk_amt=min(current_capital*0.05,2500)

        if not in_trade:
            action,score,atr=generate_signal(df5,df15)
            if action and atr>0:
                sl_pts=atr*1.5
                t2_pts=sl_pts*2.5
                lots=max(1,int(risk_amt/(sl_pts*lot)))
                lots=min(lots,2)
                entry_price=df5['close'].iloc[-1]
                in_trade=True;trade_action=action
                sl=sl_pts;t2=t2_pts
                entry_idx=i;current_lots=lots;t1_hit=False
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
                    pnl=(row['close']-entry_price)*lot*current_lots;reason='TO'
            else:
                if not t1_hit and row['low']<=entry_price-(t2*0.5):
                    t1_hit=True;sl=0
                if row['high']>=entry_price+sl:
                    pnl=-sl*lot*current_lots;reason='SL'
                elif row['low']<=entry_price-t2:
                    pnl=t2*lot*current_lots;reason='T2'
                elif bars>=30:
                    pnl=(entry_price-row['close'])*lot*current_lots;reason='TO'

            if reason:
                net_pnl=pnl-BROKERAGE
                current_capital+=net_pnl
                if pnl<0:daily_losses+=1;losses+=1
                else:wins+=1
                if current_capital>peak_capital:peak_capital=current_capital
                dd=((peak_capital-current_capital)/peak_capital)*100
                if dd>max_drawdown:max_drawdown=dd
                yearly_pnl[year]=yearly_pnl.get(year,0)+net_pnl
                in_trade=False;t1_hit=False

    total=wins+losses
    if total==0:return None
    wr=round((wins/total)*100,1)
    total_return=round(((current_capital-capital)/capital)*100,1)

    result={
        'symbol':symbol,
        'total_trades':total,
        'wins':wins,'losses':losses,
        'win_rate':wr,
        'total_pnl':round(current_capital-capital,2),
        'total_return':total_return,
        'max_drawdown':round(max_drawdown,1),
        'yearly_pnl':yearly_pnl,
        'final_capital':round(current_capital,2)
    }
    return result

def run_all_stock_backtests(capital=50000):
    print(f'\n{"="*55}')
    print(f'  STOCK BACKTEST RESULTS (Capital: Rs.{capital:,.0f})')
    print(f'{"="*55}')

    results=[]
    for symbol in STOCKS.keys():
        print(f'\n[BT] Testing {symbol}...')
        result=run_stock_backtest(symbol,capital)
        if result:
            results.append(result)
            print(f'  WR:{result["win_rate"]}% Return:{result["total_return"]}% Trades:{result["total_trades"]} DD:{result["max_drawdown"]}%')

    # Sort by total return
    results.sort(key=lambda x:-x['total_return'])

    print(f'\n{"="*55}')
    print(f'  TOP PERFORMING STOCKS')
    print(f'{"="*55}')
    for i,r in enumerate(results[:10]):
        print(f'\n  #{i+1} {r["symbol"]}:')
        print(f'  Return: {r["total_return"]}% | WR: {r["win_rate"]}%')
        print(f'  Trades: {r["total_trades"]} | Drawdown: {r["max_drawdown"]}%')
        print(f'  Final Capital: Rs.{r["final_capital"]:,.0f}')
        for yr,pnl in sorted(r["yearly_pnl"].items()):
            print(f'  {yr}: Rs.{pnl:,.0f}')

    print(f'\n{"="*55}')
    print(f'  POOR PERFORMING STOCKS (Remove these)')
    print(f'{"="*55}')
    for r in results[-5:]:
        print(f'  {r["symbol"]}: Return={r["total_return"]}% WR={r["win_rate"]}%')

    # Save results
    os.makedirs('backtest_results',exist_ok=True)
    json.dump(results,open('backtest_results/stock_backtest.json','w'),indent=2)
    print(f'\n[BT] Results saved!')

    # Top 10 recommendation
    top10=[r['symbol'] for r in results[:10]]
    print(f'\n✅ TOP 10 STOCKS TO TRADE:')
    print(f'{top10}')
    return results

if __name__=='__main__':
    run_all_stock_backtests(capital=50000)
