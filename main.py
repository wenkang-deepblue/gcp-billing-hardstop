import base64
import json
import logging
import os
import urllib.request
from decimal import Decimal, InvalidOperation
from typing import Any, Dict

import functions_framework
from google.api_core import exceptions
from google.cloud import billing_v1


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger(__name__)

billing_client = billing_v1.CloudBillingClient()


def _env_bool(name: str, default: bool) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    return raw_value.strip().lower() in {"1", "true", "yes", "on"}


def _log(message: str, severity: str = "INFO", **fields: Any) -> None:
    payload = {"severity": severity, "message": message, **fields}
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def get_project_id() -> str:
    """Return the project to protect.

    Lookup order:
    1. TARGET_PROJECT_ID
    2. GCP_PROJECT
    3. GOOGLE_CLOUD_PROJECT
    4. Metadata server
    """
    for env_name in ("TARGET_PROJECT_ID", "GCP_PROJECT", "GOOGLE_CLOUD_PROJECT"):
        project_id = os.getenv(env_name)
        if project_id:
            return project_id

    url = "http://metadata.google.internal/computeMetadata/v1/project/project-id"
    request = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
    with urllib.request.urlopen(request, timeout=5) as response:
        project_id = response.read().decode().strip()

    if not project_id:
        raise ValueError("Unable to determine protected project id.")

    return project_id


def _decode_budget_message(cloud_event) -> Dict[str, Any]:
    try:
        encoded_data = cloud_event.data["message"]["data"]
    except KeyError as exc:
        raise ValueError("CloudEvent does not contain Pub/Sub message data.") from exc

    try:
        raw_message = base64.b64decode(encoded_data).decode("utf-8")
        return json.loads(raw_message)
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("Unable to decode budget notification payload.") from exc


def _to_decimal(value: Any, field_name: str) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ValueError(f"Invalid numeric value for '{field_name}': {value!r}") from exc


def _get_required_field(payload: Dict[str, Any], field_name: str) -> Any:
    if field_name not in payload:
        raise ValueError(f"Budget notification missing required field '{field_name}'.")
    return payload[field_name]


def _validate_notification_scope(payload: Dict[str, Any]) -> None:
    expected_budget_name = os.getenv("EXPECTED_BUDGET_NAME")
    if not expected_budget_name:
        return

    actual_budget_name = payload.get("budgetDisplayName")
    if actual_budget_name != expected_budget_name:
        _log(
            "Ignoring budget notification for unexpected budget.",
            severity="WARNING",
            expected_budget_name=expected_budget_name,
            actual_budget_name=actual_budget_name,
        )
        raise IgnoreEvent("Notification belongs to a different budget.")


def _is_billing_enabled(project_name: str) -> bool:
    try:
        response = billing_client.get_project_billing_info(name=project_name)
        enabled = bool(response.billing_enabled)
        _log(
            "Fetched current billing status.",
            project_name=project_name,
            billing_enabled=enabled,
        )
        return enabled
    except Exception as exc:
        _log(
            "Unable to determine billing status. Assuming billing is enabled.",
            severity="WARNING",
            project_name=project_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return True


def _disable_billing_for_project(project_name: str, simulate_deactivation: bool) -> None:
    if simulate_deactivation:
        _log(
            "Simulation mode enabled. Billing disable skipped.",
            severity="CRITICAL",
            project_name=project_name,
            simulated=True,
        )
        return

    project_billing_info = billing_v1.ProjectBillingInfo(billing_account_name="")

    try:
        response = billing_client.update_project_billing_info(
            name=project_name,
            project_billing_info=project_billing_info,
        )
        _log(
            "Billing disabled successfully.",
            severity="CRITICAL",
            project_name=project_name,
            billing_enabled=bool(response.billing_enabled),
            billing_account_name=response.billing_account_name,
        )
    except exceptions.GoogleAPICallError as exc:
        _log(
            "Failed to disable billing through Cloud Billing API.",
            severity="ERROR",
            project_name=project_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise


class IgnoreEvent(Exception):
    """Raised when the notification should be acknowledged and ignored."""


@functions_framework.cloud_event
def stop_billing(cloud_event) -> None:
    simulate_deactivation = _env_bool("SIMULATE_DEACTIVATION", True)
    project_id = get_project_id()
    project_name = f"projects/{project_id}"

    try:
        payload = _decode_budget_message(cloud_event)
        _validate_notification_scope(payload)

        cost_amount = _to_decimal(_get_required_field(payload, "costAmount"), "costAmount")
        budget_amount = _to_decimal(_get_required_field(payload, "budgetAmount"), "budgetAmount")
        threshold = payload.get("alertThresholdExceeded")

        _log(
            "Received budget notification.",
            project_name=project_name,
            budget_name=payload.get("budgetDisplayName"),
            cost_amount=str(cost_amount),
            budget_amount=str(budget_amount),
            alert_threshold_exceeded=threshold,
            cost_interval_start=payload.get("costIntervalStart"),
            simulation_mode=simulate_deactivation,
        )

        if cost_amount < budget_amount:
            _log(
                "Current cost is still below budget. No action required.",
                project_name=project_name,
                cost_amount=str(cost_amount),
                budget_amount=str(budget_amount),
            )
            return

        _log(
            "Budget threshold reached. Starting billing shutdown flow.",
            severity="WARNING",
            project_name=project_name,
            cost_amount=str(cost_amount),
            budget_amount=str(budget_amount),
        )

        if not _is_billing_enabled(project_name):
            _log(
                "Billing is already disabled. Nothing to do.",
                project_name=project_name,
            )
            return

        _disable_billing_for_project(
            project_name=project_name,
            simulate_deactivation=simulate_deactivation,
        )
    except IgnoreEvent:
        return
    except Exception as exc:
        _log(
            "stop_billing failed. Raising error so the platform can mark this execution as failed.",
            severity="ERROR",
            project_name=project_name,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        raise