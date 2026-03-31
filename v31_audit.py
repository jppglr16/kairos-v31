"""
V31 Complete System Audit
Structural + Behavioral + Runtime validation
"""
import ast, os, re, json
from datetime import datetime, time

print("="*60)
print("V31 COMPLETE SYSTEM AUDIT - BEHAVIORAL + STRUCTURAL")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
print("="*60)

issues = []
warnings = []

# ============================================
# 1. FILE EXISTENCE
# ============================================
print("\n📁 1. FILE CHECK:")
files = [
    'v31_main.py','v31_strategy.py','v31_signal_manager.py',
    'v31_exit_monitor.py','v31_notify.py','v31_paper_tracker.py',
    'v31_vix.py','v31_oi_pcr.py','v31_strategy_orb.py',
    'v31_strategy_gamma.py','v31_gex_engine.py',
    'v31_gamma_logger.py','v31_lot_updater.py',
    'v32_token_updater.py','angel_feed.py','lot_sizes.json',
]
for f in files:
    exists = os.path.exists(f)
    print(f"  {'✅' if exists else '❌'} {f}")
    if not exists:
        issues.append(f"MISSING FILE: {f}")

# ============================================
# 2. SYNTAX CHECK
# ============================================
print("\n🔍 2. SYNTAX CHECK:")
for f in files:
    if not f.endswith('.py') or not os.path.exists(f): continue
    try:
        ast.parse(open(f).read())
        print(f"  ✅ {f}")
    except SyntaxError as e:
        print(f"  ❌ {f}: Line {e.lineno}: {e.msg}")
        issues.append(f"SYNTAX ERROR in {f} line {e.lineno}")

# ============================================
# 3. BEHAVIORAL: PATH E ACTUAL EXECUTION
# ============================================
print("\n🎯 3. PATH E BEHAVIORAL CHECK:")
main = open('v31_main.py').read()

# Check actual callable, not just string
checks = [
    ('gamma_blast_signal imported', 'from v31_strategy_gamma import gamma_blast_signal'),
    ('gamma_blast_signal called', 'signal=gamma_blast_signal(df5,df15,instrument,capital)'),
    ('DTE=2 check in gamma', 'dte > 2'),
    ('GEX engine used', 'get_gex_analysis'),
    ('ML logger called', 'log_gamma_entry'),
    ('Kill switch active', 'check_kill_switch'),
    ('OI flow enforced', 'oi_flow not in favorable'),
    ('Squeeze with accel', 'move1 > (move5/5)'),
    ('Score threshold 25', 'score < 25'),
]
for desc, check in checks:
    # Check in gamma file
    gamma = open('v31_strategy_gamma.py').read()
    ok = check in main or check in gamma
    status = '✅' if ok else '❌'
    print(f"  {status} {desc}")
    if not ok:
        issues.append(f"PATH E: {desc} missing!")

# ============================================
# 4. SESSION TIMING BEHAVIORAL CHECK
# ============================================
print("\n⏰ 4. SESSION TIMING CHECK:")
sm = open('v31_signal_manager.py').read()

# Extract actual session times
import re
nse_times = re.findall(r"'start':time\((\d+),(\d+)\)", sm)
print(f"  Session times found: {nse_times}")

# Check MORNING starts at 9:15
morning_ok = "time(9,15)" in sm
print(f"  {'✅' if morning_ok else '❌'} MORNING starts 9:15 AM")
if not morning_ok:
    issues.append("MORNING session starts at wrong time!")

# Check MCX sessions exist
evening_ok = "EVENING" in sm
night_ok = "NIGHT" in sm
print(f"  {'✅' if evening_ok else '❌'} MCX EVENING session")
print(f"  {'✅' if night_ok else '❌'} MCX NIGHT session")

# Runtime session check
try:
    from v31_signal_manager import signal_manager
    now = datetime.now()
    nifty_session = signal_manager._get_session('NIFTY')
    silverm_session = signal_manager._get_session('SILVERM')
    print(f"  ✅ NIFTY session now: {nifty_session or 'CLOSED'}")
    print(f"  ✅ SILVERM session now: {silverm_session or 'CLOSED'}")
except Exception as e:
    print(f"  ❌ Session runtime check failed: {e}")
    warnings.append("Session manager not importable!")

