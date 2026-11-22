from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from typing import Annotated
from pydantic import BaseModel, ConfigDict, Field, Strict, field_validator


class ConfigurationCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    name: str = ""
    description: str = ""
    change_summary: str = ""

    @field_validator("name")
    @classmethod
    def _validate_name(cls, value):
        if value.strip() == "" and value != "":
            raise ValueError("name must not be whitespace-only")
        return value

    def validate_strings(self):
        if not isinstance(self.name, str):
            raise ValueError("name must be a string")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if not isinstance(self.change_summary, str):
            raise ValueError("change_summary must be a string")
        if self.name.strip() == "" and self.name != "":
            pass
        if self.name.strip() == "" and len(self.name) > 0:
            raise ValueError("name must not be whitespace-only when provided")
        # Required name is not enforced at creation; service defaults empty.


class RevisionCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition: dict[str, Any]
    expected_version: Annotated[int, Strict(), Field(gt=0)]
    parent_revision_id: Optional[str] = None
    change_summary: str = ""
    name: Optional[str] = None
    description: Optional[str] = None

    @classmethod
    def _validate_expected(cls, value):
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("expected_version must be a positive integer")
        return value


class RestoreRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_version: Annotated[int, Strict(), Field(gt=0)]
    change_summary: str = ""


class ConfigurationUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: str
    expected_version: Annotated[int, Strict(), Field(gt=0)]

    @field_validator("status")
    @classmethod
    def _validate_status(cls, value):
        if value not in {"active", "archived"}:
            raise ValueError("status must be active or archived")
        return value


class ConfigurationRecord(BaseModel):
    configuration_id: str
    name: str
    description: str
    status: str
    current_revision_id: str
    created_at: str
    updated_at: str
    version: int


class ConfigurationListResponse(BaseModel):
    items: list[ConfigurationRecord]
    total: int


class RevisionRecord(BaseModel):
    revision_id: str
    configuration_id: str
    revision_number: int
    schema_version: int
    definition: dict[str, Any]
    content_hash: str
    parent_revision_id: Optional[str]
    change_summary: str
    created_at: str
    provenance: dict[str, Any]


class RevisionListResponse(BaseModel):
    items: list[RevisionRecord]
    total: int


class ConfigurationRevisionResult(BaseModel):
    configuration: ConfigurationRecord
    revision: RevisionRecord


def _strict_expected_version(value):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError("expected_version must be a positive integer")
    return value


def _to_configuration_record(record):
    return ConfigurationRecord(
        configuration_id=record["configuration_id"],
        name=record["name"],
        description=record["description"],
        status=record["status"],
        current_revision_id=record["current_revision_id"],
        created_at=record["created_at"],
        updated_at=record["updated_at"],
        version=record["version"],
    )


def _to_revision_record(record):
    return RevisionRecord(
        revision_id=record["revision_id"],
        configuration_id=record["configuration_id"],
        revision_number=record["revision_number"],
        schema_version=record["schema_version"],
        definition=record["definition"],
        content_hash=record["content_hash"],
        parent_revision_id=record["parent_revision_id"],
        change_summary=record["change_summary"],
        created_at=record["created_at"],
        provenance=record["provenance"],
    )


