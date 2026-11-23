from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from . import project_provisioning


class ProjectProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=200)
    parent_path: str = Field(min_length=1, max_length=4096)
    description: str = Field(default="", max_length=4000)
    configuration_id: Optional[str] = Field(default=None, max_length=128)
    configuration_revision_id: Optional[str] = Field(default=None, max_length=128)


class ProjectProvisionResponse(BaseModel):
    operation_id: str
    status: str
    canonical_path: str | None = None
    project: dict | None = None
    checkout: dict | None = None
    workspace: dict | None = None
    workspace_bound: bool = False
    error: str | None = None


def build_project_provisioning_router(store):
    router = APIRouter(prefix="/api/v1", tags=["platform-registry-project-provisioning"])

    @router.post("/projects/provision", response_model=ProjectProvisionResponse, status_code=201)
    def provision_project_route(payload: ProjectProvisionRequest):
        try:
            result = project_provisioning.provision_project(
                store,
                payload.name,
                payload.parent_path,
                description=payload.description,
                configuration_id=payload.configuration_id,
                configuration_revision_id=payload.configuration_revision_id,
            )
        except project_provisioning.ProvisioningValidationError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except project_provisioning.ProvisioningConflictError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_provisioning.ProvisioningPartialError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except project_provisioning.ProvisioningError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc
        return ProjectProvisionResponse(
            operation_id=result["operation_id"],
            status=result["status"],
            canonical_path=result.get("canonical_path"),
            project=result.get("project"),
            checkout=result.get("checkout"),
            workspace=result.get("workspace"),
            workspace_bound=result.get("workspace_bound", False),
            error=None,
        )

    @router.get("/project-provisioning/{operation_id}", response_model=dict)
    def get_provisioning_operation_route(operation_id: str):
        try:
            return project_provisioning.get_provisioning_operation(store, operation_id)
        except project_provisioning.ProvisioningError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail="internal error") from exc

    return router
