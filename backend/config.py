"""
Application configuration with feature flags for optional integrations.

This module centralizes all configuration, making it easy to:
- Run with just sample data (default, zero friction)
- Connect real data sources (Sentry, Azure, etc.)
- Use Groq for semantic processing
"""
import os
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from functools import lru_cache


@dataclass
class GroqConfig:
    """Groq API configuration."""
    api_key: Optional[str] = None
    model: str = "llama3-70b-8192"
    
    @property
    def is_configured(self) -> bool:
        """Check if Groq is configured."""
        return bool(self.api_key)


@dataclass
class GitHubConfig:
    """GitHub API configuration for code context."""
    enabled: bool = False
    token: Optional[str] = None
    owner: Optional[str] = None
    repo: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if GitHub is configured and enabled."""
        return self.enabled and bool(self.token) and bool(self.owner) and bool(self.repo)


@dataclass
class ChromaDBConfig:
    """ChromaDB vector store configuration."""
    persist_dir: str = "./data/chroma"
    
    @property
    def is_configured(self) -> bool:
        """ChromaDB is always available with local persistence."""
        return True


@dataclass
class DataSourceConfig:
    """Data source configuration."""
    # Which source to use: "sample", "azure", "sentry", "datadog"
    source_type: str = "sample"
    
    # Azure Log Analytics
    azure_workspace_id: Optional[str] = None
    azure_client_id: Optional[str] = None
    azure_client_secret: Optional[str] = None
    azure_tenant_id: Optional[str] = None
    
    # Sentry
    sentry_auth_token: Optional[str] = None
    sentry_org_slug: Optional[str] = None
    sentry_project_slug: Optional[str] = None
    sentry_url: str = "https://sentry.io"
    
    # Datadog
    datadog_api_key: Optional[str] = None
    datadog_app_key: Optional[str] = None
    datadog_site: str = "datadoghq.com"
    
    @property
    def azure_configured(self) -> bool:
        return all([
            self.azure_workspace_id,
            self.azure_client_id,
            self.azure_client_secret,
            self.azure_tenant_id,
        ])
    
    @property
    def sentry_configured(self) -> bool:
        return all([
            self.sentry_auth_token,
            self.sentry_org_slug,
        ])
    
    @property
    def datadog_configured(self) -> bool:
        return all([
            self.datadog_api_key,
            self.datadog_app_key,
        ])


@dataclass
class LLMConfig:
    """LLM provider configuration."""
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    
    # Model preferences
    anthropic_model: str = "claude-sonnet-4-20250514"
    openai_model: str = "gpt-4o"
    
    @property
    def provider(self) -> Optional[str]:
        """Get the active LLM provider."""
        if self.anthropic_api_key:
            return "anthropic"
        elif self.openai_api_key:
            return "openai"
        return None
    
    @property
    def is_configured(self) -> bool:
        return self.provider is not None
    
    @property
    def model(self) -> Optional[str]:
        """Get the model name for the active provider."""
        if self.provider == "anthropic":
            return self.anthropic_model
        elif self.provider == "openai":
            return self.openai_model
        return None


@dataclass
class LegacyAirweaveConfig:
    """Compatibility shim for older code expecting Airweave config."""
    api_key: Optional[str] = None
    api_url: str = "https://api.airweave.ai"
    collection_id: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and self.collection_id)


@dataclass
class LegacyIntegrationConfig:
    enabled: bool = False
    api_key: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key)


@dataclass
class LegacyLinearConfig(LegacyIntegrationConfig):
    team_id: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.team_id)


@dataclass
class LegacySlackConfig(LegacyIntegrationConfig):
    channel_id: Optional[str] = None
    signing_secret: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.api_key) and bool(self.channel_id)


@dataclass
class WebhookConfig:
    """GitHub webhook configuration."""
    secret: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        return bool(self.secret)


@dataclass
class SupabaseConfig:
    """Supabase (PostgreSQL + pgvector) configuration."""
    url: Optional[str] = None
    service_role_key: Optional[str] = None
    database_url: Optional[str] = None
    
    @property
    def is_configured(self) -> bool:
        """Check if Supabase is configured with all required fields."""
        return bool(self.url and self.service_role_key and self.database_url)
    
    @property
    def use_supabase(self) -> bool:
        """Check if Supabase persistence should be used."""
        return self.is_configured


@dataclass
class Config:
    """
    Main application configuration.
    
    Collects all configuration from environment variables.
    Uses Groq for LLM tasks and ChromaDB for vector storage.
    Optionally uses Supabase for persistent storage (Phase 2).
    """
    # Required components
    groq: GroqConfig = field(default_factory=GroqConfig)
    chroma: ChromaDBConfig = field(default_factory=ChromaDBConfig)
    
    # Phase 2: Supabase for persistent storage
    supabase: SupabaseConfig = field(default_factory=SupabaseConfig)
    
    # Optional: GitHub for code context
    github: GitHubConfig = field(default_factory=GitHubConfig)

    # Legacy/backward-compatible integrations (Airweave, LLM, Slack)
    airweave: LegacyAirweaveConfig = field(default_factory=LegacyAirweaveConfig)
    llm: LLMConfig = field(default_factory=LLMConfig)
    slack: LegacySlackConfig = field(default_factory=LegacySlackConfig)
    
    # Data source (sample by default)
    data_source: DataSourceConfig = field(default_factory=DataSourceConfig)
    
    # GitHub webhook
    webhook: WebhookConfig = field(default_factory=WebhookConfig)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables."""
        cfg = cls(
            # Groq (required for semantic processing)
            groq=GroqConfig(
                api_key=os.getenv("GROQ_API_KEY"),
                model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
            ),
            
            # ChromaDB (always configured locally)
            chroma=ChromaDBConfig(
                persist_dir=os.getenv("CHROMA_PERSIST_DIR", "./data/chroma"),
            ),
            
            # Phase 2: Supabase (optional persistent storage)
            supabase=SupabaseConfig(
                url=os.getenv("SUPABASE_URL"),
                service_role_key=os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
                database_url=os.getenv("DATABASE_URL"),
            ),
            
            # GitHub (optional)
            github=GitHubConfig(
                enabled=os.getenv("GITHUB_ENABLED", "true").lower() == "true",
                token=os.getenv("GITHUB_TOKEN"),
                owner=os.getenv("GITHUB_OWNER"),
                repo=os.getenv("GITHUB_REPO"),
            ),
            
            # Data source
            data_source=DataSourceConfig(
                source_type=os.getenv("DATA_SOURCE", "sample").lower(),
                # Azure
                azure_workspace_id=os.getenv("AZURE_LOG_ANALYTICS_WORKSPACE_ID"),
                azure_client_id=os.getenv("AZURE_LOG_ANALYTICS_CLIENT_ID"),
                azure_client_secret=os.getenv("AZURE_LOG_ANALYTICS_CLIENT_SECRET"),
                azure_tenant_id=os.getenv("AZURE_LOG_ANALYTICS_TENANT_ID"),
                # Sentry
                sentry_auth_token=os.getenv("SENTRY_AUTH_TOKEN"),
                sentry_org_slug=os.getenv("SENTRY_ORG_SLUG"),
                sentry_project_slug=os.getenv("SENTRY_PROJECT_SLUG"),
                sentry_url=os.getenv("SENTRY_URL", "https://sentry.io"),
                # Datadog
                datadog_api_key=os.getenv("DATADOG_API_KEY"),
                datadog_app_key=os.getenv("DATADOG_APP_KEY"),
                datadog_site=os.getenv("DATADOG_SITE", "datadoghq.com"),
            ),
        )

        # Populate legacy integration fields for backward compatibility
        cfg.airweave = LegacyAirweaveConfig(
            api_key=os.getenv("AIRWEAVE_API_KEY"),
            api_url=os.getenv("AIRWEAVE_API_URL", "https://api.airweave.ai"),
            collection_id=os.getenv("AIRWEAVE_COLLECTION_ID"),
        )

        cfg.llm = LLMConfig(
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY"),
            openai_api_key=os.getenv("OPENAI_API_KEY"),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514"),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        )

        cfg.slack = LegacySlackConfig(
            enabled=os.getenv("SLACK_ENABLED", "false").lower() == "true",
            api_key=os.getenv("SLACK_BOT_TOKEN"),
            channel_id=os.getenv("SLACK_CHANNEL_ID") or os.getenv("SLACK_ALERT_CHANNEL", "#devant-alerts"),
            signing_secret=os.getenv("SLACK_SIGNING_SECRET"),
        )

        cfg.webhook = WebhookConfig(
            secret=os.getenv("GITHUB_WEBHOOK_SECRET"),
        )

        return cfg
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get configuration status for API/UI.
        
        Returns dict showing what's configured and active.
        """
        return {
            "groq": {
                "configured": self.groq.is_configured,
                "model": self.groq.model if self.groq.is_configured else None,
            },
            "chroma": {
                "configured": self.chroma.is_configured,
                "persist_dir": self.chroma.persist_dir,
            },
            "github": {
                "enabled": self.github.enabled,
                "configured": self.github.is_configured,
                "owner": self.github.owner if self.github.is_configured else None,
                "repo": self.github.repo if self.github.is_configured else None,
            },
            "data_source": {
                "type": self.data_source.source_type,
                "available": {
                    "sample": True,  # Always available
                    "azure": self.data_source.azure_configured,
                    "sentry": self.data_source.sentry_configured,
                    "datadog": self.data_source.datadog_configured,
                },
            },
        }


# Cached config instance
@lru_cache(maxsize=1)
def get_config() -> Config:
    """
    Get the application configuration.
    
    Loads from environment on first call, then returns cached instance.
    """
    return Config.from_env()


def reload_config() -> Config:
    """Force reload configuration from environment."""
    get_config.cache_clear()
    return get_config()
