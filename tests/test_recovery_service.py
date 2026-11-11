import tempfile, unittest
from pathlib import Path
from src.recovery_service import RecoveryService
class RecoveryServiceTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.s=RecoveryService(Path(self.tmp.name)/'r.db')
 def tearDown(self): self.tmp.cleanup()
 def test_receipts_and_digest(self):
  r=self.s.create_recourse('tx1',['RISK_REVIEW'],[{'type':'confirm_address'}]); self.assertEqual(r['status'],'OPEN')
  e=self.s.create_evidence('tx1',{'decision':'HOLD'}); self.assertEqual(len(e['payload_sha256']),64); self.assertEqual(self.s.get_evidence(e['receipt_id'])['payload']['decision'],'HOLD')
 def test_appeal_lifecycle_and_duplicate(self):
  a=self.s.submit_appeal('tx1','The address is correct',{'proof':'uploaded'}); self.assertEqual(a['status'],'SUBMITTED')
  with self.assertRaises(ValueError): self.s.submit_appeal('tx1','Another appeal')
  done=self.s.review_appeal(a['appeal_id'],'OVERTURNED','Verified by reviewer'); self.assertEqual(done['status'],'OVERTURNED')

 def test_appeal_accepts_matching_evidence_receipt(self):
  e=self.s.create_evidence('tx1',{'decision':'HOLD'})
  a=self.s.submit_appeal('tx1','Please review this decision',{'evidence_receipt_id':e['receipt_id']})
  self.assertEqual(a['evidence']['evidence_receipt_id'],e['receipt_id'])

 def test_appeal_rejects_missing_evidence_receipt(self):
  with self.assertRaisesRegex(ValueError,'Evidence receipt not found'):
   self.s.submit_appeal('tx1','Please review this decision',{'evidence_receipt_id':'der_does_not_exist'})

 def test_appeal_rejects_evidence_from_another_transaction(self):
  e=self.s.create_evidence('tx_other',{'decision':'HOLD'})
  with self.assertRaisesRegex(ValueError,'different transaction'):
   self.s.submit_appeal('tx1','Please review this decision',{'evidence_receipt_id':e['receipt_id']})

if __name__=='__main__':unittest.main()
