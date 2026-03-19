import json,os,pandas as pd
from v30_notify import send
from datetime import datetime

NSE=['NIFTY','BANKNIFTY','SENSEX','FINNIFTY','MIDCPNIFTY',
     'LT','NTPC','MARUTI','BHARTIARTL','SBIN',
     'TATAMOTORS','RELIANCE','HINDUNILVR','TCS','TATASTEEL']

today=datetime.now().strftime('%Y-%m-%d')
year=datetime.now().strftime('%Y')

msg='📊 <b>NSE Daily Summary</b>\n'
msg+=f'━━━━━━━━━━━━━━━\n'
msg+=f'📅 {datetime.now().strftime("%d-%b-%Y")}\n\n'

for inst in NSE:
    try:
        candles=[]
        for yr in ['2024',year]:
            fname=f'historical_data/{inst}_{yr}_5min.json'
            if os.path.exists(fname):
                candles.extend(json.load(open(fname)))
        if not candles:continue
        df=pd.DataFrame(candles,columns=['time','open','high','low','close','volume'])
        for c in ['open','high','low','close']:
            df[c]=pd.to_numeric(df[c],errors='coerce')
        df=df.dropna().sort_values('time').reset_index(drop=True)
        day=df[df['time'].str.startswith(today)]
        if len(day)==0:continue
        o=float(day.iloc[0]['open'])
        h=float(day['high'].max())
        l=float(day['low'].min())
        c=float(day.iloc[-1]['close'])
        chg=round((c-o)/o*100,2)
        emoji='🟢' if chg>=0 else '🔴'
        msg+=f'{emoji} {inst}: {c:.1f} ({chg:+.2f}%)\n'
    except:pass

msg+=f'\n🕐 {datetime.now().strftime("%H:%M")}'
send(msg)
print('NSE summary sent!')
