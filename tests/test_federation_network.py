import hashlib, hmac, json, os, time
import numpy as np
import pytest
from fastapi.testclient import TestClient
from src.federation_network import service

@pytest.fixture
def client(tmp_path, monkeypatch):
    secret='merchant-a-secret-material-32bytes-minimum'
    monkeypatch.setenv('COMMONS_MERCHANT_SECRETS', json.dumps({'merchant-a':secret,'merchant-b':'merchant-b-secret-material-32bytes-minimum'}))
    monkeypatch.setattr(service,'STATE_FILE',tmp_path/'state.json')
    monkeypatch.setattr(service,'MODEL_FILE',tmp_path/'base.joblib')
    monkeypatch.setattr(service,'MODEL_DIR',tmp_path)
    import joblib
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler
    scaler=StandardScaler().fit(np.zeros((2,9)))
    model=LogisticRegression(); model.classes_=np.array([0,1]); model.coef_=np.zeros((1,9)); model.intercept_=np.zeros(1); model.n_features_in_=9
    joblib.dump({'model':model,'scaler':scaler,'features':service.FEATURES,'thresholds':{'capture_below':.3,'void_at_or_above':.8}},tmp_path/'base.joblib')
    return TestClient(service.app),secret

def test_signed_updates_aggregate_only_after_all_merchants(client):
    c,secret=client
    r=c.post('/v1/rounds',json={'round_id':'round-0001','expected_merchants':['merchant-a','merchant-b'],'feature_schema':service.FEATURES,'base_model_version':'federated_v1'})
    assert r.status_code==200
    def submit(mid,sec,value,nonce):
        body={'round_id':'round-0001','merchant_id':mid,'sample_count':10,'feature_schema':service.FEATURES,'base_model_version':'federated_v1','coefficients':[[value]*9],'intercept':[value],'nonce':nonce,'created_at':int(time.time())}
        raw=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        sig=hmac.new(sec.encode(),raw,hashlib.sha256).hexdigest()
        return c.post('/v1/updates',json=body,headers={'X-Commons-Signature':sig})
    first=submit('merchant-a',secret,1,'nonce-merchant-a-0001'); assert first.status_code==200, first.text; assert first.json()['status']=='collecting'
    assert submit('merchant-b','merchant-b-secret-material-32bytes-minimum',3,'nonce-merchant-b-0001').json()['status']=='aggregated'
    status=c.get('/v1/rounds/round-0001').json()
    assert status['participants_received']==['merchant-a','merchant-b']
    assert status['total_samples']==20

def test_invalid_signature_rejected(client):
    c,_=client
    c.post('/v1/rounds',json={'round_id':'round-0002','expected_merchants':['merchant-a','merchant-b'],'feature_schema':service.FEATURES,'base_model_version':'federated_v1'})
    body={'round_id':'round-0002','merchant_id':'merchant-a','sample_count':10,'feature_schema':service.FEATURES,'base_model_version':'federated_v1','coefficients':[[0]*9],'intercept':[0],'nonce':'nonce-merchant-a-0002','created_at':int(time.time())}
    assert c.post('/v1/updates',json=body,headers={'X-Commons-Signature':'bad'}).status_code==401
