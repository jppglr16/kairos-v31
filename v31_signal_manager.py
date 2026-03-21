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

        # Position state manager
        self.positions={}      # {instrument: {side,entry_price,status}}
        self.last_exit_time={} # {instrument: datetime} post-exit cooldown

        # Portfolio Risk Engine
        self.daily_loss=0
        self.max_daily_loss=-7000   # Rs.3000 max daily loss
        self.max_trades_per_day=8
        self.trade_count=0
        self.trading_enabled=True
        self.kill_switch=False

        # AI Trade Manager stats
        self.stats={'wins':0,'losses':0}

        self.load_state()

    # ============================================================
    # POSITION STATE MANAGER
    # ============================================================
    def has_active_position(self,inst):
        """Check if instrument has open position"""
        return inst in self.positions and self.positions[inst].get('status')=='OPEN'

    def get_position_side(self,inst):
        """Get current position side (CE/PE/BUY/SELL)"""
        if self.has_active_position(inst):
            return self.positions[inst].get('side')
        return None

    def open_position(self,inst,side,price):
        """Record new position"""
        self.positions[inst]={
            'side':side,
            'entry_price':price,
            'status':'OPEN',
            'open_time':datetime.now().isoformat()
        }
        log.info(f'[SM] Position opened: {inst} {side} @ Rs.{price}')

    def close_position(self,inst):
        """Close position and start cooldown"""
        if inst in self.positions:
            self.positions[inst]['status']='CLOSED'
            self.last_exit_time[inst]=datetime.now()
            log.info(f'[SM] Position closed: {inst}')

    def cooldown_active(self,inst,secs=300):
        """Check if post-exit cooldown active (5 mins)"""
        if inst not in self.last_exit_time:return False
        elapsed=(datetime.now()-self.last_exit_time[inst]).seconds
        return elapsed<secs

    def _is_opposite_side(self,current_side,new_direction):
        """Check if new signal opposes current position"""
        buy_types=('BUY','CE','CALL')
        sell_types=('SELL','PE','PUT')
        current_is_buy=current_side in buy_types or 'CE' in str(current_side)
        new_is_buy=new_direction in buy_types
        return current_is_buy != new_is_buy

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

    # ============================================================
    # PORTFOLIO RISK ENGINE
    # ============================================================
    def win_rate(self):
        """Calculate current win rate"""
        total=self.stats['wins']+self.stats['losses']
        if total==0:return 0.5
        return self.stats['wins']/total

    def get_adaptive_flip_score(self):
        """Adjust flip threshold based on performance"""
        wr=self.win_rate()
        if wr<0.40:  return 32  # Losing → very strict
        elif wr>0.60:return 27  # Winning → aggressive
        else:        return 29  # Normal

    def get_lot_size(self,score):
        """Dynamic lot sizing based on signal score"""
        if score>=30: return 2  # High confidence = 2 lots
        elif score>=25:return 1  # Normal = 1 lot
        else:          return 0  # Skip weak signals

    def update_pnl(self,pnl):
        """Update daily P&L and stats"""
        self.daily_loss+=pnl
        if pnl>0:
            self.stats['wins']+=1
        else:
            self.stats['losses']+=1
        log.info(f'[RM] Daily P&L: Rs.{self.daily_loss:,.0f} '
                f'WR={self.win_rate():.0%} '
                f'W:{self.stats["wins"]} L:{self.stats["losses"]}')
        # Alert if near limit
        if self.daily_loss<=self.max_daily_loss*0.7:
            try:
                from v31_notify import send
                send(f'⚠️ Risk Alert! Daily loss: Rs.{self.daily_loss:,.0f} / Limit: Rs.{self.max_daily_loss:,.0f}')



            except:pass

    def reset_daily(self):
        """Reset daily counters at market open"""
        self.daily_loss=0
        self.trade_count=0
        self.trading_enabled=True
        self.stats={'wins':0,'losses':0}
        log.info('[RM] Daily reset! Trading enabled.')

    def dynamic_hold_time(self,instrument,atr=None):
        """Dynamic hold time based on volatility"""
        try:
            if atr is None:return 1800
            if atr>2:  return 1200  # 20 min (high volatility)
            elif atr>1:return 1800  # 30 min (normal)
            else:      return 2400  # 40 min (slow market)
        except:return 1800

    def flip_score(self,instrument,direction,signal=None,score=0):
        """
        5-factor flip scoring system
        Uses existing signal data - no extra API calls!
        Returns: (allowed, flip_score, reason)
        """
        if signal is None:
            return False,0,'No signal data'

        fs=0
        reasons=[]

        # 1. Signal score quality (max 2pts)
        if score>=29:
            fs+=2; reasons.append(f'score={score}✅')
        elif score>=27:
            fs+=1; reasons.append(f'score={score}⚠️')
        else:
            reasons.append(f'score={score}❌')

        # 2. SL type quality (max 2pts)
        sl_type=signal.get('sl_type','')
        if 'FVG' in sl_type:
            fs+=2; reasons.append('FVG✅')
        elif 'OB' in sl_type:
            fs+=1; reasons.append('OB⚠️')
        else:
            reasons.append(f'{sl_type}❌')

        # 3. Trend aligned (1pt)
        if signal.get('trend_aligned',False):
            fs+=1; reasons.append('trend✅')
        else:
            reasons.append('trend❌')

        # 4. Market regime (max 2pts, min -1pt)
        regime=signal.get('regime','RANGING')
        if 'TRENDING' in regime:
            fs+=2; reasons.append(f'{regime}✅')
        elif 'RANGING' in regime:
            fs-=1; reasons.append(f'{regime}❌')
        else:
            fs+=1; reasons.append(f'{regime}⚠️')

        # 5. Liquidity sweep (1pt)
        liq=signal.get('liq_type','')
        if 'SWEEP' in liq:
            fs+=1; reasons.append('SWEEP✅')
        elif 'EQUAL' in liq:
            fs+=0; reasons.append('EQUAL⚠️')

        # Bonus: Gamma boost
        if signal.get('gamma_boost',0)>0:
            fs+=1; reasons.append('GAMMA✅')

        allowed=fs>=5
        reason=f'FlipScore:{fs}/8 [{",".join(reasons)}]'
        log.info(f'[SM] {instrument} flip check: {reason}')
        return allowed,fs,reason

    # Keep for backward compatibility
    def volume_spike(self,instrument,signal=None):
        return signal is not None

    def market_regime_ok(self,instrument,signal=None):
        if signal is None:return False
        return signal.get('regime','RANGING') not in ('RANGING','CHOPPY')

    def mtf_aligned(self,instrument,direction,signal=None):
        if signal is None:return False
        return signal.get('trend_aligned',False)

    def can_trade(self,instrument,direction,score=18,strategy_type='DIRECT',atr=None,signal=None):
        """
        7-step check in CORRECT order:
        1.Session 2.Cooldown 3.DailyCap 4.SellLock 5.DirFlip 6.Score 7.Limit
        """
        now=datetime.now()
        dir_key='SELL' if direction in SELL_TYPES else 'BUY'

        # 0. KILL SWITCH
        if self.kill_switch:
            return False,'System paused (kill switch active)'

        # 0a. DAILY LOSS LIMIT
        if self.daily_loss<=self.max_daily_loss:
            self.trading_enabled=False
            try:
                from v31_notify import send
                send(f'🚨 Daily loss limit hit!\n'
                     f'Loss: Rs.{self.daily_loss:,.0f}\n'
                     f'Trading STOPPED for today!')
            except:pass
            return False,f'Daily loss limit hit (Rs.{self.daily_loss:,.0f})'

        # 0b. TRADING ENABLED CHECK
        if not self.trading_enabled:
            return False,'Trading disabled'

        # 0c. TRADE COUNT LIMIT
        if self.trade_count>=self.max_trades_per_day:
            return False,f'Max trades reached ({self.trade_count}/{self.max_trades_per_day})'

        # 0. POST-EXIT COOLDOWN
        if self.cooldown_active(instrument):
            return False,f'Post-exit cooldown active (5 mins)'

        # 0b. POSITION CONFLICT CHECK
        if self.has_active_position(instrument):
            current_side=self.get_position_side(instrument)
            is_opposite=self._is_opposite_side(current_side,dir_key)
            if is_opposite:
                if score>=27:
                    # High score flip - close old position first
                    log.info(f'[SM] {instrument} FLIP allowed (score={score}) closing {current_side}')
                    self.close_position(instrument)
                else:
                    return False,f'Position conflict: {current_side} active, need score>=27 to flip (got {score})'
            else:
                # Same direction - check session limit normally
                pass

        # 1. SESSION CHECK
        session=self._get_session(instrument)
        if not session:
            return False,f'Outside session ({instrument})'

        # 2. COOLDOWN CHECK (trade cooldown)
        if instrument in self.last_trade_time:
            elapsed=(now-self.last_trade_time[instrument]).seconds
            if elapsed<COOLDOWN_SECS:
                return False,f'Cooldown: {COOLDOWN_SECS-elapsed}s remaining'

        # 2b. POST-EXIT COOLDOWN (after early exit/loss protection)
        if instrument in self.last_exit_time:
            _exit_elapsed=(now-self.last_exit_time[instrument]).seconds
            _exit_cooldown=300  # 5 mins after early exit
            if _exit_elapsed<_exit_cooldown:
                _remaining=_exit_cooldown-_exit_elapsed
                return False,f'Post-exit cooldown: {_remaining}s remaining'

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

        # Increment trade count
        self.trade_count+=1
        log.info(f'[RM] Trade count: {self.trade_count}/{self.max_trades_per_day}')

        # Open position tracker
        self.open_position(instrument,dir_key,0)  # price updated by exit monitor

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
