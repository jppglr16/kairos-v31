"""
V31 India VIX Engine
Filters trades based on volatility regime
VIX 14-20 = Best zone for options buying
"""
import logging,time,json
import urllib.request,http.cookiejar
log=logging.getLogger(__name__)

# VIX Configuration - adjust here!
VIX_CONFIG={
    "SPIKE_PCT":    0.10,
    "TREND_THRESH": 0.5,
    "SWEET_LOW":    14,
    "SWEET_HIGH":   20,
    "DANGER":       25,
    "QUALITY":      40,
}
VIX_DANGER=VIX_CONFIG["DANGER"]
QUALITY_THRESHOLD=VIX_CONFIG["QUALITY"]


class VIXEngine:
    def __init__(self):
        self._vix=None
        self._last_fetch=0
        self._session=None
        self.CACHE_TTL=120  # 2 mins (VIX can spike fast!)

    def _create_session(self):
        try:
            cj=http.cookiejar.CookieJar()
            opener=urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
            opener.addheaders=[
                ('User-Agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64)'),
                ('Accept','application/json,*/*'),
                ('Accept-Language','en-US,en;q=0.9'),
                ('Referer','https://www.nseindia.com/')
            ]
            opener.open('https://www.nseindia.com',timeout=10)
            time.sleep(1)
            self._session=opener
            return True
        except Exception as e:
            log.debug(f'[VIX] Session error: {e}')
            return False

    def _load_prev_vix(self):
        """Load previous VIX from file"""
        try:
            import json,os
            if os.path.exists('vix_state.json'):
                d=json.load(open('vix_state.json'))
                self._prev_vix=d.get('prev_vix')
        except:pass

    def _save_prev_vix(self,vix):
        """Save VIX to file - safe write"""
        try:
            import json
            with open('vix_state.json','w') as f:
                json.dump({'prev_vix':vix},f)
        except:pass

    def get_vix(self):
        """Get India VIX value"""
        if not hasattr(self,'_loaded'):
            self._load_prev_vix()
            self._loaded=True
        now=time.time()
        # Return cached value
        if self._vix and now-self._last_fetch<self.CACHE_TTL:
            return self._vix

        # Create session
        if not self._session:
            if not self._create_session():
                return None

        for attempt in range(3):
            try:
                resp=self._session.open(
                    'https://www.nseindia.com/api/allIndices',
                    timeout=10)
                data=json.loads(resp.read().decode())
                if 'data' not in data:
                    raise ValueError('Invalid NSE response')
                vix=next((i for i in data.get('data',[])
                          if 'VIX' in i.get('index','')),None)
                if vix:
                    val=float(vix.get('last',0))
                    self._vix=val
                    self._last_fetch=time.time()
                    self._save_prev_vix(val)  # Fix 5: persist!
                    log.info(f'[VIX] India VIX={val:.2f}')
                    return val
            except Exception as e:
                log.debug(f'[VIX] Attempt {attempt+1}: {e}')
                self._session=None
                if attempt<2:
                    self._create_session()
                    time.sleep(2)
        return None

    def get_regime(self):
        """
        VIX regime classification:
        < 12  = Very low vol (bad for buying)
        12-14 = Low vol (careful)
        14-20 = SWEET SPOT! (best for buying) ✅
        20-25 = High vol (risky but ok)
        > 25  = Extreme (avoid!)
        """
        vix=self.get_vix()
        if vix is None:
            return 'UNKNOWN',0

        if vix<12:  # Below sweet spot
            return 'TOO_LOW',-1
        elif vix<14:
            return 'LOW',0
        elif vix<=VIX_CONFIG["SWEET_HIGH"]:
            return 'SWEET_SPOT',2  # Best!
        elif vix<=VIX_CONFIG["DANGER"]:
            return 'HIGH',-1
        else:
            return 'EXTREME',-3

    def get_trend(self):
        """Get VIX trend"""
        return getattr(self,'_vix_trend','STABLE')

    def get_vix_value(self):
        """Clean getter for VIX value"""
        return self._vix

    def score_signal(self,action='BUY'):
        """Score boost based on VIX + trend"""
        regime,boost=self.get_regime()
        vix=self._vix
        if vix is None:
            return 0,'UNKNOWN',None

        # Add trend boost
        trend=self.get_trend()
        if 'SPIKE_DOWN' in str(regime):
            boost-=2  # Fix 4: IV crush override!
            log.info('[VIX] SPIKE_DOWN: trend optimism overridden!')
        elif trend=='RISING':boost-=1
        elif trend=='FALLING':boost+=1

        log.info(f'[VIX] {vix:.1f} regime={regime} trend={trend} boost={boost:+d}')
        return boost,regime,vix

    def should_trade(self):
        """
        Hard filter:
        VIX > 25 = STOP all trading!
        VIX < 12 = Warn (low premium)
        """
        vix=self.get_vix()
        if vix is None:return True,'Unknown VIX - allow'
        if vix>VIX_CONFIG["DANGER"]:
            return False,f'VIX too high ({vix:.1f}) - dangerous for buying!'
        if vix<10:
            return True,f'VIX low ({vix:.1f}) - avoid buying only'
        return True,f'VIX={vix:.1f} OK'

    def get_strategy_mode(self):
        """
        Strategy Switching Engine based on VIX
        Returns recommended trading mode
        """
        vix=self.get_vix()
        regime,_=self.get_regime()

        if vix is None:return 'NORMAL'
        if 'SPIKE' in str(regime):return 'NO_TRADE'
        if vix<12:return 'SELL_PREMIUM'
        if vix<20:return 'TREND_BUY'    # Best!
        if vix<25:return 'SCALP'
        return 'DEFENSIVE'

# Global instance
vix_engine=VIXEngine()
