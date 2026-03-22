"""
V31 Signal Tracker
Shows every step of signal evaluation
Helps understand why trade taken/rejected
"""
import logging
from datetime import datetime
log=logging.getLogger(__name__)

class SignalTracker:
    def __init__(self):
        self.current={}

    def start(self,instrument,action,price,score):
        """Start tracking a new signal"""
        self.current={
            'instrument':instrument,
            'action':action,
            'price':price,
            'initial_score':score,
            'score':score,
            'steps':[],
            'time':datetime.now().strftime('%H:%M:%S'),
            'result':'PENDING'
        }
        self._log(f'🔍 NEW SIGNAL: {instrument} {action} @ Rs.{price:.0f} Score:{score}')

    def step(self,name,result,detail='',score_change=0):
        """Record a step"""
        if not self.current:return
        status='✅' if result else '❌'
        self.current['steps'].append({
            'name':name,
            'result':result,
            'detail':detail,
            'score_change':score_change
        })
        if score_change!=0:
            self.current['score']+=score_change
        self._log(f'  {status} {name}: {detail} {f"({score_change:+d})" if score_change else ""}')

    def approve(self,lots,final_score):
        """Signal approved for trading"""
        if not self.current:return
        self.current['result']='APPROVED'
        self.current['lots']=lots
        self.current['final_score']=final_score
        self._send_summary('✅ APPROVED')

    def reject(self,reason):
        """Signal rejected"""
        if not self.current:return
        self.current['result']='REJECTED'
        self.current['reject_reason']=reason
        self._send_summary('❌ REJECTED')

    def _log(self,msg):
        log.info(f'[TRACKER] {msg}')

    def _send_summary(self,verdict):
        """Send step-by-step summary to Telegram"""
        try:
            from v31_notify import send
            c=self.current
            lines=[
                f'📊 Signal Report: {c["instrument"]}',
                f'━━━━━━━━━━━━━━━',
                f'⏰ {c["time"]} | {c["action"]} @ Rs.{c["price"]:.0f}',
                f'📈 Score: {c["initial_score"]} → {c["score"]}',
                f'',
                f'Steps:',
            ]
            for s in c['steps']:
                icon='✅' if s['result'] else '❌'
                change=f' ({s["score_change"]:+d})' if s['score_change'] else ''
                lines.append(f'{icon} {s["name"]}: {s["detail"]}{change}')
            lines.append('')
            lines.append(f'{"🚀 "+verdict+" | Lots:"+str(c.get("lots",0)) if "APPROVED" in verdict else "🚫 "+verdict}')
            lines.append(f'Reason: {c.get("reject_reason","")}')
            send('\n'.join(lines))
        except Exception as e:
            log.debug(f'[TRACKER] Send error: {e}')
        finally:
            self.current={}

# Global instance
signal_tracker=SignalTracker()
