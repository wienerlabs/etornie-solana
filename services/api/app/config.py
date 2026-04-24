from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Application
    app_name: str = "Etornie Solana Backend"
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
    together_embedding_model: str = "intfloat/multilingual-e5-large-instruct"

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

    # Groq (EtornieGPT)
    groq_api_key: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    # EUIPO API
    euipo_api_key: str = ""
    euipo_api_secret: str = ""
    euipo_base_url: str = "https://api-sandbox.euipo.europa.eu"
    euipo_auth_url: str = "https://auth-sandbox.euipo.europa.eu/oidc/accessToken"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # File storage
    upload_dir: str = "./uploads"

    # CORS
    cors_origins: list[str]

    # Solana
    solana_cluster_url: str = "https://api.devnet.solana.com"
    solana_operator_key_path: str = "keys/operator.json"
    solana_attestation_program_id: str = (
        "CpLYWQn39xw1Qei1fqcDF8NkJGiJsME2dKpAfzkN1T2X"
    )
    solana_attestation_enabled: bool = True
    solana_nft_program_id: str = (
        "6WrZ6NmuQtfpufrLbk5prQCKuF4isX1JwbrvxGFxT2gF"
    )
    solana_nft_enabled: bool = True
    solana_zk_verifier_program_id: str = (
        "GCnpSrJ1W8SXPZ94FbYy4xs5kNZEAQuiDD7Nqk4nwSk5"
    )
    solana_zk_verifier_enabled: bool = True
    api_public_url: str = "http://localhost:8000"

    # EtornieGPT x402 payment flow (Faz 5.6)
    etorniegpt_payment_vault: str = ""
    etorniegpt_payment_lamports: int = 100_000  # 0.0001 SOL ~ $0.02


settings = Settings()  # type: ignore[call-arg]
