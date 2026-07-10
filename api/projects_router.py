"""Project CRUD API — backed by SQLite app state."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field, field_validator

from src.app_state.store import create_project, get_project, list_projects

router = APIRouter(tags=["projects"])


class ProjectCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    environment: Literal["Development", "QA", "Production"] = "Development"

    @field_validator("name")
    @classmethod
    def name_not_blank(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Project name cannot be blank.")
        return cleaned


@router.post("/projects", status_code=status.HTTP_201_CREATED)
def create_project_endpoint(body: ProjectCreate) -> dict:
    project = create_project(
        name=body.name,
        description=body.description.strip(),
        environment=body.environment,
    )
    return project


@router.get("/projects")
def list_projects_endpoint() -> dict:
    return {"projects": list_projects()}


@router.get("/projects/{project_id}")
def get_project_endpoint(project_id: str) -> dict:
    project = get_project(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Project '{project_id}' not found.",
        )
    return project