def build_configuration_router(store):
    from . import ai_configurations

    router = APIRouter(prefix="/api/v1", tags=["platform-registry"])

    @router.get("/configurations", response_model=ConfigurationListResponse)
    def list_configurations(status: str | None = None):
        try:
            if status is not None and status not in {"active", "archived"}:
                raise HTTPException(status_code=422, detail="invalid status")
            rows = ai_configurations.list_configurations(store, status=status)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        items = [_to_configuration_record(row) for row in rows]
        return ConfigurationListResponse(items=items, total=len(items))

    @router.post("/configurations", response_model=ConfigurationRevisionResult, status_code=201)
    def create_configuration(payload: ConfigurationCreateRequest):
        try:
            payload.validate_strings()
            result = ai_configurations.create_configuration(
                store,
                payload.definition,
                name=payload.name,
                description=payload.description,
                change_summary=payload.change_summary,
            )
        except ai_configurations.ConfigurationValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except ai_configurations.ConfigurationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        config = ai_configurations.get_configuration(store, result["configuration"]["configuration_id"])
        revision = result["revision"]
        return ConfigurationRevisionResult(
            configuration=_to_configuration_record(config),
            revision=_to_revision_record(revision),
        )

    @router.get("/configurations/{configuration_id}", response_model=ConfigurationRecord)
    def get_configuration(configuration_id: str):
        try:
            record = ai_configurations.get_configuration(store, configuration_id)
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_configuration_record(record)

    @router.get("/configurations/{configuration_id}/revisions", response_model=RevisionListResponse)
    def list_revisions(configuration_id: str):
        try:
            rows = ai_configurations.list_revisions(store, configuration_id)
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        items = [_to_revision_record(row) for row in rows]
        return RevisionListResponse(items=items, total=len(items))

    @router.get("/configurations/{configuration_id}/revisions/{revision_id}", response_model=RevisionRecord)
    def get_revision(configuration_id: str, revision_id: str):
        try:
            record = ai_configurations.get_revision(store, configuration_id, revision_id)
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_revision_record(record)

    @router.post("/configurations/{configuration_id}/revisions", response_model=RevisionRecord, status_code=201)
    def create_revision(configuration_id: str, payload: RevisionCreateRequest):
        try:
            expected = _strict_expected_version(payload.expected_version)
            revision = ai_configurations.create_revision(
                store,
                configuration_id,
                payload.definition,
                expected_version=expected,
                parent_revision_id=payload.parent_revision_id,
                change_summary=payload.change_summary,
                name=payload.name,
                description=payload.description,
            )
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_configurations.ConfigurationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ai_configurations.ConfigurationValidationError, ai_configurations.ConfigurationArchivedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_revision_record(revision)

    @router.post("/configurations/{configuration_id}/restore/{revision_id}", response_model=RevisionRecord, status_code=201)
    def restore_revision(configuration_id: str, revision_id: str, payload: RestoreRevisionRequest):
        try:
            expected = _strict_expected_version(payload.expected_version)
            revision = ai_configurations.restore_revision(
                store,
                configuration_id,
                revision_id,
                expected_version=expected,
                change_summary=payload.change_summary,
            )
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_configurations.ConfigurationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ai_configurations.ConfigurationValidationError, ai_configurations.ConfigurationArchivedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_revision_record(revision)

    @router.patch("/configurations/{configuration_id}", response_model=ConfigurationRecord)
    def update_configuration(configuration_id: str, payload: ConfigurationUpdateRequest):
        try:
            expected = _strict_expected_version(payload.expected_version)
            if payload.status not in {"active", "archived"}:
                raise HTTPException(status_code=422, detail="invalid status")
            if payload.status == "active":
                record = ai_configurations.reactivate_configuration(
                    store, configuration_id, expected_version=expected
                )
            else:
                record = ai_configurations.archive_configuration(
                    store, configuration_id, expected_version=expected
                )
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_configurations.ConfigurationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ai_configurations.ConfigurationValidationError, ai_configurations.ConfigurationArchivedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_configuration_record(record)

    @router.post("/configurations/{configuration_id}/archive", response_model=ConfigurationRecord)
    def archive_configuration(configuration_id: str, payload: ConfigurationUpdateRequest):
        # Reuse expected version validation; status is ignored for archive endpoint.
        try:
            expected = _strict_expected_version(payload.expected_version)
            record = ai_configurations.archive_configuration(
                store, configuration_id, expected_version=expected
            )
        except ai_configurations.ConfigurationNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ai_configurations.ConfigurationConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ai_configurations.ConfigurationValidationError, ai_configurations.ConfigurationArchivedError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return _to_configuration_record(record)

    return router
