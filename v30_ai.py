import logging
from datetime import datetime
from v30_oi import get_pcr_and_bias
from v30_sentiment import get_sentiment_bias, get_sentiment_score
from v30_ml import extract_features, rule_based_predict

log = logging.getLogger(__name__)

NSE_SYMBOLS = {
    'NIFTY': 'NIFTY',
    'BANKNIFTY': 'BANKNIFTY',
    'FINNIFTY': 'FINNIFTY',
    'MIDCPNIFTY': 'MIDCPNIFTY'
}

oi_cache = {}
sentiment_cache = {'score': 0, 'time': None}

def get_oi_cached(instrument):
    global oi_cache
    now = datetime.now()
    if instrument in oi_cache:
        age = (now - oi_cache[instrument]['time']).seconds
        if age < 300:
            return oi_cache[instrument]['data']
    symbol = NSE_SYMBOLS.get(instrument)
    if not symbol: return None
    data = get_pcr_and_bias(symbol)
    if data:
        oi_cache[instrument] = {'data': data, 'time': now}
    return data

def get_sentiment_cached():
    global sentiment_cache
    now = datetime.now()
    if sentiment_cache['time']:
        age = (now - sentiment_cache['time']).seconds
        if age < 1800:
            return sentiment_cache['score']
    score = get_sentiment_score()
    sentiment_cache = {'score': score, 'time': now}
    return score

def get_best_strike(oi_data, action):
    if not oi_data: return None, None
    if action == 'BUY':
        return oi_data.get('best_ce_strike'), oi_data.get('best_ce_premium')
    else:
        return oi_data.get('best_pe_strike'), oi_data.get('best_pe_premium')

def ai_analyze(df5, df15, instrument, smc_signal, mom_signal):
    try:
        features = extract_features(df5, df15)
        oi_data = get_oi_cached(instrument) if instrument in NSE_SYMBOLS else None
        sentiment = get_sentiment_cached()
        ml_score, ml_direction = rule_based_predict(features, oi_data, sentiment)

        # Combine all signals
        signals = []
        if smc_signal.get('action') == 'BUY': signals.append(1)
        elif smc_signal.get('action') == 'SELL': signals.append(-1)
        if mom_signal.get('momentum') == 'BULLISH': signals.append(1)
        elif mom_signal.get('momentum') == 'BEARISH': signals.append(-1)
        if ml_direction == 'BULLISH': signals.append(1)
        elif ml_direction == 'BEARISH': signals.append(-1)
        if oi_data:
            if oi_data.get('pcr_bias') == 'BULLISH': signals.append(1)
            elif oi_data.get('pcr_bias') == 'BEARISH': signals.append(-1)

        if not signals: return None

        avg = sum(signals)/len(signals)
        confidence = int(abs(avg) * 100)

        if avg > 0.3: final_action = 'BUY'
        elif avg < -0.3: final_action = 'SELL'
        else: return None

        # Get best strike from OI
        best_strike, best_premium = get_best_strike(oi_data, final_action)

        result = {
            'action': final_action,
            'confidence': confidence,
            'ml_score': ml_score,
            'ml_direction': ml_direction,
            'pcr': oi_data.get('pcr') if oi_data else None,
            'pcr_bias': oi_data.get('pcr_bias') if oi_data else None,
            'oi_bias': oi_data.get('oi_bias') if oi_data else None,
            'sentiment': sentiment,
            'best_strike': best_strike,
            'best_premium': best_premium,
            'signals_count': len(signals),
            'signals_aligned': confidence
        }

        log.info(f'[AI] {instrument} {final_action} | Conf:{confidence}% | PCR:{result["pcr"]} | ML:{ml_direction} | Sentiment:{sentiment:.2f}')
        return result

    except Exception as e:
        log.error(f'[AI] Error: {e}')
        return None
