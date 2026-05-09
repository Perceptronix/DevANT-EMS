from __future__ import annotations

from fastapi import APIRouter

from config import get_config
from samples import get_sample_errors
from state import get_state_manager
from sources import get_available_sources, get_data_source

router = APIRouter()


@router.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Error Monitoring Agent Demo",
        "version": "1.0.0",
    }


@router.get("/api/config")
async def get_app_config():
    config = get_config()
    state = get_state_manager()

    data_source = get_data_source()
    available_sources = get_available_sources()

    for name, info in available_sources.items():
        info["active"] = (name == data_source.source_type)

    return {
        "airweave_configured": config.airweave.is_configured,
        "openai_configured": bool(config.llm.openai_api_key),
        "anthropic_configured": bool(config.llm.anthropic_api_key),
        "llm_provider": config.llm.provider,
        "airweave": {
            "configured": config.airweave.is_configured,
            "collection_id": config.airweave.collection_id[:8] + "..." if config.airweave.collection_id else None,
        },
        "llm": {
            "configured": config.llm.is_configured,
            "provider": config.llm.provider,
            "model": config.llm.model,
        },
        "data_source": {
            "active": data_source.name,
            "type": data_source.source_type,
            "available": available_sources,
        },
        "integrations": {
            "github_issues": {
                "enabled": config.github.enabled,
                "configured": config.github.is_configured,
                "owner": config.github.owner,
                "repo": config.github.repo,
                "mode": "live" if config.github.is_configured else "preview",
            },
            "slack": {
                "enabled": config.slack.enabled,
                "configured": config.slack.is_configured,
                "mode": "live" if config.slack.is_configured else "preview",
            },
        },
        "state": state.get_stats(),
    }


@router.get("/api/samples")
async def get_samples():
    errors = get_sample_errors(include_extended=True)
    return {
        "samples": errors,
        "count": len(errors),
    }


@router.get("/api/state")
async def get_state():
    state = get_state_manager()
    signatures = state.get_all_signatures()
    mutes = state.get_active_mutes()

    return {
        "stats": state.get_stats(),
        "recent_signatures": list(signatures.keys())[-10:],
        "active_mutes": list(mutes.keys()),
    }
