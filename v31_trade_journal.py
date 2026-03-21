"""
V31 Trade Journal
Complete trade lifecycle tracking
Entry → Exit → P&L → Statistics
"""
import json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

JOURNAL_FILE='trade_journal.json'

class TradeJournal:
    def __init__(self):
        self.trades=[]
        self.load()

    def load(self):
        try:
            if os.path.exists(JOURNAL_FILE):
                self.trades=json.load(open(JOURNAL_FILE))
                log.info(f'[JOURNAL] Loaded {len(self.trades)} trades')
        except:
            self.trades=[]

    def save(self):
        try:
            json.dump(self.trades,open(JOURNAL_FILE,'w'),indent=2)
        except Exception as e:
            log.error(f'[JOURNAL] Save error: {e}')

    def record_entry(self,instrument,direction,score,
                     entry_prem,lot,signal={}):
        """Record trade entry"""
        trade={
            'id':f'{instrument}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'date':datetime.now().strftime('%Y-%m-%d'),
            'time':datetime.now().strftime('%H:%M:%S'),
            'instrument':instrument,
            'direction':direction,
            'score':score,
            'entry_prem':entry_prem,
            'lot':lot,
            'total_cost':entry_prem*lot,
            'sl_prem':round(entry_prem*0.40),
            't1_prem':round(entry_prem*1.50),
            't2_prem':round(entry_prem*2.50),
            'regime':signal.get('regime',''),
            'sl_type':signal.get('sl_type',''),
            'liq_type':signal.get('liq_type',''),
            'ml_prob':signal.get('ml_prob',0),
            'exit_prem':None,
            'exit_time':None,
            'exit_reason':None,
            'pnl_per_unit':None,
            'pnl_total':None,
            'pnl_pct':None,
            'result':None,  # WIN/LOSS/BREAKEVEN
            'status':'OPEN',
        }
        self.trades.append(trade)
        self.save()
        log.info(f'[JOURNAL] Entry: {instrument} {direction} @ Rs.{entry_prem}')
        return trade['id']

    def record_exit(self,trade_id,exit_prem,reason):
        """Record trade exit + calculate P&L"""
        for t in self.trades:
            if t['id']==trade_id and t['status']=='OPEN':
                t['exit_prem']=exit_prem
                t['exit_time']=datetime.now().strftime('%H:%M:%S')
                t['exit_reason']=reason
                t['status']='CLOSED'

                # Calculate P&L
                entry=t['entry_prem']
                lot=t['lot']
                pnl_unit=exit_prem-entry
                pnl_total=pnl_unit*lot
                pnl_pct=round((exit_prem-entry)/entry*100,1)

                t['pnl_per_unit']=round(pnl_unit,2)
                t['pnl_total']=round(pnl_total,2)
                t['pnl_pct']=pnl_pct

                # Result
                if pnl_total>0:
                    t['result']='WIN'
                elif pnl_total<0:
                    t['result']='LOSS'
                else:
                    t['result']='BREAKEVEN'

                self.save()
                log.info(f'[JOURNAL] Exit: {t["instrument"]} '
                        f'pnl=Rs.{pnl_total:,.0f} ({pnl_pct:+.1f}%) {t["result"]}')
                return t
        return None

    def get_daily_pnl(self,date=None):
        """Get P&L summary for a date"""
        if date is None:
            date=datetime.now().strftime('%Y-%m-%d')

        day_trades=[t for t in self.trades
                   if t['date']==date and t['status']=='CLOSED']

        if not day_trades:
            return None

        total_pnl=sum(t['pnl_total'] for t in day_trades)
        wins=[t for t in day_trades if t['result']=='WIN']
        losses=[t for t in day_trades if t['result']=='LOSS']

        return {
            'date':date,
            'total_trades':len(day_trades),
            'wins':len(wins),
            'losses':len(losses),
            'win_rate':round(len(wins)/len(day_trades)*100,1),
            'total_pnl':round(total_pnl,2),
            'avg_win':round(sum(t['pnl_total'] for t in wins)/len(wins),2) if wins else 0,
            'avg_loss':round(sum(t['pnl_total'] for t in losses)/len(losses),2) if losses else 0,
            'best_trade':max(day_trades,key=lambda x:x['pnl_total'])['instrument'],
            'worst_trade':min(day_trades,key=lambda x:x['pnl_total'])['instrument'],
        }

    def get_weekly_pnl(self):
        """Get last 5 trading days P&L"""
        from collections import defaultdict
        by_date=defaultdict(list)
        for t in self.trades:
            if t['status']=='CLOSED':
                by_date[t['date']].append(t)

        weekly=[]
        for date in sorted(by_date.keys())[-5:]:
            trades=by_date[date]
            pnl=sum(t['pnl_total'] for t in trades)
            wins=sum(1 for t in trades if t['result']=='WIN')
            weekly.append({
                'date':date,
                'trades':len(trades),
                'wins':wins,
                'pnl':round(pnl,2),
                'wr':round(wins/len(trades)*100,1) if trades else 0
            })
        return weekly

    def send_daily_report(self):
        """Send daily P&L to Telegram"""
        try:
            from v31_notify import send
            summary=self.get_daily_pnl()

            if not summary:
                send('📊 Daily Summary\n━━━━━━━━━━━━━━━\n'
                     f'📅 {datetime.now().strftime("%d-%b-%Y")}\n'
                     '📭 No completed trades today')
                return

            emoji='✅' if summary['total_pnl']>0 else '❌'
            msg=f"""📊 Daily P&L Summary
━━━━━━━━━━━━━━━
📅 {summary['date']}
{emoji} P&L: Rs.{summary['total_pnl']:,.0f}
📈 Trades: {summary['total_trades']}
✅ Wins: {summary['wins']} | ❌ Losses: {summary['losses']}
🎯 Win Rate: {summary['win_rate']}%
💰 Avg Win: Rs.{summary['avg_win']:,.0f}
💸 Avg Loss: Rs.{summary['avg_loss']:,.0f}
🏆 Best: {summary['best_trade']}
⚠️ Worst: {summary['worst_trade']}"""
            send(msg)
            log.info(f'[JOURNAL] Daily report sent: Rs.{summary["total_pnl"]:,.0f}')
        except Exception as e:
            log.error(f'[JOURNAL] Report error: {e}')

# Global instance
trade_journal=TradeJournal()
