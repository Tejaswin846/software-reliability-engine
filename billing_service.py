"""Provider-neutral Matrixs plan and billing helpers.

The web/API layer owns persistence.  This module deliberately contains no
Stripe calls so another provider can be added without changing plan rules or
the billing UI contract.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def build_plan_definitions(
    *,
    stripe_developer_price_id: str = "",
    stripe_pro_price_id: str = "",
    stripe_business_price_id: str = "",
    stripe_enterprise_price_id: str = "",
) -> list[Dict[str, Any]]:
    common = {
        "advanced_guardrails": False,
        "human_intervention_history": False,
        "api_access": True,
        "export_capability": False,
    }
    return [
        {
            "id": "free", "name": "Free", "price": "₹0", "monthly_price": 0,
            "max_projects": 1, "max_api_keys": 1, "monthly_workflow_limit": 1_000,
            "monthly_telemetry_limit": 5_000, "max_team_members": 1,
            "retention_days": 7, "max_installations": 1,
            "features": {**common}, "audience": "Try Matrixs with one project",
            "stripe_price_id": None,
        },
        {
            "id": "developer", "name": "Developer", "price": "Configurable", "monthly_price": None,
            "max_projects": 3, "max_api_keys": 5, "monthly_workflow_limit": 5_000,
            "monthly_telemetry_limit": 10_000, "max_team_members": 1,
            "retention_days": 14, "max_installations": 3,
            "features": {**common, "export_capability": True},
            "audience": "Independent builders", "stripe_price_id": stripe_developer_price_id or None,
        },
        {
            "id": "pro", "name": "Pro", "price": "Configurable", "monthly_price": None,
            "max_projects": 20, "max_api_keys": 50, "monthly_workflow_limit": 100_000,
            "monthly_telemetry_limit": 500_000, "max_team_members": 10,
            "retention_days": 90, "max_installations": 50,
            "features": {**common, "advanced_guardrails": True, "human_intervention_history": True, "export_capability": True},
            "audience": "Production teams", "stripe_price_id": stripe_pro_price_id or None,
        },
        {
            "id": "business", "name": "Business", "price": "Configurable", "monthly_price": None,
            "max_projects": 100, "max_api_keys": 250, "monthly_workflow_limit": 1_000_000,
            "monthly_telemetry_limit": 5_000_000, "max_team_members": 50,
            "retention_days": 365, "max_installations": 250,
            "features": {**common, "advanced_guardrails": True, "human_intervention_history": True, "export_capability": True},
            "audience": "Growing organizations", "stripe_price_id": stripe_business_price_id or None,
        },
        {
            "id": "enterprise", "name": "Enterprise", "price": "Contact sales", "monthly_price": None,
            "max_projects": None, "max_api_keys": None, "monthly_workflow_limit": None,
            "monthly_telemetry_limit": None, "max_team_members": None,
            "retention_days": None, "max_installations": None,
            "features": {**common, "advanced_guardrails": True, "human_intervention_history": True, "export_capability": True},
            "audience": "Large organizations", "stripe_price_id": stripe_enterprise_price_id or None,
        },
    ]


def remaining(limit: Optional[int], used: int) -> Optional[int]:
    return None if limit is None else max(0, int(limit) - int(used))


def limit_message(plan: Dict[str, Any], resource: str) -> str:
    labels = {
        "projects": ("projects", "create another project"),
        "api_keys": ("API keys", "create another API key"),
        "workflows": ("monthly workflows", "record another workflow"),
        "telemetry_events": ("monthly telemetry events", "record more telemetry"),
        "installations": ("connected installations", "connect another installation"),
        "team_members": ("team members", "add another team member"),
    }
    label, action = labels[resource]
    limit_key = {
        "projects": "max_projects", "api_keys": "max_api_keys",
        "workflows": "monthly_workflow_limit", "telemetry_events": "monthly_telemetry_limit",
        "installations": "max_installations", "team_members": "max_team_members",
    }[resource]
    limit = plan.get(limit_key)
    if resource == "workflows":
        return "Monthly workflow limit reached. Upgrade your plan to continue."
    return f"Your current {plan['name']} plan supports {limit} {label}. Upgrade to {action}."
