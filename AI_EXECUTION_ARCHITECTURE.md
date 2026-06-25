# Reliability-First AI Execution

Software uses a proposal-first execution architecture. Model output cannot
directly trigger an important external action.

## Control Flow

```text
Authenticated request
  -> Intent classifier
  -> Risk detector
  -> JSON planner
  -> Rule validator
  -> Tool and data verifier
  -> Human confirmation when required
  -> Execution engine
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
```

The request row stores the latest safe snapshot. Audit events append each
request, intent, risk, plan, validation, verification, confirmation, and
execution transition.

Redis stores the same request state temporarily for fast gating and distributed
locking. SQLite remains the durable fallback and audit source.
