"""Constants for the Willo integration.

Willo never reaches this Home Assistant instance from the outside — this
integration opens the ONLY connection, outbound, to Willo's backend, and
keeps it open. See __init__.py's module doc comment for the full design.
"""

DOMAIN = "willo"

CONF_HOME_ID = "home_id"
CONF_SECRET = "secret"

# Overridable per-entry (an advanced/self-hosted-backend option), but the
# defaults are Willo's own production hosts — a person pairing a fresh
# Home Assistant Green never needs to know either exists.
DEFAULT_PAIR_URL = "https://api.willo.sh/tunnel/pair"
# Device-initiated claim flow (Willo Local) — the orchestrator, not this
# integration, calls these; see OxyHQ/willo-ha's orchestrator/ package.
DEFAULT_CLAIM_URL = "https://api.willo.sh/tunnel/claim"
DEFAULT_CLAIM_STATUS_URL = "https://api.willo.sh/tunnel/claim/status"
# TEMPORARY: tunnel.willo.sh (its own dedicated load balancer, needed for a
# long idle timeout on these long-lived connections — see OxyHQ/oxy-infra's
# app-relay.tf for the pattern) doesn't exist yet. api.willo.sh's /tunnel
# namespace is the SAME backend process and works today; switch this back
# once the dedicated ALB is built.
DEFAULT_TUNNEL_URL = "https://api.willo.sh"

TUNNEL_NAMESPACE = "/tunnel"
