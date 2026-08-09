# Durable execution control plane

Matrixs uses a formal execution state machine for every AI action:

`RECEIVED -> PLANNED -> EVIDENCE_REQUIRED -> VERIFYING -> ALLOW | RETRY | REVIEW | BLOCK`

Authorized actions continue through:

`AUTHORIZED -> EXECUTION_LEASED -> EXECUTING -> POST_VERIFYING -> VERIFIED -> COMPLETED`

Failures are moved to `COMPENSATING` or `ESCALATED`; cancellation is monotonic and
invalidates every older worker lease.

## Guarantees

- Every state change appends an immutable ledger record and a transactional outbox event.
- Idempotency keys are transactionally reserved before an external action starts.
- Every lease has a monotonically increasing fencing token.
- Cancellation increments an epoch; stale workers cannot commit a result afterward.
- Completed actions store a provider-aware receipt and request/result fingerprints.
- Outbox jobs use explicit leases, ACKs, retries, and a dead-letter state.
- Worker heartbeats let a watchdog identify stale workers.
- Supabase tables use RLS, deny `anon` and `authenticated`, and permit only the
  server-held `service_role` credential.

## Production migration

1. Correct and verify `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` on Render.
   For read redundancy, also configure the official
   `SUPABASE_LOAD_BALANCER_URL` and `SUPABASE_READ_REPLICA_URL` endpoints.
2. Run `supabase_schema.sql` in the Supabase SQL editor.
3. Run `supabase_execution_control.sql` and confirm every verification row reports
   `rls_enabled = true`.
4. Run the Supabase security and performance advisors.
5. Set `SOFTWARE_EXECUTION_CONTROL_SUPABASE_READY=true` on Render and redeploy.
6. Exercise a low-risk action, a reviewed high-risk action, cancellation, replay,
   and a failed outbox delivery before enabling broad traffic.

Until step 5, `auto` uses the SQLite adapter so local development and the existing
deployment remain compatible. Explicitly selecting `supabase` is fail-closed: the
application will not silently downgrade when the durable backend is unavailable.
