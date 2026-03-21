"""
V31 Exit Monitor
Tracks all open positions and exits on SL/Target hit
"""
import time,logging,json,os
from datetime import datetime
from v30_notify import send
log=logging.getLogger(__name__)

POSITIONS_FILE='active_positions.json'

class ExitMonitor:
    def __init__(self):
        self.positions={}  # symbol -> position dict
        self.load_positions()

    def load_positions(self):
        """Load positions from file (survive restarts)"""
        try:
            if os.path.exists(POSITIONS_FILE):
                self.positions=json.load(open(POSITIONS_FILE))
                log.info(f'[EXIT] Loaded {len(self.positions)} positions')
        except:
            self.positions={}

    def save_positions(self):
        """Save positions to file"""
        try:
            json.dump(self.positions,open(POSITIONS_FILE,'w'))
        except:pass

    def add_position(self,signal,qty,prem,option_result):
        """Add new position to track"""
        if not option_result:return

        instrument=signal.get('instrument','')
        action=signal.get('action','BUY')
        sym=option_result.get('symbol','')
        token=option_result.get('token','')
        segment=option_result.get('segment','NFO')
        opt_type='CE' if action=='BUY' else 'PE'

        # SL and targets from signal
        sl=round(prem*0.40)          # SL at -40%
        t1=round(prem*1.50)          # T1 at +50%
        t2=round(prem*2.50)          # T2 at +150%

        pos={
            'instrument':instrument,
            'symbol':sym,
            'token':token,
            'segment':segment,
            'opt_type':opt_type,
            'action':action,
            'entry_prem':prem,
            'qty':qty,
            'lot_size':qty,
            'sl':sl,
            't1':t1,
            't2':t2,
            'entry_time':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'status':'OPEN',
            'partial_exit':False,
        }

        self.positions[sym]=pos
        self.save_positions()
        log.info(f'[EXIT] Tracking {sym} entry={prem} sl={sl} t1={t1} t2={t2}')
        send(f'📊 Position Opened!\n{instrument} {opt_type}\nEntry: Rs.{prem}\nSL: Rs.{sl}\nT1: Rs.{t1}\nT2: Rs.{t2}')

    def check_positions(self,angel_obj):
        """Check all open positions for exit conditions"""
        if not self.positions:return

        closed=[]
        for sym,pos in self.positions.items():
            if pos.get('status')!='OPEN':
                closed.append(sym)
                continue

            try:
                # Get current LTP
                ltp_resp=angel_obj.ltpData(
                    pos['segment'],sym,pos['token'])
                if not ltp_resp or not ltp_resp.get('data'):continue

                ltp=float(ltp_resp['data'].get('ltp',0))
                if ltp<=0:continue

                entry=pos['entry_prem']
                sl=pos['sl']
                t1=pos['t1']
                t2=pos['t2']
                inst=pos['instrument']
                qty=pos['qty']
                pnl=(ltp-entry)*qty

                log.info(f'[EXIT] {inst}: LTP={ltp} SL={sl} T1={t1} T2={t2} PnL={pnl:.0f}')

                # ============================================================
                # EXIT CONDITIONS
                # ============================================================

                # SL Hit
                if ltp<=sl:
                    pnl=(ltp-entry)*qty
                    self._exit_position(sym,pos,ltp,'SL_HIT',pnl)
                    closed.append(sym)

                # T2 Hit (full target)
                elif ltp>=t2:
                    pnl=(ltp-entry)*qty
                    self._exit_position(sym,pos,ltp,'T2_HIT',pnl)
                    closed.append(sym)

                # T1 Hit (partial exit - book 50%)
                elif ltp>=t1 and not pos.get('partial_exit'):
                    pnl=(ltp-entry)*qty*0.5
                    self._partial_exit(sym,pos,ltp,pnl)
                # Update trailing SL
                if pos.get('trail_active') and pos.get('partial_exit'):
                    self._update_trailing_sl(sym,pos,ltp)

                # Time exit: 3:15 PM for NSE options
                elif self._is_time_exit(pos):
                    pnl=(ltp-entry)*qty
                    self._exit_position(sym,pos,ltp,'TIME_EXIT',pnl)
                    closed.append(sym)

            except Exception as e:
                log.error(f'[EXIT] Error checking {sym}: {e}')

        # Remove closed positions
        for sym in closed:
            if sym in self.positions:
                del self.positions[sym]
        if closed:
            self.save_positions()

    def _exit_position(self,sym,pos,exit_prem,reason,pnl):
        """Handle full exit"""
        inst=pos['instrument']
        entry=pos['entry_prem']
        pnl_pct=round((exit_prem-entry)/entry*100,1)
        emoji='✅' if pnl>0 else '❌'

        msg=f"""{emoji} Position Closed!
━━━━━━━━━━━━━━━
📊 {inst} {pos['opt_type']}
🏷️ Reason: {reason}
💵 Entry: Rs.{entry}
💵 Exit: Rs.{exit_prem}
📊 P&L: Rs.{pnl:,.0f} ({pnl_pct:+.1f}%)
⏰ {datetime.now().strftime('%H:%M:%S')}"""

        send(msg)
        log.info(f'[EXIT] {inst} {reason} pnl={pnl:.0f}')

        # Record to trade log
        self._record_trade(pos,exit_prem,reason,pnl)

        # Record exit in Trade Journal
        try:
            from v31_trade_journal import trade_journal
            _tid=pos.get('trade_id','')
            if _tid:
                trade_journal.record_exit(_tid,exit_prem,reason)
            else:
                # Find by instrument+date
                from datetime import datetime
                _date=datetime.now().strftime('%Y-%m-%d')
                for t in reversed(trade_journal.trades):
                    if t['instrument']==inst and t['date']==_date and t['status']=='OPEN':
                        trade_journal.record_exit(t['id'],exit_prem,reason)
                        break
        except Exception as _je:
            log.debug(f'[JOURNAL] Exit error: {_je}')
        pos['status']='CLOSED'
        # Notify signal manager + update P&L
        try:
            from v31_signal_manager import signal_manager
            signal_manager.close_position(pos['instrument'])
            signal_manager.update_pnl(pnl)
        except:pass

        # Update capital engine performance
        try:
            from v31_capital_engine import capital_engine
            capital_engine.update(inst,pnl,pnl>0)
        except:pass

    def _partial_exit(self,sym,pos,exit_prem,pnl):
        """Handle T1 partial exit with trailing SL"""
        inst=pos['instrument']
        entry=pos['entry_prem']
        pos['partial_exit']=True
        pos['sl']=entry  # Breakeven!
        pos['trail_active']=True
        pos['trail_high']=exit_prem
        send(f'🎯 T1 Hit! {inst}\n'
             f'Partial P&L: Rs.{pnl:,.0f}\n'
             f'🛡️ SL→Breakeven Rs.{entry}\n'
             f'🔄 Trailing SL active!')
        self.save_positions()
        log.info(f'[EXIT] {inst} T1 hit - SL=breakeven Rs.{entry}')

    def _update_trailing_sl(self,sym,pos,current_prem):
        """Update trailing SL as price moves up"""
        if not pos.get('trail_active'):return
        inst=pos['instrument']
        entry=pos['entry_prem']
        current_sl=pos['sl']
        # Track highest price
        if current_prem>pos.get('trail_high',0):
            pos['trail_high']=current_prem
        high=pos.get('trail_high',current_prem)
        # Trail levels
        new_sl=current_sl
        if high>=entry*2.2:   new_sl=max(current_sl,round(entry*1.8))  # Lock +80%
        elif high>=entry*1.8: new_sl=max(current_sl,round(entry*1.4))  # Lock +40%
        elif high>=entry*1.5: new_sl=max(current_sl,entry)             # Breakeven
        if new_sl>current_sl:
            pos['sl']=new_sl
            self.save_positions()
            locked=round((new_sl-entry)/entry*100)
            log.info(f'[TRAIL] {inst} SL Rs.{current_sl}→Rs.{new_sl} locked={locked}%')
            send(f'📈 Trail SL Updated!\n{inst}\nNew SL: Rs.{new_sl}\nLocked: +{locked}%')

    def _is_time_exit(self,pos):
        """Check if time-based exit needed"""
        now=datetime.now()
        segment=pos.get('segment','NFO')

        # NSE options: exit by 3:15 PM
        if segment in ['NFO','BFO']:
            if now.hour==15 and now.minute>=15:
                return True
        # MCX options: exit by 11:15 PM
        elif segment=='MCX':
            if now.hour==23 and now.minute>=15:
                return True
        return False

    def _record_trade(self,pos,exit_prem,reason,pnl):
        """Record completed trade to log"""
        try:
            trade_log='trade_log.json'
            trades=[]
            if os.path.exists(trade_log):
                trades=json.load(open(trade_log))

            trades.append({
                'instrument':pos['instrument'],
                'symbol':pos['symbol'],
                'action':pos['action'],
                'entry_prem':pos['entry_prem'],
                'exit_prem':exit_prem,
                'qty':pos['qty'],
                'pnl':round(pnl,2),
                'result':'WIN' if pnl>0 else 'LOSS',
                'reason':reason,
                'entry_time':pos['entry_time'],
                'exit_time':datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            })

            json.dump(trades,open(trade_log,'w'))
            log.info(f'[EXIT] Trade recorded: {pos["instrument"]} pnl={pnl:.0f}')
        except Exception as e:
            log.error(f'[EXIT] Record error: {e}')

    def get_open_count(self):
        return sum(1 for p in self.positions.values() if p.get('status')=='OPEN')

    def get_summary(self):
        open_pos=[(s,p) for s,p in self.positions.items() if p.get('status')=='OPEN']
        return {
            'open':len(open_pos),
            'positions':[(p['instrument'],p['entry_prem']) for s,p in open_pos]
        }


# Global instance
exit_monitor=ExitMonitor()
