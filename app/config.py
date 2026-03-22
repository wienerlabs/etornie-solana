from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Application
    app_name: str = "Etornie Backend"
    debug: bool = False

    # Database
    database_url: str

    # JWT
    jwt_secret: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    # Together AI
    together_api_key: str = ""
    together_model: str = "meta-llama/Llama-3-70b-chat-hf"
    together_embedding_model: str = "togethercomputer/m2-bert-80M-8k-retrieval"

    # File storage
    upload_dir: str = "./uploads"

    # CORS
    cors_origins: list[str] = ["http://localhost:3000"]


settings = Settings()  # type: ignore[call-arg]
