#!/bin/bash
cd ~/kairos_kotak_bot

echo "$(date): Auto scheduler started!"

while true; do
    HOUR=$(date +%H)
    DAY=$(date +%u)  # 1=Mon 7=Sun

    # Night: 10PM-6AM = run training
    if [ "$HOUR" -ge 22 ] || [ "$HOUR" -lt 6 ]; then
        # Only if trainer NOT already running
        if ! ps aux | grep -q "v31_trainer"; then
            echo "$(date): Starting nightly training..."
            python3 v31_trainer.py >> v31_training_log.txt 2>&1
            echo "$(date): Trainer done!"
            python3 v31_failure_optimizer.py >> optimizer_log.txt 2>&1
            echo "$(date): Optimizer done!"
        else
            echo "$(date): Trainer already running - skip"
        fi
    fi

    # Weekend Sunday 10PM = Full ensemble retrain
    if [ "$DAY" -eq 7 ] && [ "$HOUR" -eq 22 ]; then
        if ! ps aux | grep -q "v31_ensemble"; then
            echo "$(date): Weekend ensemble retrain..."
            python3 v31_ensemble.py >> ensemble_training_log.txt 2>&1
            echo "$(date): Ensemble done!"
        fi
    fi

    # Morning 9AM = notify ready
    if [ "$HOUR" -eq 9 ]; then
        python3 -c "
from v30_notify import send
import os,json
files=[f for f in os.listdir('ml_models') if 'v31_all_signals' in f]
send(f'🌅 Good Morning!\nV31 Ready!\nModels: {len(files)}/18\nMarket opens in 15 mins!')
" 2>/dev/null
        sleep 3600  # Don't repeat for 1 hour
    fi

    sleep 3600  # Check every hour
done
