"""Small integration helper: call only after MandateService.reserve_order succeeds."""
from pathlib import Path
from src.verified_mandate_terms import VerifiedMandateTermsStore

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = ROOT / "data" / "commons_state.db"


def persist_verified_terms(mandate, db_path=DEFAULT_DB):
    """Persist terms only after Ed25519 verification has succeeded."""
    VerifiedMandateTermsStore(db_path).save_verified(mandate)