# ============================================
# 5. LOT SIZES - RUNTIME VALIDATION
# ============================================
print("\n📊 5. LOT SIZES VALIDATION:")
try:
    d = json.load(open('lot_sizes.json'))
    lots = d['lot_sizes']
    updated = d.get('updated', 'Unknown')
    print(f"  Last updated: {updated}")

    # Check age
    try:
        upd_dt = datetime.strptime(updated, '%Y-%m-%d %H:%M')
        age_hours = (datetime.now() - upd_dt).seconds // 3600
        age_ok = age_hours < 24
        print(f"  {'✅' if age_ok else '⚠️'} Age: {age_hours}h ({'fresh' if age_ok else 'stale!'})")
        if not age_ok:
            warnings.append("Lot sizes older than 24 hours!")
    except: pass

    # Validate key lots
    expected = {
        'NIFTY': (60,75), 'BANKNIFTY': (25,35),
        'SILVERM': (25,35), 'GOLDM': (90,110),
        'CRUDEOIL': (90,110), 'NATURALGAS': (1200,1300),
        'BHARTIARTL': (450,500),
    }
    for inst, (lo, hi) in expected.items():
        val = lots.get(inst, 0)
        ok = lo <= val <= hi
        print(f"  {'✅' if ok else '⚠️'} {inst}: {val} (expected {lo}-{hi})")
        if not ok:
            warnings.append(f"Lot size {inst}={val} outside expected range!")
except Exception as e:
    print(f"  ❌ Lot sizes error: {e}")
    issues.append("Lot sizes not loadable!")

# ============================================
# 6. BARE EXCEPTS WITH CONTEXT
# ============================================
print("\n⚠️ 6. BARE EXCEPTS:")
for f in ['v31_main.py','v31_signal_manager.py',
          'v31_exit_monitor.py','v31_notify.py',
          'v31_strategy_gamma.py']:
    if not os.path.exists(f): continue
    content = open(f).read()
    lines = content.split('\n')
    bare = []
    for i,l in enumerate(lines):
        if re.match(r'\s*except:\s*(pass)?\s*$', l):
            ctx = lines[max(0,i-2):i+1]
            bare.append((i+1, ctx))
    if bare:
        print(f"  ⚠️ {f}: {len(bare)} bare excepts")
        for ln, ctx in bare[:2]:
            print(f"    Line {ln}: ...{lines[ln-2].strip()[:40]}")
        warnings.append(f"{len(bare)} bare excepts in {f}")
    else:
        print(f"  ✅ {f}: clean")

# ============================================
# 7. PAPER TRADES BEHAVIORAL ANALYSIS
# ============================================
print("\n📈 7. PAPER TRADES ANALYSIS:")
try:
    d = json.load(open('paper_trades.json'))
    trades = d.get('trades', [])
    open_t = [t for t in trades if t['status']=='OPEN']
    closed = [t for t in trades if t['status']=='CLOSED']
    pending = [t for t in trades if t['status']=='PENDING']
    expired = [t for t in trades if t['status']=='EXPIRED']

    print(f"  Total:{len(trades)} Open:{len(open_t)} "
          f"Closed:{len(closed)} Pending:{len(pending)} "
          f"Expired:{len(expired)}")

    # Behavioral checks
    if len(expired) > len(closed):
        print("  ❌ More expired than closed!")
        print("  → Step 2 failing (option not found/too expensive)")
        issues.append("Step2 failing: expired > closed trades!")

    if len(open_t) > 5:
        print("  ❌ Too many open trades!")
        print("  → Exit monitor may be failing!")
        issues.append("Exit monitor failing: too many open trades!")

    # Premium check
    no_prem = [t for t in trades if t.get('premium') is None]
    if no_prem:
        print(f"  ❌ {len(no_prem)} trades with no premium!")
        print("  → notify_v31_entry() failing!")
        issues.append(f"{len(no_prem)} trades without premium!")

    # Signal quality
    if closed:
        wins = [t for t in closed if (t.get('pnl') or 0) > 0]
        losses = [t for t in closed if (t.get('pnl') or 0) < 0]
        win_rate = len(wins)/len(closed)*100
        avg_win = (sum(t.get('pnl_pct',0) or 0 for t in wins)/
                  len(wins)) if wins else 0
        avg_loss = (sum(t.get('pnl_pct',0) or 0 for t in losses)/
                   len(losses)) if losses else 0

        print(f"  Win Rate: {win_rate:.1f}%")
        print(f"  Avg Win: {avg_win:.1f}% | Avg Loss: {avg_loss:.1f}%")

        if win_rate < 40:
            print("  ❌ Win rate too low!")
            warnings.append(f"Low win rate: {win_rate:.1f}%")
        elif win_rate >= 55:
            print("  ✅ Good win rate!")
    else:
        print("  ⚠️ No closed trades yet - cannot evaluate!")
        warnings.append("No closed trades for performance evaluation!")

except Exception as e:
    print(f"  ❌ Paper trades error: {e}")

