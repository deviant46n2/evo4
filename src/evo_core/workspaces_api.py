from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, Strict

from . import workspaces


class WorkspaceCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    project_id: str = Field(min_length=1, max_length=128)
    configuration_id: str = Field(min_length=1, max_length=128)
    configuration_revision_id: str = Field(min_length=1, max_length=128)
    checkout_id: Optional[str] = Field(default=None, max_length=128)
    description: str = Field(default="", max_length=4000)


class WorkspaceArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]


class WorkspaceReactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]


class WorkspaceRecord(BaseModel):
    workspace_id: str
    name: str
    description: str
    project_id: str
    checkout_id: Optional[str]
    configuration_id: str
    configuration_revision_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkspaceListResponse(BaseModel):
    items: list[WorkspaceRecord]
    total: int


def _to_workspace(record):
    return WorkspaceRecord(
        workspace_id=record["workspace_id"],
        name=record["name"],
        description=record["description"],
        project_id=record["project_id"],
        checkout_id=record["checkout_id"],
        configuration_id=record["configuration_id"],
        configuration_revision_id=record["configuration_revision_id"],
        status=record["status"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        version=record["version"],
    )


def build_workspace_router(store):
    router = APIRouter(prefix="/api/v1", tags=["platform-registry-workspaces"])

    @router.post("/workspaces", response_model=WorkspaceRecord, status_code=201)
    def create_workspace_route(payload: WorkspaceCreateRequest):
        try:
            record = workspaces.create_workspace(
                store,
                payload.name,
                payload.project_id,
                payload.configuration_id,
                payload.configuration_revision_id,
                checkout_id=payload.checkout_id,
                description=payload.description,
            )
        except workspaces.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except workspaces.WorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except workspaces.WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_workspace(record)

    @router.get("/workspaces/{workspace_id}", response_model=WorkspaceRecord)
    def get_workspace_route(workspace_id: str):
        try:
            record = workspaces.get_workspace(store, workspace_id)
        except workspaces.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_workspace(record)

    @router.get("/workspaces", response_model=WorkspaceListResponse)
    def list_workspaces_route(
        project_id: str | None = None,
        configuration_id: str | None = None,
        status: str | None = None,
    ):
        try:
            rows = workspaces.list_workspaces(
                store, project_id=project_id, configuration_id=configuration_id, status=status
            )
        except workspaces.WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        items = [_to_workspace(row) for row in rows]
        return WorkspaceListResponse(items=items, total=len(items))

    @router.post("/workspaces/{workspace_id}/archive", response_model=WorkspaceRecord)
    def archive_workspace_route(workspace_id: str, payload: WorkspaceArchiveRequest):
        try:
            record = workspaces.archive_workspace(
                store, workspace_id, expected_version=payload.expected_version
            )
        except workspaces.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except workspaces.WorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except workspaces.WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_workspace(record)

    @router.post("/workspaces/{workspace_id}/reactivate", response_model=WorkspaceRecord)
    def reactivate_workspace_route(workspace_id: str, payload: WorkspaceReactivateRequest):
        try:
            record = workspaces.reactivate_workspace(
                store, workspace_id, expected_version=payload.expected_version
            )
        except workspaces.WorkspaceNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except workspaces.WorkspaceConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except workspaces.WorkspaceValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_workspace(record)

    return router
