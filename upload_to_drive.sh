#!/bin/bash
# Upload training data to Google Drive
# Run this on Android first!

cd ~/kairos_kotak_bot

echo "Creating zip of training data..."
zip -r kairos_v31_data.zip \
    historical_data/ \
    v31_trainer.py \
    v31_ensemble.py \
    v31_ml_engine.py \
    v31_rl_engine.py \
    v31_transformer.py \
    v31_strategy.py \
    v31_scoring.py \
    v30_rr_filter.py \
    v30_cache.py \
    -x "*.pyc" -x "__pycache__/*"

echo "Zip created: kairos_v31_data.zip"
echo "Upload this to Google Drive manually!"
echo "Then run Colab notebook!"
