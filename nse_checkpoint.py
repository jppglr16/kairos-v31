"""NSE Session Checkpoint - sends brief summary at 3:32 PM"""
from v31_trade_journal import trade_journal
from v31_notify import send
from datetime import datetime

today=datetime.now().strftime('%Y-%m-%d')
summary=trade_journal.get_daily_pnl(today)

if summary:
    e='✅' if summary['total_pnl']>0 else '❌'
    msg=(f"📊 NSE Session Done\n"
         f"━━━━━━━━━━━━━━━\n"
         f"{e} P&L: Rs.{summary['total_pnl']:,.0f}\n"
         f"📈 Signals: {summary['total_trades']} | W:{summary['wins']} L:{summary['losses']}\n"
         f"🎯 Win Rate: {summary['win_rate']}%\n"
         f"⏰ MCX opens in 30 mins!")
else:
    msg=("📊 NSE Session Done\n"
         "━━━━━━━━━━━━━━━\n"
         "📭 No completed trades\n"
         "⏰ MCX opens in 30 mins!")

send(msg)
print('NSE checkpoint sent!')
