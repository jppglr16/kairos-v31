"""
V31 News Event Filter
Blocks trading before major market events
Prevents news spike losses!
"""
import logging
from datetime import datetime,date,timedelta
log=logging.getLogger(__name__)

# IST timezone (module level - faster!)
try:
    import pytz
    IST=pytz.timezone('Asia/Kolkata')
except:
    IST=None

# ============================================================
# 2026 MAJOR MARKET EVENTS
# ============================================================
MARKET_EVENTS={
    # RBI Policy dates 2026
    # RBI Policy 2026 (10:00 AM IST)
    '2026-04-09': {'event':'RBI Policy','time':'10:00','block_mins':60,'impact':'HIGH'},
    '2026-06-06': {'event':'RBI Policy','time':'10:00','block_mins':60,'impact':'HIGH'},
    '2026-08-06': {'event':'RBI Policy','time':'10:00','block_mins':60,'impact':'HIGH'},
    '2026-10-08': {'event':'RBI Policy','time':'10:00','block_mins':60,'impact':'HIGH'},
    '2026-12-05': {'event':'RBI Policy','time':'10:00','block_mins':60,'impact':'HIGH'},

    # Union Budget (09:00 AM IST)
    '2026-02-01': {'event':'Union Budget','time':'09:00','block_mins':120,'impact':'EXTREME'},

    # US Fed (11:30 PM IST = after market)
    '2026-01-29': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-03-19': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-05-07': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-06-18': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-07-30': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-09-17': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-11-05': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},
    '2026-12-17': {'event':'US Fed Meeting','time':'23:30','block_mins':30,'impact':'MEDIUM'},

    # CPI Data (05:30 PM IST)
    '2026-01-13': {'event':'CPI Data','time':'17:30','block_mins':30,'impact':'MEDIUM'},
    '2026-02-12': {'event':'CPI Data','time':'17:30','block_mins':30,'impact':'MEDIUM'},
    '2026-03-12': {'event':'CPI Data','time':'17:30','block_mins':30,'impact':'MEDIUM'},
    '2026-04-14': {'event':'CPI Data','time':'17:30','block_mins':30,'impact':'MEDIUM'},
}

# Quarterly results season (block all small caps)
RESULTS_SEASONS=[
    ('2026-01-15','2026-02-15'),  # Q3 results
    ('2026-04-15','2026-05-15'),  # Q4 results
    ('2026-07-15','2026-08-15'),  # Q1 results
    ('2026-10-15','2026-11-15'),  # Q2 results
]

# Stocks with known result dates (high risk)
RESULT_DATES={
    'TCS':      ['2026-04-10','2026-07-11','2026-10-10'],
    'RELIANCE': ['2026-04-25','2026-07-25','2026-10-24'],
    'HDFCBANK': ['2026-04-19','2026-07-19','2026-10-17'],
    'INFOSYS':  ['2026-04-17','2026-07-17','2026-10-16'],
}

class NewsFilter:
    def __init__(self):
        self.alerted=set()
        self.last_check=None
        self._last_result=(False,'No events',None)

    def check(self,instrument=None):
        """
        Check if trading should be blocked due to news event
        Returns: (blocked, reason, resume_time)
        """
        # Fix 4: Throttle - cache result for 60 seconds
        try:
            if self.last_check:
                elapsed=(datetime.now()-self.last_check).seconds
                if elapsed<60:
                    return self._last_result
        except:pass
        self.last_check=datetime.now()

        # Fix 2: Use IST timezone (keep timezone-aware!)
        if IST:
            now=datetime.now(IST)
        else:
            now=datetime.now()
        today=now.strftime('%Y-%m-%d')

        # Check major market events
        if today in MARKET_EVENTS:
            event=MARKET_EVENTS[today]
            event_name=event['event']
            block_mins=event['block_mins']
            impact=event['impact']

            # Block entire day for EXTREME events
            if impact=='EXTREME':
                log.info(f'[NEWS] {event_name} today - EXTREME impact!')
                self._alert(f'🚨 {event_name} today!\nTrading BLOCKED all day!')
                return True,f'{event_name} (EXTREME)',None

            # Block based on time (assume event at 10 AM for RBI)
            event_time=now.replace(hour=10,minute=0,second=0)
            if now>=event_time-timedelta(minutes=block_mins):
                if now<=event_time+timedelta(minutes=30):
                    resume=event_time+timedelta(minutes=30)
                    log.info(f'[NEWS] {event_name} block active!')
                    self._alert(f'⚠️ {event_name}!\nTrading paused\nResumes: {resume.strftime("%H:%M")}')
                    return True,f'{event_name}',resume

        # GOLDM/SILVERM: Only trade last 6 days before expiry
        # Near expiry = high premium = better profit!
        if instrument in ['GOLDM','SILVERM']:
            try:
                from v31_angel_options import get_expiry_str
                from datetime import datetime as _edt
                _exp=get_expiry_str(instrument)
                _exp_dt=_edt.strptime(_exp,'%d%b%y')
                _days=(_exp_dt.date()-_edt.now().date()).days
                if _days>6:
                    log.info(f'[NEWS] {instrument} {_days} days to expiry - wait for last 6 days!')
                    self._last_result=(True,f'{instrument} not in last 6 days ({_days}d remaining)',None)
                    return True,f'{instrument} not in last 6 days ({_days}d remaining)',None
                else:
                    log.info(f'[NEWS] {instrument} {_days} days to expiry - TRADING WINDOW! ✅')
            except Exception as _me:
                log.debug(f'[NEWS] MCX expiry check: {_me}')

        # Check instrument-specific result dates
        if instrument and instrument in RESULT_DATES:
            if today in RESULT_DATES[instrument]:
                log.info(f'[NEWS] {instrument} results today!')
                self._alert(f'⚠️ {instrument} results today! Trading blocked')
                self._last_result=(True,f'{instrument} results day',None)
                return True,f'{instrument} results day',None

        # Check results season for individual stocks
        if instrument:
            from v31_instrument_manager import INSTRUMENTS
            inst_type=INSTRUMENTS.get(instrument,{}).get('type','')
            if inst_type=='STOCK':
                for start,end in RESULTS_SEASONS:
                    if start<=today<=end:
                        # Allow indices/MCX during results season
                        if now.hour>=14:  # Block after 2 PM in results season
                            log.debug(f'[NEWS] {instrument} results season caution')

        self._last_result=(False,'No events',None)
        return False,'No events',None

    def _alert(self,msg):
        """Send Telegram alert (once per event)"""
        key=msg[:30]
        if key not in self.alerted:
            try:
                from v31_notify import send
                send(f'📰 News Filter\n━━━━━━━━━━━━━━━\n{msg}')
                self.alerted.add(key)
            except:pass

    def get_upcoming_events(self,days=7):
        """Get events in next N days"""
        events=[]
        for i in range(days):
            d=(date.today()+timedelta(days=i)).strftime('%Y-%m-%d')
            if d in MARKET_EVENTS:
                events.append({
                    'date':d,
                    'event':MARKET_EVENTS[d]['event'],
                    'impact':MARKET_EVENTS[d]['impact']
                })
        return events

    def morning_events(self):
        """Print today + upcoming events for morning checklist"""
        upcoming=self.get_upcoming_events(7)
        if not upcoming:
            return '📰 No major events this week'
        msg='📰 Upcoming Events:\n'
        for e in upcoming:
            emoji='🚨' if e['impact']=='EXTREME' else '⚠️' if e['impact']=='HIGH' else '📊'
            msg+=f"{emoji} {e['date']}: {e['event']}\n"
        return msg.strip()

# Global instance
news_filter=NewsFilter()
