#!/bin/bash
cd ~/kairos_kotak_bot
LOCK="/tmp/v31.lock"

# Remove old lock
rm -f $LOCK

echo "$(date): Starting V31..."
while true; do
    # Check for duplicate V31 processes
    COUNT=$(ps aux | grep "[v]31_main" | grep -v grep | wc -l)
    if [ "$COUNT" -gt 1 ]; then
        echo "$(date): Duplicate detected! Killing..."
        pkill -f "v31_main"
        sleep 2
    fi
    echo $$ > $LOCK
    python v31_main.py >> v31_log.txt 2>&1
    echo "$(date): V31 stopped. Restarting in 10s..."
    rm -f $LOCK
    sleep 10
done
