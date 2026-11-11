import uuid

from src.mandate_verification import (
    MandateVerifier,
    MandateVerificationError
)
from src.mandate_store import (
    MandateStore,
    MandateStoreError
)
from src.trusted_agent_registry import (
    load_trusted_public_keys,
    TrustedAgentRegistryError
)


class MandateServiceError(Exception):
    pass


class MandateService:

    def __init__(
        self,
        trusted_public_keys=None,
        store=None,
        registry_path=None
    ):
        if trusted_public_keys is None:
            try:
                if registry_path is None:
                    trusted_public_keys = load_trusted_public_keys()
                else:
                    trusted_public_keys = load_trusted_public_keys(
                        registry_path
                    )
            except TrustedAgentRegistryError as exc:
                raise MandateServiceError(
                    f"Trusted-agent registry error: {exc}"
                ) from exc

        if not isinstance(trusted_public_keys, dict):
            raise MandateServiceError(
                "Trusted public keys must be a dictionary"
            )

        self.trusted_public_keys = trusted_public_keys
        self.store = store or MandateStore()

    def reserve_order(self, mandate, signature, order):
        if not isinstance(mandate, dict):
            raise MandateServiceError("Invalid mandate")

        agent_id = mandate.get("agent_id")
        mandate_id = mandate.get("mandate_id")

        if not agent_id or not mandate_id:
            raise MandateServiceError(
                "Missing agent or mandate identity"
            )

        public_key = self.trusted_public_keys.get(agent_id)

        if not public_key:
            raise MandateServiceError(
                "Agent public key is not trusted"
            )

        try:
            verifier = MandateVerifier()

            verification = verifier.verify(
                mandate,
                signature,
                public_key,
                order
            )

            self.store.register_mandate(mandate)

            reservation_id = str(uuid.uuid4())

            self.store.reserve(
                mandate_id=mandate_id,
                nonce=mandate["nonce"],
                amount=verification["authorized_amount"],
                reservation_id=reservation_id
            )

            state = self.store.get_mandate_state(mandate_id)

            remaining_transactions = (
                state["max_transactions"]
                - state["transactions_used"]
            )

            remaining_spending = (
                state["max_spending_minor"]
                - state["spending_used_minor"]
            ) / 100

            return {
                "valid": True,
                "agent_id": agent_id,
                "mandate_id": mandate_id,
                "reservation_id": reservation_id,
                "authorized_amount": verification[
                    "authorized_amount"
                ],
                "remaining_transactions": remaining_transactions,
                "remaining_spending": remaining_spending,
                "status": "RESERVED"
            }

        except (
            MandateVerificationError,
            MandateStoreError
        ) as exc:
            raise MandateServiceError(str(exc)) from exc

    def complete_reservation(self, reservation_id):
        try:
            self.store.complete(reservation_id)
            return {
                "reservation_id": reservation_id,
                "status": "COMPLETED"
            }
        except MandateStoreError as exc:
            raise MandateServiceError(str(exc)) from exc

    def release_reservation(self, reservation_id):
        try:
            self.store.release(reservation_id)
            return {
                "reservation_id": reservation_id,
                "status": "RELEASED"
            }
        except MandateStoreError as exc:
            raise MandateServiceError(str(exc)) from exc
