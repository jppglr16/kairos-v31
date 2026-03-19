#!/bin/bash
while true; do
    COUNT=$(ls ml_models/*v31_all_signals* 2>/dev/null | wc -l)
    echo "$(date): $COUNT/18 done"
    if [ "$COUNT" -eq 18 ]; then
        python3 -c "
from v30_notify import send
send('✅ V31 Training Complete!\n18/18 instruments done!\nMeta layer ready!')
"
        echo "Training complete!"
        break
    fi
    sleep 300  # Check every 5 mins
done
