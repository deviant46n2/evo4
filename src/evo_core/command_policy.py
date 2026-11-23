"""Fail-closed command policy resolution for global and project execution.

Global command prefixes are the maximum authority. A project configuration may
only narrow that set. Project policy lives in the workspace's pinned
configuration revision at components.command_policy.allowed_commands.
"""
import json


class CommandPolicyError(ValueError):
    """Raised when command policy cannot be interpreted unambiguously."""


def _normalize_prefixes(value, field_name):
    if not isinstance(value, (list, tuple)):
        raise CommandPolicyError(f"{field_name} must be a list of argv prefixes")
    prefixes = []
    for index, prefix in enumerate(value):
        if not isinstance(prefix, (list, tuple)) or not prefix:
            raise CommandPolicyError(f"{field_name}[{index}] must be a non-empty argv list")
        if any(not isinstance(part, str) or not part or "\x00" in part for part in prefix):
            raise CommandPolicyError(f"{field_name}[{index}] must contain non-empty strings without NUL")
        normalized = tuple(prefix)
        if normalized not in prefixes:
            prefixes.append(normalized)
    return tuple(prefixes)


def _decode_revision_definition(revision):
    if not isinstance(revision, dict):
        raise CommandPolicyError("workspace configuration revision is unavailable")
    if "definition" in revision:
        definition = revision["definition"]
    else:
        raw = revision.get("definition_json")
        if not isinstance(raw, str):
            raise CommandPolicyError("workspace configuration definition is missing")
        try:
            definition = json.loads(raw)
        except (TypeError, ValueError) as exc:
            raise CommandPolicyError("workspace configuration definition is invalid JSON") from exc
    if not isinstance(definition, dict):
        raise CommandPolicyError("workspace configuration definition must be an object")
    return definition


def project_command_prefixes(revision):
    """Return explicitly configured project prefixes; missing policy denies all."""
    definition = _decode_revision_definition(revision)
    components = definition.get("components")
    if not isinstance(components, dict):
        raise CommandPolicyError("workspace configuration components are invalid")
    policy = components.get("command_policy")
    if policy is None:
        return ()
    if not isinstance(policy, dict):
        raise CommandPolicyError("components.command_policy must be an object")
    unknown = set(policy) - {"allowed_commands"}
    if unknown:
        raise CommandPolicyError(
            f"components.command_policy has unsupported fields: {sorted(unknown)}"
        )
    if "allowed_commands" not in policy:
        raise CommandPolicyError("components.command_policy.allowed_commands is required")
    return _normalize_prefixes(
        policy["allowed_commands"], "components.command_policy.allowed_commands"
    )


def intersect_command_prefixes(global_prefixes, project_prefixes):
    """Return prefixes whose accepted argv sets are in both policies."""
    global_values = _normalize_prefixes(global_prefixes, "global allowed_commands")
    project_values = _normalize_prefixes(project_prefixes, "project allowed_commands")
    effective = []
    for global_prefix in global_values:
        for project_prefix in project_values:
            common = None
            if project_prefix[:len(global_prefix)] == global_prefix:
                common = project_prefix
            elif global_prefix[:len(project_prefix)] == project_prefix:
                common = global_prefix
            if common is not None and common not in effective:
                effective.append(common)
    return tuple(effective)


def effective_project_command_prefixes(global_prefixes, revision):
    """Resolve the fail-closed intersection for a registered workspace."""
    return intersect_command_prefixes(
        global_prefixes, project_command_prefixes(revision)
    )
