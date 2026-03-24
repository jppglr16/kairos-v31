# V32 Auto-Learning Strike Selector

## Components:
1. v31_stats.py - record_trade() + get_score()
2. Strike stats: ml_models/strike_stats.json
3. Smart ladder: sorted by get_score()
4. Distance buckets: NIFTY_1.0_50pts
5. 20% exploration: random.shuffle()

## Key fields to log:
- instrument, mult, dist, premium, pnl, result

## Scoring formula:
score = (winrate × 0.7) + (avg_pnl × 0.3)

## Needs: 50+ trades per instrument
## Target: Week 2-3 after live trading!

# V32 Real-Time Tick Builder

## Architecture:
Tick → update_candle() → check_signal() → execute!

## update_candle():
candle['close'] = tick_price
candle['high'] = max(candle['high'], tick_price)
candle['low'] = min(candle['low'], tick_price)
candle['volume'] += tick_volume

## New candle every 5 mins:
if tick_time.minute % 5 == 0:
    finalize_old()
    start_new()
    run_signals()

## Benefits:
= 0-2 second signal delay (vs 60 sec!)
= Catch breakouts instantly!
= Better entry prices!

## Needs:
= Angel One WebSocket tick data
= Complete signal engine rewrite
= Target: V32 Week 2
