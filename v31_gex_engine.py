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

            # Fix 2: Skip deep OTM (noise reduction!)
            if abs(strike - spot) > spot * 0.10:
                continue

            # Fix 1: Distance decay weighting
            # ATM dominates, far OTM less influence!
            distance = abs(spot - strike)
            weight = 1.0 / (1.0 + distance / max(spot * 0.01, 1))

            call_gamma = ce_oi * max(0, spot-strike) * weight
            put_gamma  = pe_oi * max(0, strike-spot) * weight
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
    """
    Fix 5: OI-based walls (matches real institutional levels!)
    """
    try:
        if not strike_gex:
            return None, None
        # Call wall = strike with max CE OI
        call_wall = max(strike_gex, key=lambda x: x['ce_oi'])
        # Put wall = strike with max PE OI
        put_wall  = max(strike_gex, key=lambda x: x['pe_oi'])
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

def interpret_gex(total_gex, oi_data=None):
    """
    Adaptive thresholds based on instrument scale!
    Works for NIFTY, BANKNIFTY, stocks equally!
    """
    # Fix 3: Adaptive scale
    if oi_data:
        scale = sum(abs(r.get('ce_oi',0)+r.get('pe_oi',0))
                   for r in oi_data)
    else:
        scale = 1000000  # fallback

    # Fix 4: GEX strength
    gex_strength = round(total_gex / max(scale, 1), 4)

    if gex_strength > 0.10:
        return 'LONG_GAMMA', gex_strength
    elif gex_strength < -0.10:
        return 'SHORT_GAMMA', gex_strength
    elif gex_strength < 0:
        return 'SLIGHT_SHORT', gex_strength
    return 'NEUTRAL', gex_strength

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
        gex_bias, gex_strength = interpret_gex(total_gex, oi_data)

        result = {
            'total_gex': total_gex,
            'gex_strength': gex_strength,
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
