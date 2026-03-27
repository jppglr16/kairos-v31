"""
V31 GEX Engine - Dealer Positioning Model
Uses existing v31_oi_pcr data source!
No new API calls needed!
"""
import logging
log = logging.getLogger(__name__)

def get_oi_data(instrument):
    """Get OI data from existing engine"""
    try:
        from v31_oi_pcr import oi_pcr
        # Get strikes data
        strikes = {}
        data = oi_pcr._fetch_option_chain(instrument)
        if not data:
            return []

        oi_list = []
        for item in data:
            strike = item.get('strikePrice', 0)
            ce_oi = item.get('CE', {}).get('openInterest', 0)
            pe_oi = item.get('PE', {}).get('openInterest', 0)
            if strike > 0:
                oi_list.append({
                    'strike': float(strike),
                    'ce_oi': ce_oi or 0,
                    'pe_oi': pe_oi or 0,
                })
        return oi_list
    except Exception as e:
        log.debug(f'[GEX] OI fetch error: {e}')
        return []

def calculate_gex(oi_data, spot):
    """
    Calculate Gamma Exposure per strike
    Positive GEX = dealers long gamma (pinning)
    Negative GEX = dealers short gamma (explosive!)
    """
    try:
        if not oi_data or spot <= 0:
            return 0, []

        total_gex = 0
        strike_gex = []

        for row in oi_data:
            strike = row['strike']
            ce_oi = row.get('ce_oi', 0)
            pe_oi = row.get('pe_oi', 0)

            # Gamma proxy: distance from spot × OI
            # Calls above spot = positive gamma
            # Puts below spot = negative gamma
            call_gamma = ce_oi * max(0, spot - strike)
            put_gamma  = pe_oi * max(0, strike - spot)
            net = call_gamma - put_gamma

            total_gex += net
            strike_gex.append({
                'strike': strike,
                'gex': net,
                'ce_oi': ce_oi,
                'pe_oi': pe_oi,
            })

        return total_gex, strike_gex

    except Exception as e:
        log.error(f'[GEX] Calc error: {e}')
        return 0, []

def find_key_levels(strike_gex):
    """Find call wall and put wall"""
    try:
        if not strike_gex:
            return None, None
        call_wall = max(strike_gex, key=lambda x: x['gex'])
        put_wall  = min(strike_gex, key=lambda x: x['gex'])
        return call_wall['strike'], put_wall['strike']
    except:
        return None, None

def find_gamma_flip(strike_gex):
    """
    Level where GEX changes from negative to positive
    = Most explosive zone for options!
    """
    try:
        if not strike_gex:
            return None
        sorted_data = sorted(strike_gex, key=lambda x: x['strike'])
        for i in range(1, len(sorted_data)):
            prev = sorted_data[i-1]
            curr = sorted_data[i]
            if prev['gex'] < 0 and curr['gex'] > 0:
                return curr['strike']
        return None
    except:
        return None

def interpret_gex(total_gex):
    """
    LONG_GAMMA = market pinned, mean reverting
    SHORT_GAMMA = explosive moves expected!
    """
    if total_gex > 500000:
        return 'LONG_GAMMA'    # Pinned ❌ avoid
    elif total_gex < -500000:
        return 'SHORT_GAMMA'   # Explosive ✅ trade!
    elif total_gex < 0:
        return 'SLIGHT_SHORT'  # Leaning explosive
    return 'NEUTRAL'

def get_gex_analysis(instrument, spot):
    """
    Complete GEX analysis - one call!
    Returns all dealer positioning data
    """
    try:
        oi_data = get_oi_data(instrument)
        if not oi_data:
            return None

        total_gex, strike_gex = calculate_gex(oi_data, spot)
        call_wall, put_wall = find_key_levels(strike_gex)
        gamma_flip = find_gamma_flip(strike_gex)
        gex_bias = interpret_gex(total_gex)

        result = {
            'total_gex': total_gex,
            'gex_bias': gex_bias,
            'call_wall': call_wall,
            'put_wall': put_wall,
            'gamma_flip': gamma_flip,
        }

        log.info(f'[GEX] {instrument}: bias={gex_bias} '
                 f'flip={gamma_flip} '
                 f'call_wall={call_wall} put_wall={put_wall}')

        return result

    except Exception as e:
        log.error(f'[GEX] Analysis error: {e}')
        return None
