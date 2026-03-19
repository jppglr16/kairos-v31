import json,os,logging
from datetime import datetime,timedelta
from collections import defaultdict
log=logging.getLogger(__name__)

PNL_FILE='trade_log.json'

class PnLTracker:
    """
    Complete P&L tracking:
    Daily / Weekly / Monthly / Yearly
    Per instrument breakdown
    Win rate analysis
    """

    def get_all_trades(self):
        try:
            if not os.path.exists(PNL_FILE):return []
            return json.load(open(PNL_FILE))
        except:return []

    def get_completed_trades(self):
        return [t for t in self.get_all_trades() if t.get('result') and t.get('pnl') is not None]

    # ============================================================
    # DAILY P&L
    # ============================================================
    def daily_pnl(self,date=None):
        if not date:date=datetime.now().strftime('%Y-%m-%d')
        trades=self.get_completed_trades()
        day_trades=[t for t in trades if t.get('time','').startswith(date)]
        return self._calculate_stats(day_trades,f'Daily ({date})')

    # ============================================================
    # WEEKLY P&L
    # ============================================================
    def weekly_pnl(self):
        today=datetime.now()
        week_start=today-timedelta(days=today.weekday())
        trades=self.get_completed_trades()
        week_trades=[t for t in trades
                    if t.get('time','')[:10]>=week_start.strftime('%Y-%m-%d')]
        return self._calculate_stats(week_trades,
            f'Weekly ({week_start.strftime("%d%b")} - {today.strftime("%d%b%y")})')

    # ============================================================
    # MONTHLY P&L
    # ============================================================
    def monthly_pnl(self,month=None):
        if not month:month=datetime.now().strftime('%Y-%m')
        trades=self.get_completed_trades()
        month_trades=[t for t in trades if t.get('time','').startswith(month)]
        return self._calculate_stats(month_trades,f'Monthly ({month})')

    # ============================================================
    # YEARLY P&L
    # ============================================================
    def yearly_pnl(self,year=None):
        if not year:year=str(datetime.now().year)
        trades=self.get_completed_trades()
        year_trades=[t for t in trades if t.get('time','').startswith(year)]
        return self._calculate_stats(year_trades,f'Yearly ({year})')

    # ============================================================
    # STATS CALCULATOR
    # ============================================================
    def _calculate_stats(self,trades,period):
        if not trades:
            return {
                'period':period,
                'total_trades':0,
                'wins':0,'losses':0,
                'win_rate':0,
                'total_pnl':0,
                'avg_win':0,'avg_loss':0,
                'best_trade':0,'worst_trade':0,
                'profit_factor':0,
                'by_instrument':{}
            }

        wins=[t for t in trades if t.get('result')=='WIN']
        losses=[t for t in trades if t.get('result')=='LOSS']

        total_pnl=sum(t.get('pnl',0) for t in trades)
        gross_profit=sum(t.get('pnl',0) for t in wins) if wins else 0
        gross_loss=abs(sum(t.get('pnl',0) for t in losses)) if losses else 0

        # By instrument
        by_inst=defaultdict(lambda:{'trades':0,'pnl':0,'wins':0})
        for t in trades:
            inst=t.get('instrument','Unknown')
            by_inst[inst]['trades']+=1
            by_inst[inst]['pnl']+=t.get('pnl',0)
            if t.get('result')=='WIN':
                by_inst[inst]['wins']+=1

        return {
            'period':period,
            'total_trades':len(trades),
            'wins':len(wins),
            'losses':len(losses),
            'win_rate':round(len(wins)/len(trades)*100,1) if trades else 0,
            'total_pnl':round(total_pnl,2),
            'gross_profit':round(gross_profit,2),
            'gross_loss':round(gross_loss,2),
            'avg_win':round(gross_profit/len(wins),2) if wins else 0,
            'avg_loss':round(gross_loss/len(losses),2) if losses else 0,
            'best_trade':round(max((t.get('pnl',0) for t in trades),default=0),2),
            'worst_trade':round(min((t.get('pnl',0) for t in trades),default=0),2),
            'profit_factor':round(gross_profit/gross_loss,2) if gross_loss>0 else 0,
            'by_instrument':dict(by_inst)
        }

    # ============================================================
    # TELEGRAM REPORTS
    # ============================================================
    def _split_nse_mcx(self,by_instrument):
        """Split instruments into NSE and MCX"""
        MCX=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        nse={k:v for k,v in by_instrument.items() if k not in MCX}
        mcx={k:v for k,v in by_instrument.items() if k in MCX}
        return nse,mcx

    def send_daily_report(self):
        from v30_notify import send
        from datetime import datetime
        stats=self.daily_pnl()
        emoji='🟢' if stats['total_pnl']>=0 else '🔴'
        today=datetime.now().strftime('%Y-%m-%d')

        MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        done=self.get_completed_trades()
        nse=[t for t in done if t.get('instrument') not in MCX_INST and t.get('time','').startswith(today)]
        mcx=[t for t in done if t.get('instrument') in MCX_INST and t.get('time','').startswith(today)]
        nse_pnl=sum(t.get('pnl',0) for t in nse)
        mcx_pnl=sum(t.get('pnl',0) for t in mcx)

        lines=[
            f"{emoji} Daily P&L Report",
            "━━━━━━━━━━━━━━━",
            f"📅 {stats['period']}",
            f"📊 Trades: {stats['total_trades']} | ✅ {stats['wins']} | ❌ {stats['losses']}",
            f"🎯 Win Rate: {stats['win_rate']}%",
            f"💰 Net P&L: Rs.{stats['total_pnl']:,.0f}",
            f"📈 Profit Factor: {stats['profit_factor']}x",
            "",
            f"🏛 NSE: Rs.{nse_pnl:,.0f} ({len(nse)} trades)",
            f"⚡ MCX: Rs.{mcx_pnl:,.0f} ({len(mcx)} trades)",
            "",
            f"🏆 Best: Rs.{stats['best_trade']:,.0f}",
            f"💣 Worst: Rs.{stats['worst_trade']:,.0f}",
        ]

        nse_inst,mcx_inst=self._split_nse_mcx(stats['by_instrument'])

        if nse_inst:
            lines.append("")
            lines.append("📋 NSE Breakdown:")
            for inst,data in sorted(nse_inst.items(),key=lambda x:x[1]['pnl'],reverse=True):
                wr=round(data['wins']/data['trades']*100) if data['trades']>0 else 0
                e='✅' if data['pnl']>=0 else '❌'
                lines.append(f"{e} {inst}: Rs.{data['pnl']:,.0f} ({data['trades']}T {wr}%WR)")

        if mcx_inst:
            lines.append("")
            lines.append("⛽ MCX Breakdown:")
            for inst,data in sorted(mcx_inst.items(),key=lambda x:x[1]['pnl'],reverse=True):
                wr=round(data['wins']/data['trades']*100) if data['trades']>0 else 0
                e='✅' if data['pnl']>=0 else '❌'
                lines.append(f"{e} {inst}: Rs.{data['pnl']:,.0f} ({data['trades']}T {wr}%WR)")

        send('\n'.join(lines))
        return stats

    def send_weekly_report(self):
        from v30_notify import send
        stats=self.weekly_pnl()
        emoji='🟢' if stats['total_pnl']>=0 else '🔴'
        msg=f"""{emoji} <b>Weekly P&L Report</b>
━━━━━━━━━━━━━━━
📅 {stats['period']}
📊 Trades: {stats['total_trades']} | ✅ {stats['wins']} | ❌ {stats['losses']}
🎯 Win Rate: {stats['win_rate']}%
💰 Net P&L: Rs.{stats['total_pnl']:,.0f}
📈 Profit Factor: {stats['profit_factor']}x
🏆 Best Trade: Rs.{stats['best_trade']:,.0f}"""
        send(msg)
        return stats

    def send_monthly_report(self):
        from v30_notify import send
        stats=self.monthly_pnl()
        initial=50000  # Starting capital
        roi=round(stats['total_pnl']/initial*100,1) if initial>0 else 0
        emoji='🟢' if stats['total_pnl']>=0 else '🔴'
        msg=f"""{emoji} <b>Monthly P&L Report</b>
━━━━━━━━━━━━━━━
📅 {stats['period']}
📊 Trades: {stats['total_trades']} | ✅ {stats['wins']} | ❌ {stats['losses']}
🎯 Win Rate: {stats['win_rate']}%
💰 Net P&L: Rs.{stats['total_pnl']:,.0f}
📊 ROI: {roi}%
📈 Profit Factor: {stats['profit_factor']}x
🏆 Best: Rs.{stats['best_trade']:,.0f}
💣 Worst: Rs.{stats['worst_trade']:,.0f}"""

        if stats['by_instrument']:
            msg+='\n\n📋 <b>Top Instruments:</b>'
            top=sorted(stats['by_instrument'].items(),
                      key=lambda x:x[1]['pnl'],reverse=True)[:5]
            for inst,data in top:
                wr=round(data['wins']/data['trades']*100) if data['trades']>0 else 0
                msg+=f"\n• {inst}: Rs.{data['pnl']:,.0f} ({wr}%WR)"
        send(msg)
        return stats

    def send_yearly_report(self):
        from v30_notify import send
        stats=self.yearly_pnl()
        initial=50000
        roi=round(stats['total_pnl']/initial*100,1) if initial>0 else 0
        emoji='🟢' if stats['total_pnl']>=0 else '🔴'
        msg=f"""{emoji} <b>Yearly P&L Report</b>
━━━━━━━━━━━━━━━
📅 {stats['period']}
📊 Total Trades: {stats['total_trades']}
✅ Wins: {stats['wins']} | ❌ Losses: {stats['losses']}
🎯 Win Rate: {stats['win_rate']}%
💰 Net P&L: Rs.{stats['total_pnl']:,.0f}
📊 Annual ROI: {roi}%
📈 Profit Factor: {stats['profit_factor']}x"""
        send(msg)
        return stats


# Global instance
pnl_tracker=PnLTracker()
