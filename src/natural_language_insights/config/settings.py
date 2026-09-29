from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Export .env into the process environment: provider SDKs (LangChain integrations) read
# their API keys from os.environ, not from Settings. Real env vars take precedence.
load_dotenv()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_name: str = "Natural Language Insights Engine"
    app_version: str = "0.1.0"
    host: str = "0.0.0.0"
    port: int = 8080
    database_path: str = "data/database.db"
    upload_directory: str = "data/uploads"
    max_upload_mb: int = 500
    job_workers: int = 4
    # Any LangChain provider: "anthropic:claude-opus-5-5", "openai:gpt-5",
    # "google_genai:gemini-2.5-pro", "ollama:llama3.1", ...
    llm_model: str = "gpt-5.4-nano"
    llm_kwargs: dict = {}  # extra model settings, as JSON in the env var
    query_timeout_seconds: float = 30
    max_sql_attempts: int = 3  # model writes SQL, it fails, model sees the error and retries
    max_result_rows: int = 1000


settings = Settings()
