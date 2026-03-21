#!/bin/bash
cd ~/kairos_kotak_bot

TRAINING_COMPLETE_FILE="ml_models/.training_complete"

log() { echo "$(date '+%Y-%m-%d %H:%M'): $1" >> scheduler_log.txt; }

pause_training() {
    # Get PIDs and send STOP signal
    for PID in $(ps aux | grep "[v]31_trainer" | awk "{print \$2}"); do
        kill -STOP $PID 2>/dev/null
        log "Paused trainer PID $PID"
    done
    for PID in $(ps aux | grep "[v]31_ensemble" | awk "{print \$2}"); do
        kill -STOP $PID 2>/dev/null
        log "Paused ensemble PID $PID"
    done
    log "Training PAUSED"
}

resume_training() {
    for PID in $(ps aux | grep "[v]31_trainer" | awk "{print \$2}"); do
        kill -CONT $PID 2>/dev/null
        log "Resumed trainer PID $PID"
    done
    for PID in $(ps aux | grep "[v]31_ensemble" | awk "{print \$2}"); do
        kill -CONT $PID 2>/dev/null
        log "Resumed ensemble PID $PID"
    done
    log "Training RESUMED"
}

start_training_if_needed() {
    if ! ps aux | grep -q "[v]31_trainer"; then
        nohup python3 v31_trainer.py >> v31_training_log.txt 2>&1 &
        log "Trainer started PID: $!"
    fi
    if ! ps aux | grep -q "[v]31_ensemble"; then
        nohup python3 v31_ensemble.py >> ensemble_training_log.txt 2>&1 &
        log "Ensemble started PID: $!"
    fi
}

