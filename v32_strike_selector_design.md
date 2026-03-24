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
