#!/bin/bash
cd ~/kairos_kotak_bot

echo "Step 1: Waiting for training to complete..."
while true; do
    COUNT=$(ls ml_models/*v31_all_signals*.json 2>/dev/null | grep -v bt | wc -l)
    echo "$(date): Training $COUNT/18"
    if [ "$COUNT" -ge 17 ]; then
        echo "Training complete!"
        break
    fi
    sleep 300
done

echo "Step 2: Running failure optimizer..."
python3 v31_failure_optimizer.py > optimizer_log.txt 2>&1

echo "Step 3: Notifying..."
python3 -c "
from v30_notify import send
send('✅ V31 Training + Optimization Complete!\nBot ready for trading!')
"
echo "Pipeline complete!"
