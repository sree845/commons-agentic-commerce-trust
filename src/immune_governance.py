"""Explicit candidate approval, checksum verification, activation and rollback."""
import argparse, hashlib, json, shutil, time
from pathlib import Path
import joblib
ROOT=Path(__file__).resolve().parents[1]
MODELS=ROOT/'models'; REG=MODELS/'immune_model_versions.json'; REPORT=ROOT/'data/processed/immune_evaluation_report.json'; CAND=MODELS/'immune_candidate_model.joblib'; HISTORY=MODELS/'immune_governance_history.json'

def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''): h.update(chunk)
    return h.hexdigest()
def read_json(p): return json.loads(p.read_text(encoding='utf-8'))
def write_json(p,obj):
    tmp=p.with_suffix('.tmp'); tmp.write_text(json.dumps(obj,indent=2),encoding='utf-8'); tmp.replace(p)
def promote(approver):
    if not approver.strip(): raise ValueError('A named human approver is required.')
    report=read_json(REPORT)
    if not report.get('validation',{}).get('safety_gate_passed'): raise ValueError('Candidate did not pass the validation safety gate.')
    if not CAND.exists(): raise FileNotFoundError('Candidate model artifact not found.')
    package=joblib.load(CAND)
    required={'model','scaler','features','thresholds'}
    if not required.issubset(package): raise ValueError('Candidate package schema invalid.')
    if len(package['features']) != 9: raise ValueError('Candidate feature schema invalid.')
    reg=read_json(REG); old=reg['active_version']; version=f"immune_{int(time.time())}"
    target=MODELS/f'{version}.joblib'; shutil.copy2(CAND,target)
    versions=reg.setdefault('versions',{})
    versions[old]['status']='previous_version'
    versions[version]={'path':str(target.relative_to(ROOT)),'status':'active','sha256':digest(target),'approved_by':approver,'approved_at':int(time.time()),'source':'synthetic adaptation candidate; validation gate passed'}
    reg['active_version']=version; write_json(REG,reg)
    history=read_json(HISTORY) if HISTORY.exists() else {'events':[]}
    history['events'].append({'action':'PROMOTE','from':old,'to':version,'approver':approver,'sha256':digest(target),'at':int(time.time())}); write_json(HISTORY,history)
    return {'active_version':version,'previous_version':old,'sha256':digest(target)}
def rollback(approver, version=None):
    if not approver.strip(): raise ValueError('A named human approver is required.')
    reg=read_json(REG); old=reg['active_version']; choices=[k for k,v in reg['versions'].items() if v.get('status')=='previous_version']
    target_version=version or (choices[-1] if choices else None)
    if not target_version or target_version not in reg['versions']: raise ValueError('No valid rollback target.')
    info=reg['versions'][target_version]; path=ROOT/Path(info['path'].replace('\\','/'))
    if not path.exists(): raise FileNotFoundError('Rollback artifact missing.')
    if info.get('sha256') and digest(path)!=info['sha256']: raise ValueError('Rollback artifact checksum mismatch.')
    package=joblib.load(path)
    if not {'model','scaler','features','thresholds'}.issubset(package): raise ValueError('Rollback package invalid.')
    reg['versions'][old]['status']='rolled_back'; reg['versions'][target_version]['status']='active'; reg['active_version']=target_version; write_json(REG,reg)
    history=read_json(HISTORY) if HISTORY.exists() else {'events':[]}
    history['events'].append({'action':'ROLLBACK','from':old,'to':target_version,'approver':approver,'sha256':digest(path),'at':int(time.time())}); write_json(HISTORY,history)
    return {'active_version':target_version,'rolled_back_from':old,'sha256':digest(path)}
if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['promote','rollback']); p.add_argument('--approver',required=True); p.add_argument('--version'); a=p.parse_args()
    print(json.dumps(promote(a.approver) if a.action=='promote' else rollback(a.approver,a.version),indent=2))
