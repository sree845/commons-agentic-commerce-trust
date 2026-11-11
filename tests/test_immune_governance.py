import json
import pytest
from src import immune_governance as g

def test_promotion_requires_approval_and_passed_gate(tmp_path,monkeypatch):
    models=tmp_path/'models'; models.mkdir(); data=tmp_path/'data'/'processed'; data.mkdir(parents=True)
    reg=models/'immune_model_versions.json'; cand=models/'immune_candidate_model.joblib'; report=data/'immune_evaluation_report.json'
    import joblib
    from sklearn.linear_model import LogisticRegression
    import numpy as np
    m=LogisticRegression(); m.classes_=np.array([0,1]); m.coef_=np.zeros((1,9)); m.intercept_=np.zeros(1); m.n_features_in_=9
    joblib.dump({'model':m,'scaler':object(),'features':[str(i) for i in range(9)],'thresholds':{'capture_below':.3,'void_at_or_above':.8}},cand)
    joblib.dump({'model':m,'scaler':object(),'features':[str(i) for i in range(9)],'thresholds':{'capture_below':.3,'void_at_or_above':.8}},models/'base.joblib')
    reg.write_text(json.dumps({'active_version':'base','versions':{'base':{'path':'models/base.joblib','status':'active'}}}))
    report.write_text(json.dumps({'validation':{'safety_gate_passed':True}}))
    monkeypatch.setattr(g,'ROOT',tmp_path); monkeypatch.setattr(g,'MODELS',models); monkeypatch.setattr(g,'REG',reg); monkeypatch.setattr(g,'REPORT',report); monkeypatch.setattr(g,'CAND',cand); monkeypatch.setattr(g,'HISTORY',models/'history.json')
    with pytest.raises(ValueError): g.promote(' ')
    result=g.promote('independent-reviewer')
    assert result['previous_version']=='base'
    assert json.loads(reg.read_text())['active_version']==result['active_version']
