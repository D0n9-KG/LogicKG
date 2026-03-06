from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.schema_presets import PRESET_IDS, apply_schema_preset, list_schema_presets
from app.schema_store import (
    PaperType,
    activate_version,
    create_new_version,
    delete_version,
    list_versions,
    load_active,
    load_version,
    validate_schema,
)


router = APIRouter(prefix="/schema", tags=["schema"])

PresetId = Literal["high_precision", "balanced", "high_recall"]


class SchemaResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_: dict[str, Any] = Field(alias="schema")


@router.get("/active", response_model=SchemaResponse)
def get_active_schema(paper_type: PaperType = "research"):
    try:
        return SchemaResponse(schema_=load_active(paper_type))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/version/{version}", response_model=SchemaResponse)
def get_schema_version(version: int, paper_type: PaperType = "research"):
    try:
        return SchemaResponse(schema_=load_version(paper_type, version))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/versions")
def get_versions(paper_type: PaperType = "research"):
    try:
        items = list_versions(paper_type)
        return {
            "paper_type": paper_type,
            "versions": [{"version": x.version, "name": str(x.name or "")} for x in items],
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.delete("/version/{version}")
def delete_schema_version(version: int, paper_type: PaperType = "research"):
    try:
        return {"ok": True, **delete_version(paper_type, version)}
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/presets")
def get_schema_presets():
    try:
        return {"presets": list_schema_presets()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ApplyPresetRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    preset_id: PresetId
    schema_: dict[str, Any] = Field(alias="schema")


@router.post("/presets/apply", response_model=SchemaResponse)
def apply_preset(req: ApplyPresetRequest):
    try:
        if req.preset_id not in PRESET_IDS:
            raise ValueError(f"Unsupported preset_id: {req.preset_id}")
        merged = apply_schema_preset(req.schema_, preset_id=req.preset_id)
        validate_schema(merged)
        return SchemaResponse(schema_=merged)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ValidateSchemaRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    schema_: dict[str, Any] = Field(alias="schema")


@router.post("/validate")
def validate_schema_endpoint(req: ValidateSchemaRequest):
    try:
        validate_schema(req.schema_)
        return {"ok": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class CreateSchemaRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    paper_type: PaperType = Field(default="research")
    schema_: dict[str, Any] = Field(alias="schema")
    activate: bool = True


@router.post("/new", response_model=SchemaResponse)
def create_schema(req: CreateSchemaRequest):
    try:
        s = create_new_version(req.paper_type, req.schema_, activate=bool(req.activate))
        return SchemaResponse(schema_=s)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class ActivateSchemaRequest(BaseModel):
    paper_type: PaperType = Field(default="research")
    version: int = Field(ge=1)


@router.post("/activate", response_model=SchemaResponse)
def activate_schema(req: ActivateSchemaRequest):
    try:
        return SchemaResponse(schema_=activate_version(req.paper_type, req.version))
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

