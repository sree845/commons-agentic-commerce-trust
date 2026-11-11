"""Explicit coordinator-model promotion into the live Commons RiskEngine registry."""
import argparse, hashlib, json, shutil, time
from pathlib import Path
import joblib
ROOT=Path(__file__).resolve().parents[2]; MODELS=ROOT/'models'; REG=MODELS/'immune_model_versions.json'
def sha(path):
 h=hashlib.sha256();
 with path.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()
def promote(version, approver):
 if not approver.strip(): raise ValueError('Named human approver required.')
 state=json.loads((ROOT/'data/federation_network/coordinator_state.json').read_text())
 matches=[r for r in state['rounds'].values() if r.get('model_version')==version and r.get('status')=='aggregated']
 if not matches: raise ValueError('No completed federated round for this version.')
 source=MODELS/f'{version}.joblib'
 package=joblib.load(source)
 if package.get('features') != ["amount","mandate_cap","category_allowed","mandate_age_days","orders_per_hour","address_changed","payment_retries","amount_vs_merchant_norm","shared_agent_flag_count"]: raise ValueError('Federated model feature schema mismatch.')
 thresholds=package.get('thresholds',{})
 if not 0 <= thresholds.get('capture_below',-1) < thresholds.get('void_at_or_above',0) <= 1: raise ValueError('Decision thresholds invalid.')
 reg=json.loads(REG.read_text()); previous=reg['active_version']; target=MODELS/f'{version}.joblib'
 reg.setdefault('versions',{})[previous]['status']='previous_version'
 reg['versions'][version]={'path':f'models/{version}.joblib','status':'active','sha256':sha(source),'approved_by':approver,'approved_at':int(time.time()),'federation_round':matches[0]}
 reg['active_version']=version; tmp=REG.with_suffix('.tmp'); tmp.write_text(json.dumps(reg,indent=2)); tmp.replace(REG)
 return {'active_version':version,'previous_version':previous,'sha256':sha(source)}
if __name__=='__main__':
 p=argparse.ArgumentParser(); p.add_argument('--version',required=True); p.add_argument('--approver',required=True); a=p.parse_args(); print(json.dumps(promote(a.version,a.approver),indent=2))
