"""
V31 Execution Tracker
Tracks every order: approved → placed → executed/failed
Detects execution gaps vs strategy gaps
"""
import json,os,logging
from datetime import datetime
log=logging.getLogger(__name__)

class ExecutionTracker:
    def __init__(self):
        self.file='execution_log.json'
        self._load()

    def _get_filename(self):
        """Fix 4: Daily rotation!"""
        today=datetime.now().strftime('%Y-%m-%d')
        return f'execution_log_{today}.json'

    def _load(self):
        try:
            self.file=self._get_filename()
            if os.path.exists(self.file):
                self.data=json.load(open(self.file))
            else:
                self.data={'trades':[]}
        except:
            self.data={'trades':[]}

    def _save(self):
        try:
            with open(self.file,'w') as f:
                json.dump(self.data,f,indent=2)
        except Exception as e:
            log.error(f'[EXEC] Save error: {e}')

    def approved(self,instrument,action,score,path,lots):
        """Signal approved for trading"""
        trade={
            'id':f'{instrument}_{datetime.now().strftime("%Y%m%d_%H%M%S")}',
            'time':datetime.now().isoformat(),
            'instrument':instrument,
            'action':action,
            'score':score,
            'path':path,
            'lots':lots,
            'status':'APPROVED',
            'order_id':None,
            'entry_price':None,
            'exit_price':None,
            'pnl':None,
            'fail_reason':None,
        }
        self.data['trades'].append(trade)
        self._save()
        log.info(f'[EXEC] {instrument} APPROVED path={path} score={score}')
        return trade['id']

    def placed(self,trade_id,order_id,entry_price):
        """Order placed successfully"""
        for t in self.data['trades']:
            if t['id']==trade_id:
                t['status']='PLACED'
                t['order_id']=order_id
                t['entry_price']=entry_price
                self._save()
                log.info(f'[EXEC] {t["instrument"]} PLACED order={order_id}')
                return
        log.warning(f'[EXEC] trade_id {trade_id} not found!')

    def executed(self,trade_id,entry_price,status='COMPLETE'):
        """Order fully executed - handles COMPLETE/FILLED"""
        for t in self.data['trades']:
            if t['id']==trade_id:
                t['status']='EXECUTED'
                t['entry_price']=entry_price
                self._save()
                log.info(f'[EXEC] {t["instrument"]} EXECUTED @ {entry_price}')
                return

    def failed(self,trade_id,reason):
        """Order failed"""
        for t in self.data['trades']:
            if t['id']==trade_id:
                t['status']='FAILED'
                t['fail_reason']=reason
                self._save()
                log.warning(f'[EXEC] {t["instrument"]} FAILED: {reason}')
                return

    def closed(self,trade_id,exit_price,result,lot_size=1,lots=1,charges=80):
        """Trade closed with accurate PnL"""
        for t in self.data['trades']:
            if t['id']==trade_id:
                t['status']=result
                t['exit_price']=exit_price
                # Fix 5: Accurate PnL!
                entry=t.get('entry_price',0) or 0
                raw_pnl=(exit_price-entry)*lot_size*lots
                if t.get('action')=='SELL':
                    raw_pnl=-raw_pnl
                pnl=raw_pnl-charges  # Deduct brokerage
                t['pnl']=round(pnl,2)
                self._save()
                icon='🎯' if result=='WIN' else '🛑'
                log.info(f'[EXEC] {t["instrument"]} {icon} {result} pnl={pnl}')
                return

    def daily_report(self):
        """Generate daily execution report"""
        today=datetime.now().strftime('%Y-%m-%d')
        trades=[t for t in self.data['trades']
                if t['time'].startswith(today)]

        approved=len(trades)
        placed=len([t for t in trades if t['status'] in ['PLACED','EXECUTED','WIN','LOSS']])
        executed=len([t for t in trades if t['status'] in ['EXECUTED','WIN','LOSS']])
        failed=len([t for t in trades if t['status']=='FAILED'])
        wins=len([t for t in trades if t['status']=='WIN'])
        losses=len([t for t in trades if t['status']=='LOSS'])
        closed=wins+losses
        total_pnl=sum(t['pnl'] or 0 for t in trades if t['pnl'])

        print('='*50)
        print(f'📊 Execution Report - {today}')
        print('='*50)
        print(f'Approved:  {approved}')
        print(f'Placed:    {placed}')
        print(f'Executed:  {executed}')
        print(f'Failed:    {failed}')

        # Gap detection
        gap=approved-executed-failed
        if gap>0:
            print(f'⚠️  Gap:     {gap} (approved but not executed!)')
        if failed>0:
            print(f'🚨 Failures: {failed}')
            reasons=[t.get('fail_reason','?') for t in trades if t['status']=='FAILED']
            for r in set(reasons):
                print(f'   → {r}: {reasons.count(r)}x')

        # Performance
        wr=f'{wins/closed*100:.1f}%' if closed>0 else 'N/A'
        print(f'\nWins:      {wins}')
        print(f'Losses:    {losses}')
        print(f'Win Rate:  {wr}')
        print(f'Total P&L: Rs.{total_pnl:.0f}')

        # Path breakdown
        print('\nPath Performance:')
        for path in ['A_SMART','B_VWAP','C_ORB','D_SUPERTREND']:
            pt=[t for t in trades if t.get('path')==path]
            pw=[t for t in pt if t['status']=='WIN']
            pl=[t for t in pt if t['status']=='LOSS']
            pc=len(pw)+len(pl)
            pwr=f'{len(pw)/pc*100:.0f}%' if pc>0 else 'N/A'
            if pt:print(f'  {path:<15}: {len(pt)} trades WR={pwr}')

        print('='*50)
        return {'approved':approved,'executed':executed,
                'failed':failed,'wins':wins,'losses':losses,'pnl':total_pnl}

# Global instance
execution_tracker=ExecutionTracker()
