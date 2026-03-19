content=open('v30_train_all.py').read()
old="""    'NIFTY':     {'type':'index','lot':75},
    'BANKNIFTY': {'type':'index','lot':30},
    'SENSEX':    {'type':'index','lot':10},
    'FINNIFTY':  {'type':'index','lot':65},
    'MIDCPNIFTY':{'type':'index','lot':120},
    'CRUDEOIL':  {'type':'commodity','lot':100},
    'GOLDM':     {'type':'commodity','lot':10},
    'SILVERM':   {'type':'commodity','lot':30},
    'BANKNIFTY': {'type':'index','lot':30},
    'CRUDEOIL':  {'type':'commodity','lot':100},"""
new="""    'NIFTY':     {'type':'index','lot':75},
    'BANKNIFTY': {'type':'index','lot':30},
    'SENSEX':    {'type':'index','lot':10},
    'FINNIFTY':  {'type':'index','lot':65},
    'MIDCPNIFTY':{'type':'index','lot':120},
    'CRUDEOIL':  {'type':'commodity','lot':100},
    'GOLDM':     {'type':'commodity','lot':10},
    'SILVERM':   {'type':'commodity','lot':30},"""
open('v30_train_all.py','w').write(content.replace(old,new))
print("Fixed!")
