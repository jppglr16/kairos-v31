#!/bin/bash
# Usage: bash add_instrument.sh HDFCBANK
INST=$1
echo "Checking $INST..."
python3 -c "
import sys
from v31_instrument_manager import INSTRUMENTS,instrument_manager

inst='$INST'

# Check if already exists
if inst in INSTRUMENTS:
    print(f'⚠️ {inst} already exists! Skipping.')
    sys.exit(0)

print(f'Adding {inst} to V31...')
from v31_angel_trader import angel_trader
angel_trader.connect()
import time; time.sleep(2)
result=instrument_manager.auto_add_instrument(inst,angel_trader.obj)
print('✅ Done!' if result else '❌ Failed!')
" 2>/dev/null
echo "Restart V31: startv31"