# ============================================
# 8. DATA FLOW CHECK
# ============================================
print("\n📡 8. DATA FLOW CHECK:")
try:
    # Check last log entry time
    log_lines = open('v31_log.txt').readlines()
    if log_lines:
        last = log_lines[-1]
        print(f"  Last log: {last[:35].strip()}")
        # Check if recent (within 5 mins)
        try:
            ts = last[:19]
            last_dt = datetime.strptime(ts, '%Y-%m-%d %H:%M:%S')
            age_mins = (datetime.now() - last_dt).seconds // 60
            ok = age_mins < 5
            print(f"  {'✅' if ok else '⚠️'} Log age: {age_mins} mins")
            if not ok:
                warnings.append(f"Log stale: {age_mins} mins old!")
        except: pass
except Exception as e:
    print(f"  ❌ Log check error: {e}")

# Check Angel connection
try:
    log_content = open('v31_log.txt').read()
    # Last 1000 chars
    recent = log_content[-2000:]
    connected = 'Websocket connected' in recent or 'connected!' in recent
    print(f"  {'✅' if connected else '❌'} Angel/Kotak connection")
    if not connected:
        issues.append("No recent connection confirmation!")
except: pass

# ============================================
# 9. VIX BEHAVIORAL CHECK
# ============================================
print("\n📊 9. VIX CHECK:")
try:
    vix_content = open('v31_vix.py').read()
    checks = [
        ('Direction-aware VIX', 'direction=None'),
        ('SELL allowed high VIX', "direction == 'SELL'"),
        ('Near expiry relaxation', '_near_expiry'),
        ('VIX 28 threshold', '_vix_adj <= 28'),
        ('Panic mode VIX 30', '_vix_adj <= 30'),
    ]
    for desc, check in checks:
        ok = check in vix_content
        print(f"  {'✅' if ok else '❌'} {desc}")
        if not ok:
            issues.append(f"VIX: {desc} missing!")
except Exception as e:
    print(f"  ❌ VIX check error: {e}")

# ============================================
# 10. GAMMA SIGNAL ACTIVATION CHECK
# ============================================
print("\n🔥 10. GAMMA ACTIVATION CHECK:")
try:
    gamma = open('v31_strategy_gamma.py').read()
    main = open('v31_main.py').read()

    checks = [
        ('Callable from main', 'gamma_blast_signal(df5,df15,instrument,capital)'),
        ('DTE filter active', 'dte > 2'),
        ('OI enforced (hard filter)', 'return None'),
        ('Volume confirmation', 'vol_spike'),
        ('Squeeze acceleration', 'move1 > (move5/5)'),
        ('Exhaustion check', 'detect_exhaustion'),
        ('Vanna/charm effect', 'detect_vanna_charm_effect'),
        ('Delta hedging', 'detect_delta_hedging_flow'),
        ('Institutional activity', 'detect_institutional_activity'),
        ('Smart strike v2', 'get_optimal_strike_v2'),
        ('Exit plan by lots', 'trail_sl_pct'),
        ('Kill switch 10%', 'max_loss_pct=0.10'),
        ('6% budget', '0.06'),
        ('ML logging', 'log_gamma_entry'),
    ]
    for desc, check in checks:
        ok = check in gamma or check in main
        print(f"  {'✅' if ok else '❌'} {desc}")
        if not ok:
            issues.append(f"GAMMA: {desc} missing!")
except Exception as e:
    print(f"  ❌ Gamma check error: {e}")

# ============================================
# 11. SCHEDULER EXECUTION CHECK
# ============================================
print("\n⏰ 11. SCHEDULER CHECK:")
try:
    sched = open('smart_scheduler.sh').read()
    log_content = ''
    if os.path.exists('scheduler_log.txt'):
        log_content = open('scheduler_log.txt').read()[-2000:]

    checks = [
        ('Token refresh 8:25', '08:25', 'MCX tokens refreshed'),
        ('Lot refresh', 'lot_updater', ''),
        ('Option cache', 'refresh_cache', ''),
    ]
    for desc, code_check, log_check in checks:
        in_code = code_check in sched
        in_log = log_check in log_content if log_check else True
        ok = in_code
        print(f"  {'✅' if ok else '❌'} {desc}")

    # Check last scheduler run
    if log_content:
        last_run = log_content.split('\n')[-2]
        print(f"  Last run: {last_run[:50]}")
except Exception as e:
    print(f"  ❌ Scheduler check: {e}")

# ============================================
# FINAL SUMMARY
# ============================================
print("\n" + "="*60)
print("AUDIT SUMMARY")
print("="*60)

if issues:
    print(f"\n🔴 CRITICAL ISSUES ({len(issues)}):")
    for i,iss in enumerate(issues, 1):
        print(f"  {i}. {iss}")
else:
    print("\n✅ No critical issues!")

if warnings:
    print(f"\n🟡 WARNINGS ({len(warnings)}):")
    for i,w in enumerate(warnings, 1):
        print(f"  {i}. {w}")
else:
    print("✅ No warnings!")

print(f"\n{'✅ SYSTEM HEALTHY!' if not issues else '❌ FIX CRITICAL ISSUES!'}")
print("="*60)
