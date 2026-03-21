from v31_holidays import market_status
from v31_option_engine import load_all_options
from v30_notify import send
import glob,json,os
from datetime import datetime

s=market_status()
import glob as _glob
all_pkls=_glob.glob('ml_models/*.pkl')
# Count unique instruments with models
trained=set()
for f in all_pkls:
    inst=os.path.basename(f).split('_')[0]
    trained.add(inst)
models=list(trained)
# Count v31_ml models specifically
v31_models=[f for f in all_pkls if "_model.pkl" in f or "_v31_ml.pkl" in f]
from v31_instrument_manager import INSTRUMENTS as _INST
v31_count=len([i for i in set(os.path.basename(f).split("_")[0] for f in v31_models) if i in _INST])
opts=load_all_options()

open_pos=[]
if os.path.exists('active_positions.json'):
    pos=json.load(open('active_positions.json'))
    open_pos=[p for p in pos.values() if p.get('status')=='OPEN']

margin=0
try:
    from v31_angel_trader import angel_trader
    angel_trader.connect()
    import time; time.sleep(2)
    r=angel_trader.obj.rmsLimit()
    if r and r.get('data'):
        margin=float(r['data'].get('availablecash',0) or 0)
except:pass

nse_ok=not s['nse_holiday']
mcx_ok=not s['mcx_holiday']
funded=margin>50000

# Auto-trigger training for missing instruments
try:
    from v31_instrument_manager import INSTRUMENTS
    all_insts=list(INSTRUMENTS.keys())
    missing_train=[i for i in all_insts if i not in trained]
    if missing_train:
        import subprocess
        for inst in missing_train:
            # Download data if missing
            data_files=glob.glob(f'historical_data/{inst}_*.json')
            if not data_files:
                subprocess.Popen(['python3','download_stock_data.py',inst],
                               stdout=open('daily_download_log.txt','a'),
                               stderr=subprocess.STDOUT)
        # Notify
        from v30_notify import send as _send
        _missing_str=', '.join(missing_train)
        _send(f"Training missing: {_missing_str}\nStarting auto-train...")
        # Resume trainer
        import os as _os
        _os.system('kill -CONT $(pgrep -f v31_trainer.py) 2>/dev/null')
except Exception as _te:
    pass

lines=[
    "V31 Morning Checklist",
    "=" * 20,
    datetime.now().strftime("%d %b %Y %H:%M"),
    "",
    "MARKET:",
    ("OK" if nse_ok else "CLOSED") + " NSE Today",
    ("OK" if mcx_ok else "CLOSED") + " MCX Today",
    "",
    "SYSTEM:",
    f"ML Models: {{v31_count}}/32",
    f"Options Cache: {len(opts):,}",
    f"Capital: Rs.{margin:,.0f}",
    f"Open Positions: {len(open_pos)}",
    "",
    "RULES:",
    "Max 1 signal per instrument",
    "SL must be from FVG/OB",
    "Exit NSE by 3:15 PM",
    "Exit MCX by 11:15 PM",
    "Never average down!",
    "",
    "GO LIVE!" if funded else "ADD FUNDS FIRST!",
    "NSE Opens: 9:15 AM",
]
msg="\n".join(lines)
send(msg)
print('Morning checklist sent!')
