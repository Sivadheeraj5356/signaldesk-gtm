# Tenant provider connections - design (not yet implemented)

Goal: every workspace connects its OWN Gmail/Cal.com account. The operator env
tokens are an owner-workspace development path only and are already refused for
tenant workspaces (senders.provider_state / bookers.provider_state take ws).

## Data model (per-tenant schema, existing isolation)

`connections` table (id, data): {provider: gmail|calcom, identity: verified
email/account id, scopes: [], access_token_ref, refresh_token_ref, expires_at,
status: active|expired|revoked, connected_at, updated_at}

Tokens are never stored in the accounts/outreach tables, never logged, never
returned by /api/state (state exposes identity + status only). Storage target:
encrypted-at-rest column or an external secret store; plaintext in the tenant
schema is the fallback only behind TLS + isolation, documented as a limitation.

## Connect flow (OAuth, durable - replaces static env token)

1. Workspace owner clicks Connect Gmail -> GET /api/connect/gmail/start
   - requires authenticated session + CSRF
   - builds Google consent URL: scope gmail.send ONLY (sensitive scope),
     state = signed nonce bound to workspace + session, PKCE
2. Google consent -> GET /api/connect/gmail/callback
   - verifies state nonce + workspace binding, exchanges code for tokens
   - fetches gmail profile -> verified identity stored on the connection
   - refresh_token stored; access_token cached with expiry
3. Send path uses connection.access_token, refreshing via refresh_token when
   expired (google token endpoint). Failure marks connection status=expired
   and sends refuse until reconnected. Reconnect repeats step 1.
4. Disconnect: token revoked at Google, connection row deleted.

Approval binding: campaign send_approval.sender must EQUAL the connection's
verified identity (checked at approval time and again at send time).

## Google verification requirements (researched 2026-10-22)

gmail.send is a SENSITIVE scope: before public/self-serve use, the OAuth app
needs Google verification - verified domain ownership, privacy policy URL,
branding, scope justification, demo video. Unverified apps are limited to 100
test users with an unverified-app warning screen. This is a launch prerequisite
for multi-tenant sending, not a code change. For the owner's own workspace and
testing, an unverified app in "testing" mode with the owner as a test user is
sufficient.
Sources: developers.google.com/workspace/gmail/api/auth/scopes,
developers.google.com/identity/protocols/oauth2/production-readiness/sensitive-scope-verification

## Cal.com (researched 2026-10-22)

- Auth: OAuth (recommended for integrations) or API keys (cal_ / cal_live_
  prefixes) from Settings > Security. Current contract uses the API-key shape.
- Endpoint version: official docs describe v2; bookers.py currently targets
  v1 URL shapes - must be reconciled against v2 before any live call (gap).
- Plan gating: some API surface sits in paid tiers (pricing page lists Custom
  APIs / Additional APIs / Enterprise API in premium plans; Teams endpoints
  need a Teams plan). Exact booking-creation cost tier is NOT verified -
  real booking stays fail-closed until the account's actual plan is known.
- Per-tenant: each tenant connects their own Cal.com account (OAuth client
  per Cal.com docs); the owner env key is dev-only like Gmail.
Sources: cal.com/docs/api-reference/v2/introduction, cal.com/pricing

## Booking authority gates before real bookings (fail-closed now)

- Invitee bound to member evidence (done), ISO start + IANA timezone (done)
- Remaining: verified event type ownership, slot availability confirmed
  against the live calendar at booking time, cost/terms acknowledgment for
  the plan tier, and campaign approval re-check at booking time.
