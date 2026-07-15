"""Model Registry catalog — see SPEC.md sections 7 and 12.

Powers the ``/models`` UI and is what the router (section 8) resolves
against, though the router queries the DB directly rather than going
through this HTTP endpoint — this is purely the read-facing catalog view.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.db.models import Model as ModelRow
from app.db.models import Provider, User
from app.db.session import get_db

router = APIRouter(tags=["models"])


class ModelResponse(BaseModel):
    id: int
    provider_name: str
    model_id: str
    display_name: str
    supports_vision: bool
    supports_coding_hint: int | None
    supports_reasoning_hint: int | None
    context_length: int | None
    speed_rating: int | None
    free: bool
    quality_source: str
    enabled: bool
    last_scanned_at: datetime | None


def _to_response(model: ModelRow) -> ModelResponse:
    return ModelResponse(
        id=model.id,
        provider_name=model.provider_name,
        model_id=model.model_id,
        display_name=model.display_name,
        supports_vision=model.supports_vision,
        supports_coding_hint=model.supports_coding_hint,
        supports_reasoning_hint=model.supports_reasoning_hint,
        context_length=model.context_length,
        speed_rating=model.speed_rating,
        free=model.free,
        quality_source=model.quality_source.value,
        enabled=model.enabled,
        last_scanned_at=model.last_scanned_at,
    )


@router.get("/models", response_model=list[ModelResponse])
async def list_models(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[ModelResponse]:
    result = await db.execute(
        select(ModelRow)
        .join(Provider, ModelRow.provider_name == Provider.name)
        .order_by(Provider.priority, ModelRow.model_id)
    )
    return [_to_response(model) for model in result.scalars().all()]
