import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    # API security key (used by Chrome extension)
    API_KEY: str = Field(..., description="API key used to authenticate requests from Chrome Extension")

    # GitHub configuration
    GITHUB_TOKEN: str = Field(..., description="GitHub Personal Access Token with repo scope")
    GITHUB_WEBHOOK_SECRET: str = Field("", description="Secret for validating webhook HMAC signatures")
    CHANGELOG_REPO: str = Field(..., description="Separate repository name (owner/repo) where changelog.txt is pushed")

    # NVIDIA NIM configuration
    NVIDIA_NIM_API_KEY: str = Field(..., description="NVIDIA NIM API key")
    NVIDIA_NIM_BASE_URL: str = Field("https://integrate.api.nvidia.com/v1", description="NVIDIA NIM base API URL")
    NVIDIA_NIM_MODEL: str = Field("meta/llama-3.1-70b-instruct", description="LLM model name to use on NVIDIA NIM")

    # Additional AI Provider configuration (Free Tiers)
    GEMINI_API_KEY: str = Field("", description="Google Gemini API key")
    GROQ_API_KEY: str = Field("", description="Groq API key")
    OPENROUTER_API_KEY: str = Field("", description="OpenRouter API key")
    OLLAMA_BASE_URL: str = Field("http://localhost:11434/v1", description="Local Ollama base URL")

    # Jenkins configuration
    JENKINS_API_TOKEN: str = Field("", description="Jenkins API token for triggering pipelines")

    # App configuration
    BRD_FILE_PATH: str = Field("./brd/requirements.md", description="Path to the Business Requirement Document")
    DATABASE_URL: str = Field("sqlite+aiosqlite:///./data/capsule.db", description="Database connection URL")
    LOG_LEVEL: str = Field("INFO", description="Log level (DEBUG, INFO, WARNING, ERROR)")
    CLOUDFLARE_WORKER_URL: str = Field("http://localhost:8787", description="Cloudflare Worker URL for image generation and summaries")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

settings = Settings()

# Clean up any Byte Order Mark (BOM) or extra whitespaces introduced by terminal encoding/piping
for field_name in settings.model_fields:
    val = getattr(settings, field_name)
    if isinstance(val, str):
        setattr(settings, field_name, val.lstrip("\ufeff").strip())

