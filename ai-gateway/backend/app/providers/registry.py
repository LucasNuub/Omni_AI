"""Static registry of provider adapter instances and their seed metadata.

Model-level resolution (the Model Registry) doesn't exist yet, so the router
works provider-level only: it chooses among whichever of these adapters
currently have an enabled ``Provider`` row and a usable key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuthType, Provider
from app.providers.base import ProviderAdapter
from app.providers.deepseek import DeepSeekAdapter
from app.providers.gemini import GeminiAdapter
from app.providers.groq import GroqAdapter
from app.providers.huggingface import HuggingFaceAdapter
from app.providers.ollama import OllamaAdapter
from app.providers.openrouter import OpenRouterAdapter
from app.providers.pollinations import PollinationsAdapter

# PollinationsAdapter satisfies ProviderAdapter structurally (it doesn't
# inherit it), and mypy's structural check trips on the same async-generator
# vs. coroutine ambiguity as the cast in api/chat.py — the cast reflects its
# actual runtime behavior, not a real type mismatch.
ADAPTERS: dict[str, ProviderAdapter] = {
    "groq": GroqAdapter(),
    "gemini": GeminiAdapter(),
    "openrouter": OpenRouterAdapter(),
    "pollinations": cast(ProviderAdapter, PollinationsAdapter()),
    "huggingface": HuggingFaceAdapter(),
    "deepseek": DeepSeekAdapter(),
    "ollama": OllamaAdapter(),
}


@dataclass(frozen=True)
class _ProviderSeed:
    name: str
    auth_type: AuthType
    priority: int


# Lower priority number = tried first. Ollama is deliberately last: SPEC.md
# section 16 makes it the always-available last-hop fallback, not a
# first-choice provider.
_SEED_ORDER: tuple[_ProviderSeed, ...] = (
    _ProviderSeed("groq", AuthType.api_key, 0),
    _ProviderSeed("gemini", AuthType.api_key, 1),
    _ProviderSeed("openrouter", AuthType.api_key, 2),
    _ProviderSeed("pollinations", AuthType.none, 3),
    _ProviderSeed("huggingface", AuthType.api_key, 4),
    _ProviderSeed("deepseek", AuthType.api_key, 5),
    _ProviderSeed("ollama", AuthType.local, 6),
)


async def ensure_providers_seeded(db: AsyncSession) -> None:
    """Idempotently insert a ``Provider`` row for each known adapter.

    Safe to call on every startup: existing rows (and any admin-toggled
    ``enabled`` state) are left untouched.
    """
    result = await db.execute(select(Provider.name))
    existing = set(result.scalars().all())

    for seed in _SEED_ORDER:
        if seed.name in existing:
            continue
        db.add(Provider(name=seed.name, auth_type=seed.auth_type, priority=seed.priority))

    await db.commit()
