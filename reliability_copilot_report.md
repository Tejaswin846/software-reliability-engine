# Reliability Copilot Report

Generated: 2026-06-21

## Goal

Move Software from monitoring and recovery to optimization and guidance.

## What Reliability Copilot Analyzes

The Copilot reads measured reliability data from:

- workflow failures
- SDK error events
- automatic recovery events
- guardrail events
- model benchmark performance
- external tool benchmark performance

## Recommendation Types

The system can recommend:

- switch model
- change provider
- add retry
- increase timeout
- use backup extractor
- use backup search provider
- move guardrail checks earlier
- collect more data when no urgent weakness is visible

## Recommendation Fields

Every recommendation includes:

- issue
- recommendation
- category
- confidence
- estimated success improvement
- supporting evidence

## Database

Created:

```text
recommendations
```

Tracked fields:

- scope
- user_id
- project_id
- category
- issue
- recommendation
- confidence
- estimated_success_improvement
- supporting_evidence_json
- status
- source
- created_at
- updated_at

## API

Created:

```text
GET /api/copilot/recommendations
GET /api/copilot/summary
```

The dashboard payload also includes:

```text
copilot.summary
copilot.recommendations
```

## Dashboard

Added:

```text
Reliability Copilot Panel
```

The panel displays:

- recommendations count
- average confidence
- total estimated improvement
- issue
- recommendation
- expected improvement
- confidence
- supporting evidence

## Current Behavior

The Copilot is deterministic and explainable. It does not call an LLM yet.

For this phase, "intelligent recommendations" means:

1. inspect reliability data
2. identify weak points
3. produce ranked recommendations
4. store recommendations in SQLite
5. show recommendations in the dashboard and API

The next production step is adding recommendation acceptance workflows so teams can mark actions as accepted, rejected, implemented, or measured.
