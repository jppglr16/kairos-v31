#!/bin/bash
# Run every Sunday night
echo "Starting weekly V31 retrain..."
pkill -f v31_trainer
sleep 2
nohup python3 v31_trainer.py > v31_training_log.txt 2>&1 &
echo "Retrain started PID: $!"
