from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import os
import socket
from collections.abc import Callable
from typing import Any, ClassVar
from urllib.parse import urlparse

import requests


class ReliabilityNotificationDispatcher:
    """Deliver incident notifications through server-configured destinations."""

    ENVIRONMENT_ENDPOINTS: ClassVar[dict[str, str]] = {
        "slack": "SOFTWARE_ALERT_SLACK_WEBHOOK_URL",
        "email": "SOFTWARE_ALERT_EMAIL_WEBHOOK_URL",
        "webhook": "SOFTWARE_ALERT_WEBHOOK_URL",
    }

    def __init__(
        self,
        *,
        scrub: Callable[[Any], Any] | None = None,
        timeout_seconds: float = 5,
    ) -> None:
        self.scrub = scrub or (lambda value: value)
        self.timeout_seconds = max(1.0, min(15.0, float(timeout_seconds)))

    @staticmethod
    def _destination(item: Any) -> tuple[str, str | None, dict[str, Any]]:
        if isinstance(item, str):
            return item.strip().lower(), None, {}
        if not isinstance(item, dict):
            return "unknown", None, {}
        destination_type = str(item.get("type") or "webhook").strip().lower()
        url = str(item.get("url") or "").strip() or None
        return destination_type, url, dict(item)

    @staticmethod
    def _safe_endpoint(url: str) -> bool:
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            return False
        try:
            addresses = socket.getaddrinfo(
                parsed.hostname, 443, type=socket.SOCK_STREAM
            )
        except OSError:
            return False
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address[4][0].split("%", 1)[0])
            except ValueError:
                return False
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
            ):
                return False
        return True

    def configuration_status(self) -> dict[str, Any]:
        destinations: dict[str, dict[str, Any]] = {
            "dashboard": {
                "configured": True,
                "endpoint_host": "matrixs-dashboard",
            }
        }
        for destination_type, environment_name in self.ENVIRONMENT_ENDPOINTS.items():
            endpoint = os.getenv(environment_name, "").strip()
            destinations[destination_type] = {
                "configured": bool(endpoint),
                "endpoint_host": urlparse(endpoint).hostname if endpoint else None,
                "https": urlparse(endpoint).scheme == "https" if endpoint else False,
            }
        token_configured = bool(os.getenv("SOFTWARE_ALERT_WEBHOOK_TOKEN", "").strip())
        return {
            "destinations": destinations,
            "external_delivery_ready": any(
                item["configured"] and item.get("https")
                for name, item in destinations.items()
                if name != "dashboard"
            ),
            "webhook_signing_configured": token_configured,
            "custom_webhooks_enabled": os.getenv(
                "SOFTWARE_ALERT_ALLOW_CUSTOM_WEBHOOKS", "false"
            ).lower()
            in {"1", "true", "yes", "on"},
            "timeout_seconds": self.timeout_seconds,
        }

    def deliver(
        self, destinations: list[Any], event: dict[str, Any]
    ) -> list[dict[str, Any]]:
        safe_event = self.scrub(event)
        deliveries: list[dict[str, Any]] = []
        allow_custom = os.getenv(
            "SOFTWARE_ALERT_ALLOW_CUSTOM_WEBHOOKS", "false"
        ).lower() in {"1", "true", "yes", "on"}
        for item in destinations:
            destination_type, custom_url, options = self._destination(item)
            if destination_type == "dashboard":
                deliveries.append(
                    {
                        "destination_type": "dashboard",
                        "destination_ref": "matrixs-dashboard",
                        "status": "delivered",
                        "response_code": None,
                        "error": None,
                    }
                )
                continue
            environment_name = self.ENVIRONMENT_ENDPOINTS.get(destination_type)
            endpoint = os.getenv(environment_name or "", "").strip()
            if custom_url and allow_custom:
                endpoint = custom_url
            if not endpoint:
                deliveries.append(
                    {
                        "destination_type": destination_type,
                        "destination_ref": environment_name,
                        "status": "skipped",
                        "response_code": None,
                        "error": "Destination is not configured.",
                    }
                )
                continue
            if not self._safe_endpoint(endpoint):
                deliveries.append(
                    {
                        "destination_type": destination_type,
                        "destination_ref": urlparse(endpoint).hostname,
                        "status": "failed",
                        "response_code": None,
                        "error": "Destination failed HTTPS/SSRF validation.",
                    }
                )
                continue
            payload = safe_event
            if destination_type == "slack":
                payload = {
                    "text": str(safe_event.get("summary") or "Matrixs incident"),
                    "attachments": [{"fields": safe_event}],
                }
            elif destination_type == "email":
                payload = {
                    "to": options.get("to"),
                    "subject": safe_event.get("summary") or "Matrixs incident",
                    "event": safe_event,
                }
            headers = {"Content-Type": "application/json"}
            token = os.getenv("SOFTWARE_ALERT_WEBHOOK_TOKEN", "").strip()
            if token and destination_type in {"webhook", "email"}:
                headers["Authorization"] = f"Bearer {token}"
            encoded_payload = json.dumps(
                payload, ensure_ascii=False, separators=(",", ":"), default=str
            ).encode("utf-8")
            if token and destination_type in {"webhook", "email"}:
                signature = hmac.new(
                    token.encode("utf-8"), encoded_payload, hashlib.sha256
                ).hexdigest()
                headers["X-Matrixs-Signature"] = f"sha256={signature}"
            try:
                response = requests.post(
                    endpoint,
                    data=encoded_payload,
                    headers=headers,
                    timeout=self.timeout_seconds,
                    allow_redirects=False,
                )
                delivered = 200 <= response.status_code < 300
                deliveries.append(
                    {
                        "destination_type": destination_type,
                        "destination_ref": urlparse(endpoint).hostname,
                        "status": "delivered" if delivered else "failed",
                        "response_code": response.status_code,
                        "error": None
                        if delivered
                        else f"Destination returned HTTP {response.status_code}.",
                    }
                )
            except requests.RequestException as error:
                deliveries.append(
                    {
                        "destination_type": destination_type,
                        "destination_ref": urlparse(endpoint).hostname,
                        "status": "failed",
                        "response_code": None,
                        "error": str(error)[:500],
                    }
                )
        return deliveries


__all__ = ["ReliabilityNotificationDispatcher"]
