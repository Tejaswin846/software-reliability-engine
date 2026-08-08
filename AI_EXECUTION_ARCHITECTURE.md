# Reliability-First AI Execution and Risk-Adaptive Verification v2

Software uses a proposal-first execution architecture. Model output cannot
directly trigger an important external action.

## Control Flow

```text
Authenticated request
  -> Intent classifier
  -> JSON planner
  -> Normalized evidence collector
  -> Deterministic verification
  -> Current action + cumulative workflow risk
  -> Evidence strength + uncertainty
  -> Policy, history, and token-cost ceiling
  -> Code / small model / frontier model / human gate
  -> ALLOW / RETRY / BLOCK / REVIEW
  -> Execution engine
  -> Post-action verification
  -> Append-only audit
```

Each stage is separately recorded with the same `request_id` and `user_id`.

## Intent Contract

Supported intents:

```text
answer_question
summarize
search_data
create_workflow
send_email
create_calendar_event
modify_database
delete_data
external_tool_action
```

The planner returns:

```json
{
  "intent": "send_email",
  "risk_level": "high_risk",
  "proposed_actions": [],
  "required_tools": [],
  "missing_info": [],
  "requires_user_confirmation": true
}
```

No action executes during planning or validation.

## Risk Policy

Low risk:

- answer, summarize, explain, rewrite, classify

Medium risk:

- memory search
- file or database query after a real source is supplied
- report generation
- internal workflow preparation
- draft creation

High risk:

- sending email or messages
- calendar creation
- database writes and deletes
- publishing
- side-effecting external tools
- workflows that affect external systems

## Validation

The rule validator checks:

- planner contract fields
- authenticated `user_id`
- missing action information
- connected target app
- email recipient
- calendar date/time
- required tool permission
- secret exposure
- destructive-action confirmation contract

Secret-like input is rejected. Audit records and Sentry context are redacted.

## Verification

Verification uses actual system state:

- Qdrant supplies memory evidence only
- Supabase or a connected database app proves database availability
- the authenticated connected-app session proves app and tool availability
- Redis proves temporary request state

Qdrant data never authorizes an action.

Risk-Adaptive Verification adds the following deterministic checks before any
model-based verifier is considered:

- schema and required fields
- tool failures, exceptions, timeouts, authentication, and authorization
- read/write/execute/send/delete/pay/privilege action classification
- unknown and unexpected tools
- duplicate non-idempotent actions and retry ceilings
- expected versus observed state transitions
- required independent evidence after a side effect
- false-success contradictions between agent claims and tool/state evidence

Unknown actions and tools start at elevated risk. Thresholds use risk bands and
a hysteresis margin so a one-point score change cannot suddenly choose a much
weaker verifier.

## Cumulative Workflow Risk

Every authenticated workflow has a compact durable state containing:

```text
sensitive data classes
external side effects
irreversible actions
retry and failure history
privilege level
financial exposure
policy violations
verification token spend
semantic-audit calibration history
```

The next action is scored against both its local consequence and this retained
context. Raw evidence is stored separately from the trusted summary and remains
authoritative. Contradictions and anomalies cause the decision record to expose
the raw evidence references needed to reconstruct context.

## Evidence and Verifier Routing

Evidence strength is independent from both action risk and model confidence.
Tool identifiers, state read-back, external confirmation, and independent
sources strengthen evidence. Agent claims, copied confidence values, and model
approval without traceable support do not.

```text
Level A  low risk + sufficient evidence       deterministic code
Level B  limited consequence + uncertainty    small semantic verifier
Level C  high uncertainty/consequence          frontier verifier
Level S  critical or irreversible              human gate / strong verification
```

The evaluation API is provider-neutral. A model verifier supplies a normalized
`decision` evidence event with supporting evidence ids, then re-evaluates the
step. Human approval satisfies any lower verifier floor. If no required model
verifier is connected, the safe result is `REVIEW`.

## Token Cost Ceiling

Each decision records original workflow tokens, verification tokens spent,
remaining budget, expected next-verifier cost, retry cost, and normal,
escalation, and emergency reserves. The Token Engine controls spending only
after the safety level is known. Insufficient budget returns `REVIEW` or
`BLOCK`; it never silently lowers the required verification level.

## Selective Semantic Audits

Level-A `ALLOW` decisions are deterministically sampled using an adaptive rate.
The rate is bounded by policy and increases when audits discover hidden errors.
Mandatory high-risk verification is never replaced by sampling.

Audit outcomes are submitted through the authenticated audit endpoint as
`passed`, `hidden_error`, `false_positive`, or `false_negative`.

## Metrics

`GET /api/ai/verification/metrics` exposes:

- verification overhead
- net token saving
- false-positive and false-negative rates
- audit discovery rate
- escalation rate
- decision latency
- token cost per prevented failure
- reliability gain per verification token

## Confirmation

High-risk validation returns:

```json
{
  "confirmation_required": true,
  "confirmation_card": {
    "title": "Review before running",
    "action": "Run the proposed send email action.",
    "target_app": "gmail",
    "recipient_or_target": "person@example.com",
    "data_affected": "External communication",
    "possible_risk": "This action can change data or communicate outside Software."
  }
}
```

The global frontend loader displays Confirm and Cancel buttons. Confirm calls
`POST /api/ai/confirm`, then executes the same request. Cancel records the
decision without running the action.

## API Example

Plan:

```bash
curl -X POST https://YOUR_URL/api/ai/plan \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION" \
  -d '{
    "request": "Send email to person@example.com",
    "action": {
      "subject": "Reliability report",
      "body": "The report is ready."
    }
  }'
```

Validate:

```bash
curl -X POST https://YOUR_URL/api/ai/validate \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION" \
  -d '{"request_id":"air_..."}'
```

Execute low/medium risk:

```bash
curl -X POST https://YOUR_URL/api/ai/execute \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION" \
  -d '{"request_id":"air_..."}'
```

High-risk execution returns `409` until the authenticated user confirms.

## Audit Storage

Tables:

```text
ai_execution_requests
ai_execution_audit_events
risk_verification_workflows
risk_verification_evidence
risk_verification_decisions
risk_verification_audits
```

The request row stores the latest safe snapshot. Audit events append each
request, intent, risk, plan, validation, verification, confirmation, and
execution transition.

Redis stores the same request state temporarily for fast gating and distributed
locking. SQLite remains the durable fallback and audit source.
