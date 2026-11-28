"""Operator-controlled environment-variable secret resolution for Registry adapters."""
import os
import re
from types import MappingProxyType
from collections.abc import Mapping


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


class SecretResolutionError(ValueError):
    """Raised without exposing secret values or provider request material."""


def resolve_secret_references(secret_refs, allowed_env_vars, *, environ=None):
    """Resolve only explicitly allowlisted env:NAME references.

    The returned mapping is transient adapter input. Callers must not serialize,
    log, persist, or attach it to participant descriptors or invocation records.
    """
    if not isinstance(secret_refs, Mapping):
        raise SecretResolutionError("secret references must be an object")
    if isinstance(allowed_env_vars, (str, bytes)) or not isinstance(allowed_env_vars, (list, tuple, set, frozenset)):
        raise SecretResolutionError("operator secret allowlist must be a collection of variable names")
    allowlist = set()
    for name in allowed_env_vars:
        if not isinstance(name, str) or not _ENV_NAME.fullmatch(name):
            raise SecretResolutionError("operator secret allowlist contains an invalid variable name")
        allowlist.add(name)
    source = os.environ if environ is None else environ
    resolved = {}
    for key, reference in secret_refs.items():
        if key != "api_key" or not isinstance(reference, str):
            raise SecretResolutionError("unsupported secret reference")
        match = re.fullmatch(r"env:([A-Za-z_][A-Za-z0-9_]*)", reference)
        if match is None:
            raise SecretResolutionError("secret reference must use env:VARIABLE_NAME")
        variable = match.group(1)
        if variable not in allowlist:
            raise SecretResolutionError("secret reference is not operator-allowlisted")
        value = source.get(variable)
        if not isinstance(value, str) or not value:
            raise SecretResolutionError("allowlisted provider secret is unavailable")
        resolved[key] = value
    return MappingProxyType(resolved)
