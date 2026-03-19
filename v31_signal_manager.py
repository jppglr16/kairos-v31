"""
V31 Signal Manager V2 - Production Grade
Session-based trade control with direction tracking
All critical fixes applied
"""
import logging,json,os
from datetime import datetime,time,timedelta
log=logging.getLogger(__name__)

# ============================================================
# SESSION DEFINITIONS
# ============================================================
NSE_SESSIONS=[
    {'name':'MORNING',  'start':time(9,30),  'end':time(13,0)},
    {'name':'AFTERNOON','start':time(13,30), 'end':time(15,0)},
]
MCX_SESSIONS=[
    {'name':'EVENING',  'start':time(15,30), 'end':time(18,0)},
    {'name':'NIGHT',    'start':time(18,0),  'end':time(23,0)},
]

MCX_INST=['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
INDEX_INST=['NIFTY','BANKNIFTY','FINNIFTY','MIDCPNIFTY','SENSEX']

# ✅ Fix 2: Clear direction mapping
SELL_TYPES=('SELL','SELL_CE','SELL_PE','STRADDLE','PE')
BUY_TYPES=('BUY','CE','CALL')

MAX_DAILY_TRADES=8       # Per instrument daily cap
COOLDOWN_SECS=300        # 5 min between trades
SELL_LOCK_TIMEOUT=1800   # 30 min sell lock auto-release

STATE_FILE='signal_manager_state.json'

# ============================================================
# SIGNAL MANAGER
# ============================================================
class SignalManager:
    def __init__(self):
        self.state={}          # {instrument:{session:{BUY:0,SELL:0}}}
        self.active_sells={}   # {instrument: strategy_type}
        self.sell_lock_time={} # {instrument: datetime}
        self.last_trade_time={}# {instrument: datetime} cooldown
        self.date=None
        self.load_state()

    def load_state(self):
        try:
            if os.path.exists(STATE_FILE):
                data=json.load(open(STATE_FILE))
                if data.get('date')==datetime.now().strftime('%Y-%m-%d'):
                    self.state=data.get('state',{})
                    self.active_sells=data.get('active_sells',{})
                    self.date=data['date']
                    log.info(f'[SM] Loaded state for {self.date}')
                    return
            self._reset()
        except:
            self._reset()

    def save_state(self):
        try:
            json.dump({
                'date':datetime.now().strftime('%Y-%m-%d'),
                'state':self.state,
                'active_sells':self.active_sells,
            },open(STATE_FILE,'w'))
        except:pass

    def _reset(self):
        self.state={}
        self.active_sells={}
        self.sell_lock_time={}
        self.last_trade_time={}
        self.date=datetime.now().strftime('%Y-%m-%d')
        self.save_state()

    def _get_session(self,instrument):
        """Get current session name"""
        now=datetime.now().time()
        sessions=MCX_SESSIONS if instrument in MCX_INST else NSE_SESSIONS
        for s in sessions:
            if s['start']<=now<s['end']:
                return s['name']
        return None

    def _get_limits(self,score):
        """✅ Fix 1: Score-based limits"""
        if score>=28:
            return {'BUY':2,'SELL':2}  # High score = 2 trades each
        elif score>=25:
            return {'BUY':2,'SELL':1}
        elif score>=20:
            return {'BUY':1,'SELL':1}
        else:
            return {'BUY':0,'SELL':0}  # Low score blocked!

    def _get_daily_total(self,instrument):
        """Get total trades today for instrument"""
        total=0
        for sess in self.state.get(instrument,{}).values():
            total+=sess.get('BUY',0)+sess.get('SELL',0)
        return total


    def _check_direction_bias(self,instrument,dir_key):
        """Check if direction flip detected (chop filter)"""
        opposite='BUY' if dir_key=='SELL' else 'SELL'
        inst_state=self.state.get(instrument,{})
        total_opposite=sum(s.get(opposite,0) for s in inst_state.values())
        total_same=sum(s.get(dir_key,0) for s in inst_state.values())
        if total_same>=1 and total_opposite>=1:
            log.info(f'[SM] {instrument} direction flip: {opposite}:{total_opposite} {dir_key}:{total_same}')
            return True
        return False

    def _auto_release_sell_lock(self,instrument):
        """✅ Fix 3: Auto-release sell lock after timeout"""
        if instrument in self.sell_lock_time:
            elapsed=(datetime.now()-self.sell_lock_time[instrument]).seconds
            if elapsed>SELL_LOCK_TIMEOUT:
                log.info(f'[SM] Auto-releasing sell lock for {instrument} after {elapsed}s')
                self.release_sell_lock(instrument)

    def can_trade(self,instrument,direction,score=18,strategy_type='DIRECT',atr=None):
        """
        7-step check in CORRECT order:
        1.Session 2.Cooldown 3.DailyCap 4.SellLock 5.DirFlip 6.Score 7.Limit
        """
        now=datetime.now()
        dir_key='SELL' if direction in SELL_TYPES else 'BUY'

        # 1. SESSION CHECK
        session=self._get_session(instrument)
        if not session:
            return False,f'Outside session ({instrument})'

        # 2. COOLDOWN CHECK
        if instrument in self.last_trade_time:
            elapsed=(now-self.last_trade_time[instrument]).seconds
            if elapsed<COOLDOWN_SECS:
                return False,f'Cooldown: {COOLDOWN_SECS-elapsed}s remaining'

        # 3. DAILY CAP
        if self._get_daily_total(instrument)>=MAX_DAILY_TRADES:
            return False,f'Daily cap reached ({self._get_daily_total(instrument)}/{MAX_DAILY_TRADES})'

        # 4. SELL LOCK
        self._auto_release_sell_lock(instrument)
        if dir_key=='SELL' and instrument in self.active_sells:
            active=self.active_sells[instrument]
            if active!=strategy_type:
                return False,f'Sell lock: {active} active'

        # 5. DIRECTION FLIP
        flip=self._check_direction_bias(instrument,dir_key)
        if flip and score<25:
            return False,f'Direction flip: need score>=25 (got {score})'

        # 6. SCORE FILTER
        if score>=28:
            limits={'BUY':3,'SELL':2}  # Boost (not bypass!)
            log.info(f'[SM] {instrument} HIGH SCORE BOOST ({score})')
        else:
            limits=self._get_limits(score)
        if limits[dir_key]==0:
            return False,f'Score {score} too low for {dir_key} (need>=20)'

        # 7. SESSION LIMIT
        inst_state=self.state.get(instrument,{})
        sess_state=inst_state.get(session,{'BUY':0,'SELL':0})
        current=sess_state.get(dir_key,0)
        max_allowed=limits[dir_key]
        if current>=max_allowed:
            return False,f'{dir_key} limit ({current}/{max_allowed}) in {session}'

        # ALLOW
        log.info(f'[SM] {instrument}|{session}|{dir_key}|{current+1}/{max_allowed}|Score:{score}')
        return True,f'Allowed ({current+1}/{max_allowed}) in {session}'

    def record_trade(self,instrument,direction,strategy_type='DIRECT'):
        """Record trade taken"""
        session=self._get_session(instrument)
        if not session:return

        if instrument not in self.state:
            self.state[instrument]={}
        if session not in self.state[instrument]:
            self.state[instrument][session]={'BUY':0,'SELL':0}

        dir_key='SELL' if direction in SELL_TYPES else 'BUY'
        self.state[instrument][session][dir_key]+=1

        # Lock sell strategy + record time
        if dir_key=='SELL':
            self.active_sells[instrument]=strategy_type
            self.sell_lock_time[instrument]=datetime.now()

        # ✅ Fix 5: Record for cooldown
        self.last_trade_time[instrument]=datetime.now()

        total=self._get_daily_total(instrument)
        log.info(f'[SM] Recorded {instrument} {dir_key} in {session} '
                f'(session:{self.state[instrument][session][dir_key]} daily:{total})')
        self.save_state()

    def release_sell_lock(self,instrument):
        """Release sell lock when position closed"""
        if instrument in self.active_sells:
            del self.active_sells[instrument]
        if instrument in self.sell_lock_time:
            del self.sell_lock_time[instrument]
        log.info(f'[SM] Released sell lock: {instrument}')
        self.save_state()

    def is_in_session(self,instrument):
        return self._get_session(instrument) is not None

    def get_status(self,instrument,direction='BUY'):
        session=self._get_session(instrument)
        if not session:return 'No session'
        dir_key='SELL' if direction in SELL_TYPES else 'BUY'
        sess_state=self.state.get(instrument,{}).get(session,{})
        daily=self._get_daily_total(instrument)
        return f'{sess_state.get(dir_key,0)}/2 in {session} | Daily:{daily}/{MAX_DAILY_TRADES}'

    def get_session_summary(self):
        return {
            'date':self.date,
            'state':self.state,
            'active_sells':list(self.active_sells.keys()),
            'daily_totals':{i:self._get_daily_total(i) for i in self.state}
        }

    def reset_day(self):
        self._reset()
        log.info('[SM] Day reset!')


# Global instance
signal_manager=SignalManager()