check_training_complete() {
    DONE=$(ls ml_models/*v31_all_signals*.json 2>/dev/null | grep -v bt | wc -l)
    RL=$(ls ml_models/*v31_rl.pkl 2>/dev/null | wc -l)
    TF=$(ls ml_models/*v31_transformer.pkl 2>/dev/null | wc -l)
    if [ "$DONE" -ge 17 ] && [ "$RL" -ge 15 ] && [ "$TF" -ge 15 ]; then
        touch $TRAINING_COMPLETE_FILE
        log "✅ Training COMPLETE!"
        python3 -c "
from v30_notify import send
send('🎓 V31 Training Complete!\n18/18 done!\nWeekly retrain Sat+Sun 10PM!')
" 2>/dev/null
        return 0
    fi
    return 1
}

run_weekly_retrain() {
    log "Weekly retrain starting..."
    python3 v31_trainer.py >> v31_training_log.txt 2>&1
    python3 v31_failure_optimizer.py >> optimizer_log.txt 2>&1
    python3 v31_ensemble.py >> ensemble_training_log.txt 2>&1
    log "Weekly retrain complete!"
    python3 -c "
from v30_notify import send
send('🔄 Weekly Retrain Complete!\nAll 18 models updated!\nBot ready for next week!')
" 2>/dev/null
}

log "Smart scheduler started!"
python3 -c "
from v30_notify import send
send('🤖 Smart Scheduler Active!\n8:45AM → Pause training\n9:00AM → Check V31\n11:30PM → Resume training\nSat+Sun 10PM → Weekly retrain\n🛡️ Duplicate check every 60 secs!')
" 2>/dev/null

LAST_30MIN=""

while true; do
    HOUR=$(date +%H)
    MIN=$(date +%M)
    DAY=$(date +%u)
    HHMM="${HOUR}:${MIN}"

    # ============================================================
    # 8:45 AM - Pause training + Good morning
    # ============================================================
    if [ "$HHMM" = "08:45" ]; then
        pause_training
        DONE=$(ls ml_models/*v31_all_signals*.json 2>/dev/null | grep -v bt | wc -l)
        RL=$(ls ml_models/*v31_rl.pkl 2>/dev/null | wc -l)
        python3 -c "
from v30_notify import send
from datetime import datetime
import os
files=[f for f in os.listdir('ml_models') if 'v31_all_signals' in f and 'bt' not in f]
rl=[f for f in os.listdir('ml_models') if '_v31_rl.pkl' in f]
send(f'''🌅 Good Morning Ramkumar!
━━━━━━━━━━━━━━━
✅ V31 Ready for trading!
📊 Training: {len(files)}/18 models
🤖 RL Models: {len(rl)}/18
💰 Capital: Rs.50,000
🕐 {datetime.now().strftime(\"%d-%b-%Y\")}
━━━━━━━━━━━━━━━
⏰ Market opens 9:15 AM
🎯 First signals at 10:00 AM!''')
" 2>/dev/null
        log "8:45 AM - Training paused, good morning sent"
    fi

    # ============================================================
    # 9:00 AM - Ensure V31 running
    # ============================================================
    if [ "$HHMM" = "09:00" ]; then
        if ! ps aux | grep -q "[v]31_main"; then
            log "9:00 AM - V31 not running! Starting..."
            nohup bash start_v31.sh > /dev/null 2>&1 &
            python3 -c "
from v30_notify import send
send('⚠️ V31 was stopped!\nRestarted automatically!\nMarket ready!')
" 2>/dev/null
        else
            log "9:00 AM - V31 running ✅"
        fi
    fi

    # ============================================================
    # 11:30 PM - Resume training
    # ============================================================
    if [ "$HHMM" = "23:30" ]; then
        if [ ! -f "$TRAINING_COMPLETE_FILE" ]; then
            resume_training
            start_training_if_needed
            log "11:30 PM - Training resumed"
        else
            log "11:30 PM - Training complete, skip"
        fi
    fi

    # ============================================================
    # Every 30 mins - Check training progress
    # ============================================================
    CURRENT_30MIN="${HOUR}:$(( (10#$MIN / 30) * 30 ))"
    if [ "$CURRENT_30MIN" != "$LAST_30MIN" ]; then
        LAST_30MIN=$CURRENT_30MIN
        if [ ! -f "$TRAINING_COMPLETE_FILE" ]; then
            check_training_complete
            DONE=$(ls ml_models/*v31_all_signals*.json 2>/dev/null | grep -v bt | wc -l)
            log "Training progress: $DONE/18"
            if [ "$HOUR" -lt 8 ] || [ "$HOUR" -ge 23 ]; then
                start_training_if_needed
            fi
        fi
    fi

    # ============================================================
    # 3:32 PM - NSE Daily Summary
    # ============================================================
    if [ "$HHMM" = "15:32" ]; then
        log "Sending NSE daily summary..."
        python3 ~/kairos_kotak_bot/send_nse_summary.py >> daily_download_log.txt 2>&1
        log "NSE summary sent!"
    fi

    # ============================================================
    # 11:32 PM - Daily P&L Report (Trading days only!)
    # ============================================================
    if [ "$HHMM" = "23:32" ]; then
        # Only send on weekdays (Mon-Fri)
        DAY=$(date +%u)  # 1=Mon 7=Sun
        if [ "$DAY" -le "5" ]; then
            # Check if NSE holiday
            IS_HOLIDAY=$(python3 -c "
from v31_holidays import is_nse_holiday
from datetime import date
h,r=is_nse_holiday(date.today())
print('YES' if h else 'NO')
" 2>/dev/null)
            if [ "$IS_HOLIDAY" = "NO" ]; then
                log "Sending daily P&L report..."
                python3 -c "
from v31_trade_journal import trade_journal
trade_journal.send_daily_report()
" >> daily_download_log.txt 2>&1
                log "Daily P&L report sent!"
            else
                log "NSE Holiday - skipping P&L report"
            fi
        else
            log "Weekend - skipping P&L report"
        fi
    fi

    # ============================================================
    # 11:34 PM - Weekly P&L (Fridays only)
    # ============================================================
    if [ "$HHMM" = "23:34" ] && [ "$(date +%u)" = "5" ]; then
        log "Sending weekly P&L report..."
        python3 -c "
from v31_trade_journal import trade_journal
from v31_notify import send
weekly=trade_journal.get_weekly_pnl()
if weekly:
    msg='📊 Weekly P&L Summary
━━━━━━━━━━━━━━━
'
    total=0
    for d in weekly:
        e='✅' if d['pnl']>0 else '❌'
        msg+=f'{e} {d["date"]}: Rs.{d["pnl"]:,.0f} ({d["wins"]}/{d["trades"]} WR:{d["wr"]}%)
'
        total+=d['pnl']
    msg+=f'━━━━━━━━━━━━━━━
💰 Weekly Total: Rs.{total:,.0f}'
    send(msg)
" >> daily_download_log.txt 2>&1
        log "Weekly P&L sent!"
    fi

        # ============================================================
    # 3:35 PM - Download today candles after market close
    # ============================================================
    if [ "$HHMM" = "15:35" ]; then
        log "3:35 PM - Downloading today candles..."
        python3 -c "
import json,os,time
from SmartApi import SmartConnect
import pyotp
from datetime import datetime

obj=SmartConnect(api_key='pEOas0vU')
totp=pyotp.TOTP('R2T2F2BMP56U44O4OMOYJZTFJI').now()
obj.generateSession('J234619','1605',totp)

today=datetime.now().strftime('%Y-%m-%d')
year=datetime.now().strftime('%Y')

INSTRUMENTS={
    'NIFTY':{'token':'99926000','exchange':'NSE'},
    'BANKNIFTY':{'token':'99926009','exchange':'NSE'},
    'SENSEX':{'token':'99919000','exchange':'BSE'},
    'FINNIFTY':{'token':'99926037','exchange':'NSE'},
    'MIDCPNIFTY':{'token':'99926074','exchange':'NSE'},
    'CRUDEOIL':{'token':'472790','exchange':'MCX'},
    'GOLDM':{'token':'477904','exchange':'MCX'},
    'SILVERM':{'token':'457533','exchange':'MCX'},
    'LT':{'token':'11483','exchange':'NSE'},
    'NTPC':{'token':'11630','exchange':'NSE'},
    'MARUTI':{'token':'10999','exchange':'NSE'},
    'BHARTIARTL':{'token':'10604','exchange':'NSE'},
    'SBIN':{'token':'3045','exchange':'NSE'},
    'TATAMOTORS':{'token':'3456','exchange':'NSE'},
    'RELIANCE':{'token':'2885','exchange':'NSE'},
    'HINDUNILVR':{'token':'1394','exchange':'NSE'},
    'TCS':{'token':'11536','exchange':'NSE'},
    'TATASTEEL':{'token':'3499','exchange':'NSE'},
}

updated=0
for symbol,info in INSTRUMENTS.items():
    try:
        time.sleep(0.5)
        resp=obj.getCandleData({
            'exchange':info['exchange'],
            'symboltoken':info['token'],
            'interval':'FIVE_MINUTE',
            'fromdate':f'{today} 09:00',
            'todate':f'{today} 15:30'
        })
        if resp and resp.get('data'):
            candles=resp['data']
            fname=f'historical_data/{symbol}_{year}_5min.json'
            existing=json.load(open(fname)) if os.path.exists(fname) else []
            existing=[c for c in existing if not str(c[0]).startswith(today)]
            existing.extend(candles)
            json.dump(existing,open(fname,'w'))
            updated+=1
            print(f'{symbol}: +{len(candles)} candles')
    except Exception as e:
        print(f'{symbol}: {e}')
print(f'Done! Updated {updated}/18')
" >> daily_download_log.txt 2>&1
        log "Daily candles download complete!"
        python3 -c "
from v30_notify import send
send('📊 Daily candles downloaded!
All 18 instruments updated!
Data ready for tomorrow!')
" 2>/dev/null
    fi

    # ============================================================
    # Saturday + Sunday 10PM - Weekly retrain
    # ============================================================
    if [ "$HHMM" = "22:00" ]; then
        if [ "$DAY" = "6" ] || [ "$DAY" = "7" ]; then
            if [ -f "$TRAINING_COMPLETE_FILE" ]; then
                log "Weekend 10PM - Weekly retrain starting..."
                run_weekly_retrain
            fi
        fi
    fi

    # ============================================================
    # INTERNET CHECK - Every 5 mins
    # ============================================================
    if [ "$((10#$MIN % 5))" = "0" ]; then
        if ! ping -c 1 -W 3 8.8.8.8 > /dev/null 2>&1; then
            log "⚠️ Internet DOWN!"
            python3 -c "
from v30_notify import send
send('⚠️ Internet connection lost!
V31 may miss signals!
Check connection!')
" 2>/dev/null
        fi
    fi

    # ============================================================
    # UPDATE OPTIONS MASTER - Every day at 8:30 AM
    # ============================================================
    if [ "$HHMM" = "08:30" ]; then
        log "Updating Angel options master..."
        python3 /data/data/com.termux/files/home/kairos_kotak_bot/update_options_master.py >> daily_download_log.txt 2>&1
        log "Options master updated!"
        # Also refresh universal engine cache
        python3 -c "from v31_option_engine import refresh_cache; refresh_cache(); print('Engine cache refreshed!')" >> daily_download_log.txt 2>&1
    fi

    # ============================================================
    # WEEKLY RETRAIN - Saturday + Sunday 10 PM
    # ============================================================
    if [ "$HHMM" = "22:00" ] && [ "$(date +%u)" -ge "6" ]; then
        log "Starting weekly retrain..."
        python3 -c "
from v30_notify import send
send('🔄 Weekly Retrain Started!
📊 Training all 22 instruments
⏱️ Estimated: 4-6 hours')
" 2>/dev/null

        # Resume training processes
        kill -CONT $(pgrep -f v31_trainer.py) 2>/dev/null
        kill -CONT $(pgrep -f v31_ensemble.py) 2>/dev/null

        # Force retrain all models
        python3 -c "
import os,glob
# Remove old models for fresh retrain
models=glob.glob('ml_models/*v31_ml*.pkl')
for m in models:
    os.remove(m)
print(f'Removed {len(models)} old models for retrain')
" >> v31_training_log.txt 2>&1

        log "Weekly retrain initiated!"
    fi

    # WEEKLY RETRAIN COMPLETE CHECK - Sunday 6 AM
    if [ "$HHMM" = "06:00" ] && [ "$(date +%u)" = "7" ]; then
        python3 -c "
import os,glob
models=glob.glob('ml_models/*v31_ml*.pkl')
from v30_notify import send
send(f'✅ Weekly Retrain Status
📊 Models trained: {len(models)}/22
🎯 Ready for Monday!')
" 2>/dev/null
        log "Weekly retrain status sent!"
    fi

    # ============================================================
    # LOG ROTATION - Every day at 4AM
    # ============================================================
    # GitHub auto-backup at 4:05 AM
    if [ "$HHMM" = "04:05" ]; then
        cd ~/kairos_kotak_bot
        git add *.py *.sh *.json *.txt 2>/dev/null
        git commit -m "Daily backup $(date +%Y%m%d_%H%M)" 2>/dev/null
        git push origin main 2>/dev/null
        log "GitHub backup done!"
    fi

    if [ "$HHMM" = "04:00" ]; then
        log "Rotating logs..."
        python3 -c "
from v31_health_monitor import rotate_logs
rotate_logs()
print('Logs rotated!')
" 2>/dev/null
        log "Logs rotated!"
    fi

    # ============================================================
    # CAPITAL REFRESH - Every hour
    # ============================================================
    if [ "$MIN" = "00" ]; then
        python3 -c "
from v31_health_monitor import get_capital_angel
cap=get_capital_angel()
if cap>0:
    print(f'Angel capital: Rs.{cap:,}')
" >> daily_download_log.txt 2>&1
    fi

    # ============================================================
    # DUPLICATE CHECK - Every 60 seconds! 🛡️
    # ============================================================
    V31_COUNT=$(ps aux | grep "[v]31_main" | grep -v grep | wc -l)
    if [ "$V31_COUNT" -gt 1 ]; then
        log "⚠️ Duplicate V31 detected ($V31_COUNT)! Fixing..."
        pkill -f v31_main 2>/dev/null
        sleep 3
        nohup bash start_v31.sh > /dev/null 2>&1 &
        log "V31 restarted - single instance!"
        python3 -c "
from v30_notify import send
send('⚠️ Duplicate V31 detected!\nFixed automatically!\nSingle instance running!')
" 2>/dev/null
    fi

    sleep 60
done
