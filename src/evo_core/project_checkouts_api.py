from typing import Annotated, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator

from . import project_checkouts


class ProjectCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=4000)
    git_remote: Optional[str] = Field(default=None, max_length=2048)
    default_ref: Optional[str] = Field(default=None, max_length=512)
    project_type: Optional[str] = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value):
        if not value.strip():
            raise ValueError("name must not be blank")
        return value


class ProjectUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, max_length=200)
    description: str = Field(default="", max_length=4000)
    git_remote: Optional[str] = Field(default=None, max_length=2048)
    default_ref: Optional[str] = Field(default=None, max_length=512)
    project_type: Optional[str] = Field(default=None, max_length=100)
    expected_version: Annotated[int, Strict(), Field(gt=0)]


class ProjectArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]


class ProjectReactivateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]


class ProjectRecord(BaseModel):
    project_id: str
    name: str
    description: str
    git_remote: Optional[str]
    default_ref: Optional[str]
    project_type: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProjectListResponse(BaseModel):
    items: list[ProjectRecord]
    total: int


class CheckoutRegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1, max_length=4096)
    branch_or_ref: Optional[str] = Field(default=None, max_length=512)
    last_known_commit: Optional[str] = Field(default=None, max_length=128)


class CheckoutUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    branch_or_ref: Optional[str] = Field(default=None, max_length=512)
    last_known_commit: Optional[str] = Field(default=None, max_length=128)
    expected_version: Annotated[int, Strict(), Field(gt=0)]


class CheckoutUnregisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]


class CheckoutRecord(BaseModel):
    checkout_id: str
    project_id: str
    canonical_path: str
    branch_or_ref: Optional[str]
    last_known_commit: Optional[str]
    availability_status: str
    created_at: str
    updated_at: str
    version: int


class CheckoutListResponse(BaseModel):
    items: list[CheckoutRecord]
    total: int


def _to_project(record):
    return ProjectRecord(
        project_id=record["project_id"],
        name=record["name"],
        description=record["description"],
        git_remote=record["git_remote"],
        default_ref=record["default_ref"],
        project_type=record["project_type"],
        status=record["status"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        version=record["version"],
    )


def _to_checkout(record):
    return CheckoutRecord(
        checkout_id=record["checkout_id"],
        project_id=record["project_id"],
        canonical_path=record["canonical_path"],
        branch_or_ref=record["branch_or_ref"],
        last_known_commit=record["last_known_commit"],
        availability_status=record["availability_status"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        version=record["version"],
    )


def build_project_checkout_router(store):
    router = APIRouter(prefix="/api/v1", tags=["platform-registry-projects"])

    @router.get("/projects", response_model=ProjectListResponse)
    def list_projects(status: str | None = None):
        try:
            if status is not None and status not in {"active", "archived"}:
                raise HTTPException(status_code=422, detail="invalid status")
            rows = project_checkouts.list_projects(store, status=status)
        except HTTPException:
            raise
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        items = [_to_project(row) for row in rows]
        return ProjectListResponse(items=items, total=len(items))

    @router.post("/projects", response_model=ProjectRecord, status_code=201)
    def register_project_route(payload: ProjectCreateRequest):
        try:
            record = project_checkouts.register_project(
                store,
                payload.name,
                description=payload.description,
                git_remote=payload.git_remote,
                default_ref=payload.default_ref,
                project_type=payload.project_type,
            )
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_project(record)

    @router.get("/projects/{project_id}", response_model=ProjectRecord)
    def get_project_route(project_id: str):
        try:
            record = project_checkouts.get_project(store, project_id)
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_project(record)

    @router.patch("/projects/{project_id}", response_model=ProjectRecord)
    def update_project_route(project_id: str, payload: ProjectUpdateRequest):
        try:
            updates = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
            record = project_checkouts.update_project(
                store, project_id, updates, expected_version=payload.expected_version
            )
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_project(record)

    @router.post("/projects/{project_id}/archive", response_model=ProjectRecord)
    def archive_project_route(project_id: str, payload: ProjectArchiveRequest):
        try:
            record = project_checkouts.archive_project(
                store, project_id, expected_version=payload.expected_version
            )
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_project(record)

    @router.post("/projects/{project_id}/reactivate", response_model=ProjectRecord)
    def reactivate_project_route(project_id: str, payload: ProjectReactivateRequest):
        try:
            record = project_checkouts.reactivate_project(
                store, project_id, expected_version=payload.expected_version
            )
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_project(record)

    @router.get("/projects/{project_id}/checkouts", response_model=CheckoutListResponse)
    def list_checkouts_route(project_id: str):
        try:
            rows = project_checkouts.list_checkouts(store, project_id)
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        items = [_to_checkout(row) for row in rows]
        return CheckoutListResponse(items=items, total=len(items))

    @router.post("/projects/{project_id}/checkouts", response_model=CheckoutRecord, status_code=201)
    def register_checkout_route(project_id: str, payload: CheckoutRegisterRequest):
        try:
            record = project_checkouts.register_checkout(
                store,
                project_id,
                payload.path,
                branch_or_ref=payload.branch_or_ref,
                last_known_commit=payload.last_known_commit,
            )
        except project_checkouts.ProjectNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.ProjectArchivedError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except project_checkouts.CheckoutPathConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.CheckoutPathError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_checkout(record)

    @router.get("/checkouts/{checkout_id}", response_model=CheckoutRecord)
    def get_checkout_route(checkout_id: str):
        try:
            record = project_checkouts.get_checkout(store, checkout_id)
        except project_checkouts.CheckoutNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_checkout(record)

    @router.patch("/checkouts/{checkout_id}", response_model=CheckoutRecord)
    def update_checkout_route(checkout_id: str, payload: CheckoutUpdateRequest):
        try:
            updates = payload.model_dump(exclude_unset=True, exclude={"expected_version"})
            record = project_checkouts.update_checkout(
                store, checkout_id, updates, expected_version=payload.expected_version
            )
        except project_checkouts.CheckoutNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_checkout(record)

    @router.post("/checkouts/{checkout_id}/refresh-availability", response_model=CheckoutRecord)
    def refresh_checkout_route(checkout_id: str):
        try:
            record = project_checkouts.refresh_checkout_availability(store, checkout_id)
        except project_checkouts.CheckoutNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_checkout(record)

    @router.post("/checkouts/{checkout_id}/unregister", response_model=dict)
    def unregister_checkout_route(checkout_id: str, payload: CheckoutUnregisterRequest):
        try:
            result = project_checkouts.unregister_checkout(
                store, checkout_id, expected_version=payload.expected_version
            )
        except project_checkouts.CheckoutNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except project_checkouts.CheckoutInUseError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_checkouts.ProjectValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return result

    return router
