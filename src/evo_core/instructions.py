"""Discovery and trust handling for repository-provided instruction files.

Repository instruction files, including conventional ``AGENTS.md`` files, are
untrusted project input.  They may describe project conventions, but they can
never override trusted Evo global policy, expand permissions, or authorize
consequential actions.
"""
from dataclasses import dataclass, field
from pathlib import Path
import json


TRUSTED_GLOBAL_AUTHORITY = "trusted Evo global policy and user authorization"
MAX_INSTRUCTION_FILE_BYTES = 256_000
MAX_INSTRUCTION_FILES = 32


@dataclass
class InstructionFile:
    path: str
    relative_path: str
    content: str = ""
    status: str = "applied"
    reason: str = ""
    trust_level: str = "untrusted"


@dataclass
class InstructionDiscovery:
    root: str
    target: str
    status: str = "success"
    applied_files: list = field(default_factory=list)
    ignored_files: list = field(default_factory=list)
    error: str = ""
    provenance: dict = field(default_factory=dict)

    @property
    def files(self):
        return list(self.applied_files)

    @property
    def discovered_files(self):
        return list(self.applied_files) + list(self.ignored_files)

    @property
    def instructions(self):
        return [item.content for item in self.applied_files]

    @property
    def applied_paths(self):
        return [item.relative_path for item in self.applied_files]

    def combined_text(self):
        parts = []
        for item in self.applied_files:
            parts.append(f"--- {item.relative_path} ---\n{item.content}")
        return "\n\n".join(parts)

    def to_provenance(self):
        return {
            "root": self.root,
            "target": self.target,
            "status": self.status,
            "applied": [
                {"path": item.path, "relative_path": item.relative_path,
                 "status": item.status, "trust_level": item.trust_level}
                for item in self.applied_files
            ],
            "ignored": [
                {"path": item.path, "relative_path": item.relative_path,
                 "status": item.status, "reason": item.reason,
                 "trust_level": item.trust_level}
                for item in self.ignored_files
            ],
            "precedence": "root-to-target (root first, more specific files later)",
            "trust_level": "untrusted",
            "authority": TRUSTED_GLOBAL_AUTHORITY,
            "error": self.error,
        }


def _safe_resolve(root, target):
    root = Path(root).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("instruction root is not a directory")
    if target in (None, "", "."):
        target_path = root
    else:
        target_path = (root / str(target)).resolve()
    try:
        target_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("instruction target escapes the root") from exc
    return root, target_path


def _ancestor_directories(root, base):
    relative = base.relative_to(root)
    directories = [root]
    current = root
    for part in relative.parts:
        current = current / part
        directories.append(current)
    return directories


def discover_repository_instructions(root, target=".", max_file_bytes=MAX_INSTRUCTION_FILE_BYTES,
                                    max_files=MAX_INSTRUCTION_FILES):
    """Discover applicable ``AGENTS.md`` files beneath *root*.

    Only files on the path from *root* to *target* are considered.  Sibling or
    unrelated nested instruction files are intentionally not applied.
    """
    discovery = InstructionDiscovery(root=str(root), target=str(target))
    try:
        root_path, target_path = _safe_resolve(root, target)
    except (OSError, ValueError) as exc:
        discovery.status = "failed"
        discovery.error = str(exc)
        discovery.provenance = discovery.to_provenance()
        return discovery

    if target_path.is_file():
        base = target_path.parent
    else:
        base = target_path

    directories = _ancestor_directories(root_path, base)
    candidates = []
    for directory in directories:
        candidate = directory / "AGENTS.md"
        if candidate.is_file() and not candidate.is_symlink():
            try:
                candidate.resolve().relative_to(root_path)
            except ValueError:
                continue
            candidates.append(candidate)

    if len(candidates) > max_files:
        for extra in candidates[max_files:]:
            extra_relative = extra.relative_to(root_path).as_posix()
            discovery.ignored_files.append(InstructionFile(
                path=str(extra), relative_path=extra_relative,
                status="ignored", reason=f"maximum instruction file count ({max_files}) exceeded",
                trust_level="untrusted"))
        candidates = candidates[:max_files]
        discovery.status = "limit_exceeded"
        discovery.error = f"applicable instruction file count exceeds limit of {max_files}"

    for candidate in candidates:
        relative = candidate.relative_to(root_path).as_posix()
        try:
            size = candidate.stat().st_size
            if size > max_file_bytes:
                discovery.ignored_files.append(InstructionFile(
                    path=str(candidate), relative_path=relative,
                    status="ignored", reason=f"file is {size} bytes; limit is {max_file_bytes}",
                    trust_level="untrusted"))
                continue
            content = candidate.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            discovery.ignored_files.append(InstructionFile(
                path=str(candidate), relative_path=relative,
                status="unreadable", reason=str(exc), trust_level="untrusted"))
            continue
        discovery.applied_files.append(InstructionFile(
            path=str(candidate), relative_path=relative,
            content=content, status="applied", trust_level="untrusted"))

    discovery.provenance = discovery.to_provenance()
    return discovery


# Backward/alias-friendly names for tests and callers.
discover_instructions = discover_repository_instructions
discover_agents_md = discover_repository_instructions
discover_agents_files = discover_repository_instructions
find_agents_md = discover_repository_instructions
InstructionContext = InstructionDiscovery
AgentsInstruction = InstructionFile


def workspace_root_for(store, project_id=None, workspace_id=None):
    """Resolve a registered workspace's checkout root, or return None."""
    if not workspace_id:
        return None
    try:
        from .workspaces import get_workspace
        from .project_checkouts import _checkout_row
        workspace = get_workspace(store, workspace_id)
    except Exception:
        return None
    if not isinstance(workspace, dict):
        try:
            workspace = dict(workspace)
        except Exception:
            return None
    if workspace.get("status") not in (None, "active"):
        return None
    if project_id is not None and workspace.get("project_id") != project_id:
        return None
    checkout_id = workspace.get("checkout_id")
    if not checkout_id:
        return None
    try:
        with store.lock:
            checkout = _checkout_row(store.db, checkout_id)
        checkout = dict(checkout) if not isinstance(checkout, dict) else checkout
    except Exception:
        return None
    canonical = checkout.get("canonical_path")
    if not canonical:
        return None
    try:
        path = Path(canonical).resolve()
    except (OSError, RuntimeError):
        return None
    if not path.is_dir():
        return None
    return path


def discover_for_scope(store, project_id=None, workspace_id=None, target="."):
    root = workspace_root_for(store, project_id, workspace_id)
    if root is None:
        discovery = InstructionDiscovery(root="", target=str(target), status="failed",
                                        error="no registered workspace root or checkout")
        discovery.provenance = discovery.to_provenance()
        return discovery
    return discover_repository_instructions(root, target=target)
