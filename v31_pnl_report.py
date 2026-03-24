"""
V31 EOD P&L Report
Sends daily P&L summary to Telegram
Run after 3:30 PM (NSE) and 11:30 PM (MCX)
"""
from datetime import datetime
import json,os,re
from v30_notify import send

def get_pnl_report(session='NSE'):
    today=datetime.now().strftime('%Y-%m-%d')

    wins=0;losses=0;total_pnl=0
    signals=0;blocked=0;allowed=0
    trade_details=[]

    try:
        with open('v31_log.txt') as f:
            lines=[l for l in f if today in l]

        for line in lines:
            if 'SIGNAL:' in line:signals+=1
            if 'BLOCKED' in line:blocked+=1
            if 'ALLOWED' in line:allowed+=1
            if '[PAPER]' in line and 'tracked' in line:
                wins+=1  # Count tracked trades
            if 'WIN' in line:wins+=1
            if 'LOSS' in line:losses+=1

        # Get paper P&L from execution log
        log_file=f'execution_log_{today}.json'
        if os.path.exists(log_file):
            data=json.load(open(log_file))
            for t in data:
                pnl=t.get('pnl',0)
                if pnl:
                    total_pnl+=pnl
                    if pnl>0:wins+=1
                    elif pnl<0:losses+=1
    except Exception as e:
        print(f'Error: {e}')

    total=wins+losses
    wr=round(wins/total*100) if total>0 else 0
    pnl_emoji='📈' if total_pnl>=0 else '📉'

    msg=f'''📊 V31 {session} P&L Report
━━━━━━━━━━━━━━━
📅 {datetime.now().strftime("%d-%b-%Y")}
💰 Capital: Rs.50,000

🔍 Signal Summary:
📡 Generated: {signals}
🚫 Blocked:   {blocked}
✅ Allowed:   {allowed}

📈 Trade Results:
✅ Wins:     {wins}
❌ Losses:   {losses}
📊 Total:    {total}
🎯 Win Rate: {wr}%

{pnl_emoji} P&L: Rs.{total_pnl:+,.0f}
━━━━━━━━━━━━━━━
🕐 {datetime.now().strftime("%H:%M")}
📱 Paper Trade Mode'''

    send(msg)
    print(f'{session} P&L report sent!')
    return msg

if __name__=='__main__':
    import sys
    session=sys.argv[1] if len(sys.argv)>1 else 'NSE'
    get_pnl_report(session)
