"""Operator-owned provider compliance approvals.

Origin allowlisting controls where the adapter may connect. These records
separately express the operator's reviewed integration/interface/use decision.
"""
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable

from .participant_contracts import resolve_adapter_contract
from .provider_endpoint import (
    ProviderEndpointError,
    is_loopback_provider_origin,
    normalize_provider_origin,
)


class ProviderApprovalError(ValueError):
    pass


@dataclass(frozen=True)
class ProviderApproval:
    origin: str
    adapter_id: str
    uses: tuple[str, ...]
    status: str
    reviewed_at: str | None
    terms_reference: str | None
    data_handling_reference: str | None


def _validate_review_date(value):
    if not isinstance(value, str) or not value:
        raise ProviderApprovalError("provider approval reviewed_at must be an ISO date or timestamp")
    try:
        date.fromisoformat(value)
    except ValueError:
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ProviderApprovalError("provider approval reviewed_at must be an ISO date or timestamp") from exc
    return value


def _optional_reference(value, field):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 1024 or "\x00" in value:
        raise ProviderApprovalError(f"provider approval {field} is invalid")
    return value


def parse_provider_approvals(raw) -> tuple[ProviderApproval, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list) or len(raw) > 128:
        raise ProviderApprovalError("provider_approvals must be a bounded list of tables")
    approvals = []
    seen = set()
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ProviderApprovalError(f"provider_approvals[{index}] must be a table")
        allowed = {
            "origin", "adapter_id", "uses", "status", "reviewed_at",
            "terms_reference", "data_handling_reference",
        }
        if set(item) - allowed or not {"origin", "adapter_id", "uses", "status"}.issubset(item):
            raise ProviderApprovalError(f"provider_approvals[{index}] has missing or unknown fields")
        try:
            origin = normalize_provider_origin(item["origin"])
            local_origin = is_loopback_provider_origin(item["origin"])
        except (ProviderEndpointError, TypeError) as exc:
            raise ProviderApprovalError(f"provider_approvals[{index}] origin is invalid") from exc
        adapter_id = item["adapter_id"]
        try:
            resolve_adapter_contract(adapter_id, 1, "model")
        except (TypeError, ValueError) as exc:
            raise ProviderApprovalError(f"provider_approvals[{index}] adapter is unsupported") from exc
        uses = item["uses"]
        if (
            not isinstance(uses, list)
            or not uses
            or len(uses) > 16
            or any(not isinstance(use, str) or use != "chat_completion" for use in uses)
            or len(uses) != len(set(uses))
        ):
            raise ProviderApprovalError(f"provider_approvals[{index}] uses are invalid")
        status = item["status"]
        if not isinstance(status, str) or status not in {"local_only", "approved", "restricted", "suspended", "unknown"}:
            raise ProviderApprovalError(f"provider_approvals[{index}] status is invalid")
        if status == "local_only" and not local_origin:
            raise ProviderApprovalError("local_only approval requires a loopback origin")
        if status == "approved" and local_origin:
            raise ProviderApprovalError("loopback origins must use explicit local_only classification")
        reviewed_at = item.get("reviewed_at")
        if reviewed_at is not None:
            reviewed_at = _validate_review_date(reviewed_at)
        terms = _optional_reference(item.get("terms_reference"), "terms_reference")
        handling = _optional_reference(item.get("data_handling_reference"), "data_handling_reference")
        if status in {"approved", "local_only"} and (
            reviewed_at is None or handling is None or (status == "approved" and terms is None)
        ):
            raise ProviderApprovalError("approved provider records require review date and handling/terms references")
        approval = ProviderApproval(
            origin, adapter_id, tuple(uses), status, reviewed_at, terms, handling,
        )
        for use in approval.uses:
            key = (approval.origin, approval.adapter_id, use)
            if key in seen:
                raise ProviderApprovalError("duplicate provider approval for the same origin, adapter, and use")
            seen.add(key)
        approvals.append(approval)
    return tuple(approvals)


def find_provider_approval(approvals: Iterable[ProviderApproval], origin: str, adapter_id: str, use: str):
    """Return the exact reviewed record or None (unknown); never infer approval."""
    try:
        normalized_origin = normalize_provider_origin(origin)
    except ProviderEndpointError:
        return None
    for approval in approvals:
        if (
            approval.origin == normalized_origin
            and approval.adapter_id == adapter_id
            and use in approval.uses
        ):
            return approval
    return None
