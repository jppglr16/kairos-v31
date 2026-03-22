"""
V31 OI & PCR Engine
Fetches NSE option chain data
Provides PCR + OI levels for signal filtering
"""
import json,time,logging
import urllib.request,http.cookiejar
from datetime import datetime

log=logging.getLogger(__name__)

class OIPCREngine:
    def __init__(self):
        self._cache={}
        self._cache_time={}
        self._session=None
        self._last_fetch=0
        self.CACHE_TTL=180  # 3 mins

    def _create_session(self):
        """Create NSE session with cookies"""
        try:
            cj=http.cookiejar.CookieJar()
            opener=urllib.request.build_opener(
                urllib.request.HTTPCookieProcessor(cj))
            opener.addheaders=[
                ('User-Agent','Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'),
                ('Accept','text/html,application/json,*/*'),
                ('Accept-Language','en-US,en;q=0.9'),
                ('Referer','https://www.nseindia.com'),
            ]
            # Hit homepage to get cookies
            opener.open('https://www.nseindia.com',timeout=5)
            time.sleep(1)
            self._session=opener
            log.info('[OI] NSE session created ✅')
            return True
        except Exception as e:
            log.warning(f'[OI] Session error: {e}')
            return False

    def fetch_angel_oi(self,symbol='NIFTY'):
        """Fetch OI data from Angel One directly"""
        try:
            from v31_angel_trader import angel_trader
            import json
            if not angel_trader.connected:
                return {}

            # Try getOIData
            r=angel_trader.obj.getOIData(symbol)
            if isinstance(r,str):
                try:r=json.loads(r)
                except:return {}
            if isinstance(r,dict) and r.get('data'):
                log.info(f'[OI] {symbol} Angel OI data received ✅')
                return r

            # Try oIBuildup
            r=angel_trader.obj.oIBuildup(symbol)
            if isinstance(r,str):
                try:r=json.loads(r)
                except:return {}
            if isinstance(r,dict) and r.get('data'):
                return r
        except Exception as e:
            log.debug(f'[OI] Angel OI error: {e}')
        return {}

    def fetch_option_chain(self,symbol='NIFTY',is_stock=False):
        """Fetch option chain - try Angel first, then NSE"""
        # Check cache
        now=time.time()
        if symbol in self._cache:
            if now-self._cache_time.get(symbol,0)<self.CACHE_TTL:
                return self._cache[symbol]

        # Try Angel One first (more reliable!)
        angel_data=self.fetch_angel_oi(symbol)
        if angel_data:
            self._cache[symbol]=angel_data
            self._cache_time[symbol]=now
            return angel_data

        log.debug(f'[OI] Angel failed, trying NSE...')
        # Check cache
        now=time.time()
        if symbol in self._cache:
            if now-self._cache_time.get(symbol,0)<self.CACHE_TTL:
                return self._cache[symbol]

        # Rate limit
        if now-self._last_fetch<30:
            return self._cache.get(symbol,{})

        # Create session if needed
        if not self._session:
            if not self._create_session():
                return {}

        # Fetch option chain
        for attempt in range(3):
            try:
                if is_stock:
                    url=f'https://www.nseindia.com/api/option-chain-equities?symbol={symbol}'
                else:
                    url=f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol}'

                resp=self._session.open(url,timeout=5)
                data=json.loads(resp.read())
                self._cache[symbol]=data
                self._cache_time[symbol]=now
                self._last_fetch=now
                log.info(f'[OI] {symbol} option chain fetched ✅')
                return data
            except Exception as e:
                log.warning(f'[OI] Fetch attempt {attempt+1} failed: {e}')
                if attempt<2:
                    time.sleep(2*(attempt+1))
                    self._session=None  # Reset session
                    self._create_session()

        return {}

    def get_pcr(self,symbol='NIFTY'):
        """
        Get PCR for symbol
        Returns: (total_pcr, atm_pcr, signal)
        """
        try:
            data=self.fetch_option_chain(symbol)
            if not data:return 1.0,1.0,'NEUTRAL'

            # Total PCR
            filtered=data.get('filtered',{})
            ce_oi=filtered.get('CE',{}).get('totOI',1)
            pe_oi=filtered.get('PE',{}).get('totOI',0)
            total_pcr=pe_oi/max(ce_oi,1)

            # ATM PCR (more accurate!)
            spot=data.get('records',{}).get('underlyingValue',0)
            atm_strike=round(spot/50)*50 if spot>0 else 0
            atm_pcr=total_pcr  # Default

            if atm_strike>0:
                for item in data.get('records',{}).get('data',[]):
                    if item.get('strikePrice')==atm_strike:
                        ce=item.get('CE',{}).get('openInterest',1)
                        pe=item.get('PE',{}).get('openInterest',0)
                        atm_pcr=pe/max(ce,1)
                        break

            # Signal
            if atm_pcr>1.2:signal='BULLISH'
            elif atm_pcr<0.8:signal='BEARISH'
            else:signal='NEUTRAL'

            log.info(f'[OI] {symbol} PCR={total_pcr:.2f} ATM={atm_pcr:.2f} {signal}')
            return total_pcr,atm_pcr,signal
        except Exception as e:
            log.debug(f'[OI] PCR error: {e}')
            return 1.0,1.0,'NEUTRAL'

    def get_max_pain(self,symbol='NIFTY'):
        """Calculate max pain strike"""
        try:
            data=self.fetch_option_chain(symbol)
            if not data:return 0

            strikes={}
            for item in data.get('records',{}).get('data',[]):
                strike=item.get('strikePrice',0)
                ce_oi=item.get('CE',{}).get('openInterest',0)
                pe_oi=item.get('PE',{}).get('openInterest',0)
                strikes[strike]={'ce':ce_oi,'pe':pe_oi}

            if not strikes:return 0

            # Max pain = strike where total loss is minimized
            min_loss=float('inf')
            max_pain=0
            for test_price in strikes:
                total_loss=0
                for strike,(oi) in strikes.items():
                    # CE loss
                    if test_price>strike:
                        total_loss+=oi['ce']*(test_price-strike)
                    # PE loss
                    if test_price<strike:
                        total_loss+=oi['pe']*(strike-test_price)
                if total_loss<min_loss:
                    min_loss=total_loss
                    max_pain=test_price

            log.info(f'[OI] {symbol} max pain={max_pain}')
            return max_pain
        except Exception as e:
            log.debug(f'[OI] Max pain error: {e}')
            return 0

    def get_oi_levels(self,symbol='NIFTY'):
        """Get high OI strikes as S/R levels"""
        try:
            data=self.fetch_option_chain(symbol)
            if not data:return [],[]

            ce_strikes={}
            pe_strikes={}

            for item in data.get('records',{}).get('data',[]):
                strike=item.get('strikePrice',0)
                ce_oi=item.get('CE',{}).get('openInterest',0)
                pe_oi=item.get('PE',{}).get('openInterest',0)
                if ce_oi>0:ce_strikes[strike]=ce_oi
                if pe_oi>0:pe_strikes[strike]=pe_oi

            # Top 3 CE strikes = resistance
            top_ce=sorted(ce_strikes,key=lambda x:-ce_strikes[x])[:3]
            # Top 3 PE strikes = support
            top_pe=sorted(pe_strikes,key=lambda x:-pe_strikes[x])[:3]

            log.info(f'[OI] {symbol} resistance={top_ce} support={top_pe}')
            return top_ce,top_pe
        except Exception as e:
            log.debug(f'[OI] OI levels error: {e}')
            return [],[]

    def score_signal(self,instrument,action,price):
        """
        Score signal based on PCR + OI
        Returns: score_boost (-3 to +3)
        """
        try:
            # Only for indices
            index_map={
                'NIFTY':'NIFTY','BANKNIFTY':'BANKNIFTY',
                'FINNIFTY':'FINNIFTY','MIDCPNIFTY':'MIDCPNIFTY',
                'SENSEX':'SENSEX'
            }
            sym=index_map.get(instrument)
            if not sym:return 0

            total_pcr,atm_pcr,signal=self.get_pcr(sym)
            ce_levels,pe_levels=self.get_oi_levels(sym)
            max_pain=self.get_max_pain(sym)

            boost=0

            # PCR alignment
            if action=='BUY' and signal=='BULLISH':
                boost+=2
                log.info(f'[OI] {instrument} BUY aligned with PCR={atm_pcr:.2f} +2')
            elif action=='BUY' and signal=='BEARISH':
                boost-=2
                log.info(f'[OI] {instrument} BUY against PCR={atm_pcr:.2f} -2')
            elif action in ('SELL','PE') and signal=='BEARISH':
                boost+=2
            elif action in ('SELL','PE') and signal=='BULLISH':
                boost-=2

            # Max pain proximity
            if max_pain>0:
                dist=abs(price-max_pain)/max(price*0.01,1)
                if dist<1.0:
                    boost+=1
                    log.info(f'[OI] Near max pain {max_pain} +1')

            # Near high OI strike (resistance for BUY)
            if action=='BUY':
                for strike in ce_levels:
                    if 0<strike-price<price*0.005:
                        boost-=1
                        log.info(f'[OI] Near CE wall {strike} -1')
            else:
                for strike in pe_levels:
                    if 0<price-strike<price*0.005:
                        boost-=1

            return max(min(boost,3),-3)
        except Exception as e:
            log.debug(f'[OI] Score error: {e}')
            return 0

# Global instance
oi_pcr=OIPCREngine()
