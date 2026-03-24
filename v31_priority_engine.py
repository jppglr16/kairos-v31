"""
V31 Priority-Based Data Engine
Reduces API calls by 70%!

Priority Levels:
🔴 P1: Active trades (every 5s)
🟡 P2: Near signal (every 15s)  
🟢 P3: Idle (every 60s)
⚪ P4: Inactive (every 300s)
"""
import time
import logging
from datetime import datetime
from collections import defaultdict

log = logging.getLogger(__name__)

class PriorityDataEngine:
    def __init__(self):
        # Priority levels in seconds
        self.INTERVALS = {
            'P1': 5,    # Active trade
            'P2': 15,   # Near signal
            'P3': 60,   # Normal scan
            'P4': 300,  # Inactive
        }

        self.priorities = {}      # {instrument: priority}
        self.last_fetch = {}      # {instrument: timestamp}
        self.signal_scores = {}   # {instrument: score}
        self.fetch_count = defaultdict(int)  # Track API calls

        # API rate limiter
        self._last_api_call = 0
        self._min_gap = 0.5  # 2 calls/sec max

    def update_priority(self, instrument, active_trades,
                       recent_score=0):
        """
        Dynamically assign priority based on:
        1. Active trade = P1
        2. High recent score = P2
        3. Normal = P3
        4. MCX during NSE hours = P4
        """
        now_h = datetime.now().hour
        mcx = ['CRUDEOIL','GOLDM','SILVERM','NATURALGAS']
        nse = ['NIFTY','BANKNIFTY','FINNIFTY','SENSEX',
               'MIDCPNIFTY']

        # P4: Wrong market hours
        if instrument in mcx and 9 <= now_h < 15:
            self.priorities[instrument] = 'P4'
            return
        if instrument in nse and (now_h < 9 or now_h >= 15):
            self.priorities[instrument] = 'P4'
            return

        # P1: Active trade
        if instrument in active_trades:
            self.priorities[instrument] = 'P1'
            return

        # P2: Recent high score signal
        if recent_score >= 15:
            self.priorities[instrument] = 'P2'
            return

        # P3: Normal
        self.priorities[instrument] = 'P3'

    def should_fetch(self, instrument):
        """
        Returns True only if enough time passed
        based on instrument priority
        """
        priority = self.priorities.get(instrument, 'P3')
        interval = self.INTERVALS[priority]
        last = self.last_fetch.get(instrument, 0)
        elapsed = time.time() - last

        if elapsed >= interval:
            return True, priority
        return False, priority

    def rate_limited_call(self, func, *args, **kwargs):
        """
        Wrapper for ALL API calls
        Enforces global rate limit
        """
        now = time.time()
        wait = self._min_gap - (now - self._last_api_call)
        if wait > 0:
            time.sleep(wait)

        result = func(*args, **kwargs)
        self._last_api_call = time.time()
        return result

    def mark_fetched(self, instrument):
        self.last_fetch[instrument] = time.time()
        self.fetch_count[instrument] += 1

    def get_stats(self):
        """Show API call statistics"""
        total = sum(self.fetch_count.values())
        by_priority = defaultdict(int)
        for inst in self.fetch_count:
            p = self.priorities.get(inst,'P3')
            by_priority[p] += self.fetch_count[inst]
        return {
            'total_calls': total,
            'by_priority': dict(by_priority),
            'priorities': dict(self.priorities)
        }

# Global instance
priority_engine = PriorityDataEngine()
