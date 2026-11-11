import base64
import binascii
import json
from pathlib import Path


class TrustedAgentRegistryError(Exception):
    """Raised when the trusted-agent registry is invalid."""


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REGISTRY_PATH = ROOT / "config" / "trusted_agents.json"


def load_trusted_public_keys(registry_path=DEFAULT_REGISTRY_PATH):
    """
    Load active agents and their Ed25519 public keys.

    Returns:
        dict: {agent_id: base64_encoded_public_key}

    Only ACTIVE agents are returned. REVOKED agents are validated
    but excluded from the trusted-key dictionary.
    """
    path = Path(registry_path)

    try:
        with path.open("r", encoding="utf-8-sig") as file:
            registry = json.load(file)
    except FileNotFoundError as exc:
        raise TrustedAgentRegistryError(
            f"Registry file not found: {path}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise TrustedAgentRegistryError(
            "Registry contains invalid JSON."
        ) from exc
    except OSError as exc:
        raise TrustedAgentRegistryError(
            "Could not read the trusted-agent registry."
        ) from exc

    if not isinstance(registry, dict):
        raise TrustedAgentRegistryError(
            "Registry root must be a JSON object."
        )

    if registry.get("version") != 1:
        raise TrustedAgentRegistryError(
            "Unsupported or missing registry version."
        )

    agents = registry.get("agents")

    if not isinstance(agents, list):
        raise TrustedAgentRegistryError(
            "'agents' must be a list."
        )

    trusted_keys = {}
    seen_agent_ids = set()

    for index, agent in enumerate(agents):
        if not isinstance(agent, dict):
            raise TrustedAgentRegistryError(
                f"Agent entry {index} must be an object."
            )

        agent_id = agent.get("agent_id")
        public_key = agent.get("public_key")
        status = agent.get("status")

        if not isinstance(agent_id, str) or not agent_id.strip():
            raise TrustedAgentRegistryError(
                f"Agent entry {index} has an invalid agent_id."
            )

        agent_id = agent_id.strip()

        if agent_id in seen_agent_ids:
            raise TrustedAgentRegistryError(
                f"Duplicate agent_id: {agent_id}"
            )

        seen_agent_ids.add(agent_id)

        if not isinstance(public_key, str) or not public_key:
            raise TrustedAgentRegistryError(
                f"Agent {agent_id} has an invalid public_key."
            )

        try:
            decoded_key = base64.b64decode(
                public_key,
                validate=True
            )
        except (binascii.Error, ValueError) as exc:
            raise TrustedAgentRegistryError(
                f"Agent {agent_id} has an invalid Base64 public key."
            ) from exc

        if len(decoded_key) != 32:
            raise TrustedAgentRegistryError(
                f"Agent {agent_id} public key must be 32 bytes."
            )

        if status not in ("ACTIVE", "REVOKED"):
            raise TrustedAgentRegistryError(
                f"Agent {agent_id} has an unsupported status."
            )

        if status == "ACTIVE":
            trusted_keys[agent_id] = public_key

    return trusted_keys
