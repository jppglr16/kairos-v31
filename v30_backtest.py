import json,os,time,logging
import pandas as pd
import numpy as np
from datetime import datetime,timedelta
import pyotp
from SmartApi import SmartConnect

log=logging.getLogger(__name__)

ANGEL_CONFIG={
    'api_key':'pEOas0vU',
    'client_id':'J234619',
    'mpin':'1605',
    'totp_secret':'R2T2F2BMP56U44O4OMOYJZTFJI'
}

SYMBOLS={
    'NIFTY':     {'token':'99926000','exchange':'NSE'},
    'BANKNIFTY': {'token':'99926009','exchange':'NSE'},
    'FINNIFTY':  {'token':'99926037','exchange':'NSE'},
    'MIDCPNIFTY':{'token':'99926074','exchange':'NSE'},
    'CRUDEOIL':  {'token':'472790','exchange':'MCX'},
    'GOLDM':     {'token':'477904','exchange':'MCX'},
    'SILVERM':   {'token':'457533','exchange':'MCX'},
}

def get_client():
    obj=SmartConnect(api_key=ANGEL_CONFIG['api_key'])
    totp=pyotp.TOTP(ANGEL_CONFIG['totp_secret']).now()
    obj.generateSession(ANGEL_CONFIG['client_id'],ANGEL_CONFIG['mpin'],totp)
    return obj

def fetch_year_data(client,instrument,year,interval='FIVE_MINUTE'):
    sym=SYMBOLS[instrument]
    all_candles=[]
    # Fetch quarter by quarter to avoid rate limits
    quarters=[
        (f'{year}-01-01',f'{year}-03-31'),
        (f'{year}-04-01',f'{year}-06-30'),
        (f'{year}-07-01',f'{year}-09-30'),
        (f'{year}-10-01',f'{year}-12-31'),
    ]
    for start,end in quarters:
        try:
            time.sleep(3)
            params={
                'exchange':sym['exchange'],
                'symboltoken':sym['token'],
                'interval':interval,
                'fromdate':f'{start} 09:00',
                'todate':f'{end} 23:30'
            }
            data=client.getCandleData(params)
            if data and data.get('data'):
                all_candles.extend(data['data'])
                print(f'[BT] {instrument} {year} {start}: {len(data["data"])} candles')
        except Exception as e:
            print(f'[BT] Error {instrument} {year} {start}: {e}')
    return all_candles

def save_historical_data(instrument,year,candles):
    os.makedirs('historical_data',exist_ok=True)
    fname=f'historical_data/{instrument}_{year}_5min.json'
    json.dump(candles,open(fname,'w'))
    print(f'[BT] Saved {len(candles)} candles to {fname}')

def load_historical_data(instrument,year):
    fname=f'historical_data/{instrument}_{year}_5min.json'
    if os.path.exists(fname):
        return json.load(open(fname))
    return []

def candles_to_df(candles):
    if not candles:return None
    df=pd.DataFrame(candles,columns=['time','open','high','low','close','volume'])
    df['open']=df['open'].astype(float)
    df['high']=df['high'].astype(float)
    df['low']=df['low'].astype(float)
    df['close']=df['close'].astype(float)
    df['volume']=df['volume'].astype(float)
    return df

