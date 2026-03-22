"""
V31 India VIX Engine
Filters trades based on volatility regime
VIX 14-20 = Best zone for options buying
"""
import logging,time,json
import urllib.request,http.cookiejar
log=logging.getLogger(__name__)

class VIXEngine:
    def __init__(self):
        self._vix=None
        self._last_fetch=0
        self._session=None
        self.CACHE_TTL=300  # 5 mins

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

    def get_vix(self):
        """Get India VIX value"""
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
                vix=next((i for i in data.get('data',[])
                          if 'VIX' in i.get('index','')),None)
                if vix:
                    val=float(vix.get('last',0))
                    self._vix=val
                    self._last_fetch=now
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

        if vix<12:
            return 'TOO_LOW',-2
        elif vix<14:
            return 'LOW',-1
        elif vix<=20:
            return 'SWEET_SPOT',2  # Best!
        elif vix<=25:
            return 'HIGH',0
        else:
            return 'EXTREME',-3

    def score_signal(self,action='BUY'):
        """Score boost based on VIX"""
        regime,boost=self.get_regime()
        vix=self._vix or 0
        log.info(f'[VIX] {vix:.1f} regime={regime} boost={boost:+d}')
        return boost,regime,vix

    def should_trade(self):
        """
        Hard filter:
        VIX > 25 = STOP all trading!
        VIX < 12 = Warn (low premium)
        """
        vix=self.get_vix()
        if vix is None:return True,'Unknown VIX - allow'
        if vix>25:
            return False,f'VIX too high ({vix:.1f}) - extreme volatility!'
        if vix<10:
            return False,f'VIX too low ({vix:.1f}) - premiums worthless!'
        return True,f'VIX={vix:.1f} OK'

# Global instance
vix_engine=VIXEngine()
