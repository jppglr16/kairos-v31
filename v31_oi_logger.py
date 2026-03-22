"""
V31 OI Visual Logger
Shows PCR, max pain, OI walls per signal
"""
import logging
from datetime import datetime
log=logging.getLogger(__name__)

class OIVisualLogger:
    def __init__(self):
        self.records=[]

    def log_signal(self,instrument,action,price,
                   boost,pcr,atm_pcr,signal,
                   max_pain,ce_levels,pe_levels):
        entry={
            'Time':datetime.now().strftime('%H:%M'),
            'Inst':instrument,
            'Act':action,
            'Price':f'{price:.0f}',
            'Boost':f'{boost:+d}',
            'PCR':f'{pcr:.2f}',
            'ATM':f'{atm_pcr:.2f}',
            'Sig':signal,
            'MaxPain':str(max_pain),
            'CE Wall':','.join(map(str,ce_levels[:2])),
            'PE Wall':','.join(map(str,pe_levels[:2]))
        }
        self.records.append(entry)

        # Keep last 10
        if len(self.records)>10:
            self.records=self.records[-10:]

        # Print table
        try:
            from tabulate import tabulate
            print('\n'+tabulate(
                self.records[-5:],
                headers='keys',
                tablefmt='simple'
            )+'\n')
        except:
            # Fallback without tabulate
            r=self.records[-1]
            log.info(f'[OI] {r["Inst"]} {r["Act"]} '
                    f'price={r["Price"]} boost={r["Boost"]} '
                    f'PCR={r["PCR"]} ATM={r["ATM"]} '
                    f'sig={r["Sig"]} maxpain={r["MaxPain"]}')

    def get_summary(self):
        """Get last 5 records as text"""
        if not self.records:
            return 'No OI signals yet'
        lines=['=== OI Signal Log ===']
        for r in self.records[-5:]:
            lines.append(
                f'{r["Time"]} {r["Inst"]:<12} '
                f'{r["Act"]:<5} boost={r["Boost"]} '
                f'PCR={r["PCR"]} {r["Sig"]}')
        return '\n'.join(lines)

# Global instance
oi_logger=OIVisualLogger()
