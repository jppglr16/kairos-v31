import requests,logging
from datetime import datetime
log=logging.getLogger(__name__)

BOT_TOKEN='8623010355:AAEnUfLlo5drxyd_sYVMCEv5CcANOz13c8M'
CHAT_ID='8436318442'

def send(msg):
    try:
        url=f'https://api.telegram.org/bot{BOT_TOKEN}/sendMessage'
        r=requests.post(url,json={'chat_id':CHAT_ID,'text':msg,'parse_mode':'HTML'},timeout=5)
        return r.json().get('ok',False)
    except Exception as e:
        log.error(f'[NOTIFY] {e}')
        return False

def notify_startup(capital):
    send(f"""🚀 <b>Kairos V30 Started!</b>
━━━━━━━━━━━━━━━
💰 Capital: ₹{capital:,.0f}
📊 Instruments: NIFTY,BANKNIFTY,FINNIFTY,MIDCPNIFTY,SENSEX,CRUDEOIL,GOLDM,SILVERM
🧠 AI: SMC+ML+RL+OI+PCR Active
🕐 Time: {datetime.now().strftime('%d-%b-%Y %H:%M')}
✅ All systems ready!""")

def notify_entry(signal,qty,symbol):
    action=signal['action']
    inst=signal['instrument']
    price=signal['price']
    sl=signal['sl_points']
    t1=signal['target1']
    t2=signal['target2']
    conf=signal.get('ai_confidence',0)
    pcr=signal.get('pcr','N/A')
    market=signal.get('market_condition','')
    emoji='🟢' if action=='BUY' else '🔴'
    send(f"""{emoji} <b>TRADE ENTRY</b>
━━━━━━━━━━━━━━━
📊 <b>{inst}</b> | {signal['option_type']}
🎯 Action: <b>{action}</b>
📌 Symbol: {symbol}
📦 Qty: {qty}
💵 Entry Price: <b>{price:.0f}</b>
🛑 Stop Loss: {price-sl:.0f} <i>(-{sl:.0f}pts)</i>
🎯 Target 1: {price+t1:.0f} <i>(+{t1:.0f}pts)</i>
🎯 Target 2: {price+t2:.0f} <i>(+{t2:.0f}pts)</i>
🧠 Confidence: {conf}/100
📈 PCR: {pcr}
🌊 Market: {market}
🕐 {datetime.now().strftime('%H:%M:%S')}""")

def notify_exit(instrument,reason,pnl,entry,exit_price):
    if pnl>0:
        emoji='🎯';status='PROFIT'
    else:
        emoji='❌';status='LOSS'
    send(f"""{emoji} <b>EXIT - {reason}</b>
━━━━━━━━━━━━━━━
📊 <b>{instrument}</b>
💵 Entry: {entry:.0f}
💵 Exit: {exit_price:.0f}
{'✅' if pnl>0 else '🔴'} PnL: <b>₹{pnl:,.0f}</b>
🕐 {datetime.now().strftime('%H:%M:%S')}""")

def notify_sl_hit(instrument,pnl):
    send(f"""🛑 <b>STOP LOSS HIT</b>
━━━━━━━━━━━━━━━
📊 {instrument}
❌ Loss: ₹{abs(pnl):,.0f}
🕐 {datetime.now().strftime('%H:%M:%S')}""")

def notify_target_hit(instrument,target,pnl):
    send(f"""🎯 <b>TARGET {target} HIT!</b>
━━━━━━━━━━━━━━━
📊 {instrument}
✅ Profit: ₹{pnl:,.0f}
🕐 {datetime.now().strftime('%H:%M:%S')}""")

def notify_daily_summary(trades,wins,losses,pnl,capital):
    emoji='📈' if pnl>0 else '📉'
    wr=int((wins/trades)*100) if trades>0 else 0
    send(f"""{emoji} <b>DAILY SUMMARY</b>
━━━━━━━━━━━━━━━
📅 {datetime.now().strftime('%d-%b-%Y')}
📊 Total Trades: {trades}
✅ Wins: {wins} | ❌ Loss: {losses}
🎯 Win Rate: {wr}%
💰 Daily PnL: <b>₹{pnl:,.0f}</b>
🏦 Capital: ₹{capital:,.0f}
━━━━━━━━━━━━━━━
{'🚀 Great Day!' if pnl>5000 else '👍 Good Day!' if pnl>0 else '💪 Tomorrow will be better!'}""")

def notify_stopped(reason,daily_pnl):
    send(f"""⚠️ <b>TRADING STOPPED</b>
━━━━━━━━━━━━━━━
Reason: {reason}
Daily PnL: ₹{daily_pnl:,.0f}
🕐 {datetime.now().strftime('%H:%M:%S')}""")

def notify_error(msg):
    send(f'⚠️ <b>V30 ERROR</b>\n{msg}')
