from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Database
    database_url: str = "postgresql+asyncpg://codebase:codebase@localhost:5432/codebase_intelligence"

    # OpenAI-compatible endpoint (chat / completions)
    openai_api_base: str = "https://api.openai.com/v1"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o"

    # Embedding endpoint (can differ from the chat endpoint)
    openai_embedding_base: str = "https://integrate.api.nvidia.com/v1"
    openai_embedding_api_key: str = ""
    openai_embedding_model: str = "nvidia/nemotron-3-embed-1b"

    # GitHub OAuth
    github_client_id: str = ""
    github_client_secret: str = ""

    # App
    secret_key: str = "change-me"
    frontend_url: str = "http://localhost:3000"
    backend_url: str = "http://localhost:8000"
    repos_dir: str = "./repos"
    port: int = 8001

    @property
    def repos_path(self) -> Path:
        p = Path(self.repos_dir)
        p.mkdir(parents=True, exist_ok=True)
        return p


settings = Settings()
