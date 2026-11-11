"""Explicitly synthetic demonstration data. Never represents real PayPal activity."""
from datetime import datetime, timezone
SCENARIOS = [
 {'id':'legitimate','name':'Authorized everyday purchase','attack_family':'none','merchant':'Merchant A · Electronics','amount':3499,'risk':0.08,'decision':'CAPTURE','reasons':['Within signed spending limit','Permitted product category','Normal order velocity'],'mandate':'VALID'},
 {'id':'overspend','name':'Mandate spending limit exceeded','attack_family':'authority_violation','merchant':'Merchant A · Electronics','amount':8999,'risk':0.91,'decision':'VOID','reasons':['Order exceeds mandate cap','Authority violation is independent of model score'],'mandate':'INVALID_LIMIT'},
 {'id':'velocity','name':'Coordinated high-velocity agent','attack_family':'velocity_attack','merchant':'Merchant B · Fashion','amount':2499,'risk':0.76,'decision':'HOLD','reasons':['Unusually high order velocity','Cross-merchant pattern requires review'],'mandate':'VALID'},
 {'id':'address','name':'Unexpected shipping address change','attack_family':'address_manipulation','merchant':'Merchant C · Home goods','amount':4299,'risk':0.68,'decision':'HOLD','reasons':['Shipping address differs from trusted profile','Review before capture'],'mandate':'VALID'},
 {'id':'category','name':'Unauthorized product category','attack_family':'authority_violation','merchant':'Merchant B · Fashion','amount':1999,'risk':0.95,'decision':'VOID','reasons':['Requested category is outside signed mandate'],'mandate':'INVALID_CATEGORY'},
 {'id':'false_decline','name':'Legitimate order initially flagged','attack_family':'false_decline','merchant':'Merchant C · Home goods','amount':1599,'risk':0.58,'decision':'HOLD','reasons':['Borderline behavioural score','Eligible for correction and appeal'],'mandate':'VALID'}
]
def overview():
    return {'mode':'SIMULATION','merchant_count':3,'total_orders':len(SCENARIOS),'decisions':{k:sum(x['decision']==k for x in SCENARIOS) for k in ('CAPTURE','HOLD','VOID')},'average_risk':round(sum(x['risk'] for x in SCENARIOS)/len(SCENARIOS),3),'merchants':[{'name':'Merchant A','sector':'Electronics','orders':2},{'name':'Merchant B','sector':'Fashion','orders':2},{'name':'Merchant C','sector':'Home goods','orders':2}]}