def run_backtest(instrument,df,capital=50000):
    from v30_smc import get_smc_signal
    from v30_momentum import get_momentum_signal,detect_market_condition
    from v30_strategy import detect_fvg,detect_liq_sweep,count_conf

    results=[]
    wins=0;losses=0;total_pnl=0
    min_candles=30

    LOT={'NIFTY':75,'BANKNIFTY':30,'FINNIFTY':65,'MIDCPNIFTY':120,'CRUDEOIL':100,'GOLDM':10,'SILVERM':30}
    lot=LOT.get(instrument,25)

    for i in range(min_candles,len(df)-20,5):
        try:
            df5=df.iloc[i-30:i].copy()
            df15=df.iloc[max(0,i-90):i:3].copy()
            if len(df5)<20 or len(df15)<10:continue

            smc=get_smc_signal(df5,df15)
            mom=get_momentum_signal(df5)
            market=detect_market_condition(df15)
            fvg=detect_fvg(df5)
            liq=detect_liq_sweep(df5)

            if not smc['action']:continue
            action=smc['action']
            conf=count_conf(smc,mom,fvg,liq,action)
            if conf<4:continue

            atr=(df5['high']-df5['low']).tail(14).mean()
            sl=atr*1.5
            t1=sl*1.5
            t2=sl*2.5

            entry_price=df5['close'].iloc[-1]
            # Simulate next 20 candles
            future=df.iloc[i:i+20]
            exit_price=entry_price
            exit_reason='TIMEOUT'
            pnl=0

            for j,row in future.iterrows():
                if action=='BUY':
                    if row['low']<=entry_price-sl:
                        exit_price=entry_price-sl
                        exit_reason='SL'
                        pnl=-sl*lot
                        break
                    elif row['high']>=entry_price+t2:
                        exit_price=entry_price+t2
                        exit_reason='T2'
                        pnl=t2*lot
                        break
                else:
                    if row['high']>=entry_price+sl:
                        exit_price=entry_price+sl
                        exit_reason='SL'
                        pnl=-sl*lot
                        break
                    elif row['low']<=entry_price-t2:
                        exit_price=entry_price-t2
                        exit_reason='T2'
                        pnl=t2*lot
                        break

            if exit_reason=='TIMEOUT':
                pnl=(future['close'].iloc[-1]-entry_price)*lot if action=='BUY' else (entry_price-future['close'].iloc[-1])*lot

            total_pnl+=pnl
            if pnl>0:wins+=1
            else:losses+=1

            results.append({
                'time':str(df5.index[-1]) if hasattr(df5.index[-1],'strftime') else str(i),
                'action':action,'entry':entry_price,'exit':exit_price,
                'reason':exit_reason,'pnl':round(pnl,2),'conf':conf,
                'market':market
            })
        except Exception as e:
            continue

    total_trades=wins+losses
    win_rate=round((wins/total_trades)*100,1) if total_trades>0 else 0
    summary={
        'instrument':instrument,
        'total_trades':total_trades,
        'wins':wins,'losses':losses,
        'win_rate':win_rate,
        'total_pnl':round(total_pnl,2),
        'avg_pnl':round(total_pnl/total_trades,2) if total_trades>0 else 0,
        'results':results
    }
    print(f'[BT] {instrument}: Trades={total_trades} WR={win_rate}% PnL=₹{total_pnl:.0f}')
    return summary

def download_all_historical():
    print('[BT] Downloading 3 years historical data...')
    client=get_client()
    for instrument in ['NIFTY','BANKNIFTY','CRUDEOIL']:
        for year in [2022,2023,2024]:
            existing=load_historical_data(instrument,year)
            if len(existing)>1000:
                print(f'[BT] {instrument} {year} already exists ({len(existing)} candles)')
                continue
            time.sleep(3)
            candles=fetch_year_data(client,instrument,year)
            if candles:
                save_historical_data(instrument,year,candles)
            time.sleep(5)
    print('[BT] Download complete!')

def run_full_backtest():
    print('[BT] Running full backtest...')
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
        result=run_backtest(instrument,df)
        all_results[instrument]=result
        # Save results
        os.makedirs('backtest_results',exist_ok=True)
        json.dump(result,open(f'backtest_results/{instrument}_backtest.json','w'),indent=2)
    return all_results

def train_ml_from_backtest():
    print('[BT] Training ML from backtest results...')
    try:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.model_selection import train_test_split
        import pickle

        all_features=[]
        all_labels=[]

        for instrument in ['NIFTY','BANKNIFTY','CRUDEOIL']:
            fname=f'backtest_results/{instrument}_backtest.json'
            if not os.path.exists(fname):continue
            data=json.load(open(fname))
            for trade in data.get('results',[]):
                try:
                    features=[
                        trade.get('conf',0),
                        1 if trade.get('market')=='UPTREND' else -1 if trade.get('market')=='DOWNTREND' else 0,
                        1 if trade.get('action')=='BUY' else -1,
                    ]
                    label=1 if trade.get('pnl',0)>0 else 0
                    all_features.append(features)
                    all_labels.append(label)
                except:continue

        if len(all_features)<50:
            print(f'[BT] Not enough data: {len(all_features)} trades')
            return None

        X=np.array(all_features)
        y=np.array(all_labels)
        X_train,X_test,y_train,y_test=train_test_split(X,y,test_size=0.2)
        clf=RandomForestClassifier(n_estimators=100,random_state=42)
        clf.fit(X_train,y_train)
        score=clf.score(X_test,y_test)
        print(f'[BT] ML Model accuracy: {score*100:.1f}%')
        pickle.dump(clf,open('v30_ml_model.pkl','wb'))
        print('[BT] Model saved to v30_ml_model.pkl')
        return clf,score
    except Exception as e:
        print(f'[BT] ML training error: {e}')
        return None

def weekly_retrain():
    print('[BT] Weekly retrain started...')
    download_all_historical()
    results=run_full_backtest()
    model=train_ml_from_backtest()
    if model:
        clf,score=model
        print(f'[BT] Retrain complete! Model accuracy: {score*100:.1f}%')
    return results

if __name__=='__main__':
    weekly_retrain()
