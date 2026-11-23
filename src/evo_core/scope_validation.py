def validate_scope(store, project_id=None, workspace_id=None):
    if project_id is not None:
        if not isinstance(project_id, str) or not project_id.strip():
            raise ValueError("project_id must be None or a non-empty string")
        project_id = project_id.strip()
    if workspace_id is not None:
        if not isinstance(workspace_id, str) or not workspace_id.strip():
            raise ValueError("workspace_id must be None or a non-empty string")
        workspace_id = workspace_id.strip()
    if workspace_id is not None and project_id is None:
        raise ValueError("workspace_id requires project_id")

    normalized_project = project_id.strip() if isinstance(project_id, str) else project_id
    normalized_workspace = workspace_id.strip() if isinstance(workspace_id, str) else workspace_id

    if project_id is None:
        return (None, None)

    import sqlite3
    from .project_checkouts import _project_row, ProjectNotFoundError
    from .workspaces import _workspace_row, WorkspaceNotFoundError

    with store.lock:
        try:
            project = _project_row(store.db, project_id)
        except ProjectNotFoundError as exc:
            raise ValueError("project_id does not refer to an existing project") from exc
        except sqlite3.OperationalError as exc:
            raise ValueError("project_id cannot be validated without an initialized Registry") from exc

    if workspace_id is None:
        return (normalized_project, None)

    if workspace_id is not None:
            try:
                workspace = _workspace_row(store.db, workspace_id)
            except WorkspaceNotFoundError as exc:
                raise ValueError("workspace_id does not refer to an existing workspace") from exc
            except sqlite3.OperationalError as exc:
                raise ValueError("workspace_id cannot be validated without an initialized Registry") from exc
            if workspace["project_id"] != project_id:
                raise ValueError("workspace does not belong to the supplied project")

    return (normalized_project, normalized_workspace)


def scope_error(exc):
    return exc


def scope_is_visible(record_project_id, record_workspace_id, request_project_id, request_workspace_id):
    """Return whether a record belongs to the requested global/project/workspace view."""
    if request_project_id is None:
        return record_project_id is None and record_workspace_id is None
    if record_project_id is not None and record_project_id != request_project_id:
        return False
    if request_workspace_id is None:
        return record_workspace_id is None
    if record_project_id is None:
        return record_workspace_id is None
    return record_project_id == request_project_id and (
        record_workspace_id is None or record_workspace_id == request_workspace_id
    )
