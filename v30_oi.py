import requests,json
from datetime import datetime

HEADERS = {
    'User-Agent': 'Mozilla/5.0',
    'Accept': 'application/json',
    'Referer': 'https://www.nseindia.com'
}

def get_nse_session():
    s = requests.Session()
    s.get('https://www.nseindia.com', headers=HEADERS, timeout=10)
    return s

def get_option_chain(symbol):
    try:
        s = get_nse_session()
        url = f'https://www.nseindia.com/api/option-chain-indices?symbol={symbol}'
        r = s.get(url, headers=HEADERS, timeout=10)
        return r.json()
    except Exception as e:
        print(f'[OI] Error {symbol}: {e}')
        return None

def get_pcr_and_bias(symbol):
    try:
        data = get_option_chain(symbol)
        if not data: return None
        records = data['records']['data']
        atm = data['records']['underlyingValue']
        
        total_ce_oi = 0
        total_pe_oi = 0
        ce_oi_change = 0
        pe_oi_change = 0
        best_ce_strike = None
        best_pe_strike = None
        best_ce_premium = 0
        best_pe_premium = 0
        
        for rec in records:
            if 'CE' in rec:
                total_ce_oi += rec['CE'].get('openInterest', 0)
                ce_oi_change += rec['CE'].get('changeinOpenInterest', 0)
                premium = rec['CE'].get('lastPrice', 0)
                if 100 <= premium <= 150:
                    if best_ce_strike is None:
                        best_ce_strike = rec['strikePrice']
                        best_ce_premium = premium
            if 'PE' in rec:
                total_pe_oi += rec['PE'].get('openInterest', 0)
                pe_oi_change += rec['PE'].get('changeinOpenInterest', 0)
                premium = rec['PE'].get('lastPrice', 0)
                if 100 <= premium <= 150:
                    if best_pe_strike is None:
                        best_pe_strike = rec['strikePrice']
                        best_pe_premium = premium

        pcr = total_pe_oi / total_ce_oi if total_ce_oi > 0 else 1
        
        # PCR interpretation
        if pcr > 1.3:
            bias = 'BULLISH'
        elif pcr < 0.7:
            bias = 'BEARISH'
        else:
            bias = 'NEUTRAL'

        # OI change confirmation
        if ce_oi_change > pe_oi_change * 1.5:
            oi_bias = 'BEARISH'
        elif pe_oi_change > ce_oi_change * 1.5:
            oi_bias = 'BULLISH'
        else:
            oi_bias = 'NEUTRAL'

        return {
            'symbol': symbol,
            'atm': atm,
            'pcr': round(pcr, 2),
            'pcr_bias': bias,
            'oi_bias': oi_bias,
            'best_ce_strike': best_ce_strike,
            'best_ce_premium': best_ce_premium,
            'best_pe_strike': best_pe_strike,
            'best_pe_premium': best_pe_premium,
            'total_ce_oi': total_ce_oi,
            'total_pe_oi': total_pe_oi,
            'timestamp': str(datetime.now())
        }
    except Exception as e:
        print(f'[OI] PCR error: {e}')
        return None
