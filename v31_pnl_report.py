"""
V31 EOD P&L Report
Sends daily P&L summary to Telegram
Run after 3:30 PM (NSE) and 11:30 PM (MCX)
"""
from datetime import datetime
import json,os,glob
from v30_notify import send

def get_pnl_report():
    today=datetime.now().strftime('%Y-%m-%d')
    
    # Load today's execution log
    log_file=f'execution_log_{today}.json'
    trades=[]
    if os.path.exists(log_file):
        trades=json.load(open(log_file))
    
    # Also check v31_log for paper trades
    wins=0;losses=0;total_pnl=0
    trade_details=[]
    
    try:
        with open('v31_log.txt') as f:
            lines=[l for l in f if today in l]
        
        for line in lines:
            if 'PAPER' in line and 'profit' in line.lower():
                wins+=1
            elif 'PAPER' in line and 'loss' in line.lower():
                losses+=1
    except:pass
    
    # Build report
    total=wins+losses
    wr=round(wins/total*100) if total>0 else 0
    
    msg=f'''📊 V31 Daily P&L Report
━━━━━━━━━━━━━━━
📅 {datetime.now().strftime("%d-%b-%Y")}
💰 Capital: Rs.50,000

📈 Trade Summary:
✅ Wins:   {wins}
❌ Losses: {losses}
📊 Total:  {total}
🎯 Win Rate: {wr}%

💵 P&L: Rs.{total_pnl:,.0f}
━━━━━━━━━━━━━━━
🕐 {datetime.now().strftime("%H:%M")}'''
    
    send(msg)
    print('P&L report sent!')
    return msg

if __name__=='__main__':
    get_pnl_report()
