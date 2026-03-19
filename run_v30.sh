#!/bin/bash
cd ~/kairos_kotak_bot
while true; do
  echo "Starting V30..."
  python v30_main.py
  echo "Crashed. Restarting in 30s..."
  sleep 30
done
