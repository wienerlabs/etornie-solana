from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
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

    # Together AI (embeddings for RAG)
    together_api_key: str = ""
    together_model: str = "meta-llama/Llama-3-70b-chat-hf"
    together_embedding_model: str = "togethercomputer/m2-bert-80M-8k-retrieval"

    # Groq (EtornieGPT)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # WhatsApp Business API
    whatsapp_api_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_business_account_id: str = ""
    whatsapp_api_version: str = "v22.0"

    # EmailJS
    emailjs_public_key: str = ""
    emailjs_private_key: str = ""
    emailjs_service_id: str = ""
    emailjs_template_id: str = ""  # OTP verification
    emailjs_case_template_id: str = ""  # New case notification

    # File storage
    upload_dir: str = "./uploads"

    # CORS
    cors_origins: list[str]


settings = Settings()  # type: ignore[call-arg]
