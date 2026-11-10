import os
from pathlib import Path
from typing import Optional

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(_ENV_FILE, ".env"),
        extra="ignore",
    )

    # LLM Provider selection & common options
    llm_provider: str = Field(
        default="mistral",
        validation_alias=AliasChoices("LLM_PROVIDER", "llm_provider"),
    )
    llm_timeout: int = Field(
        default=30,
        validation_alias=AliasChoices("LLM_TIMEOUT", "llm_timeout"),
    )
    llm_max_tokens: Optional[int] = Field(
        default=1024,
        validation_alias=AliasChoices("LLM_MAX_TOKENS", "llm_max_tokens"),
    )
    model: str = Field(
        default="",
        validation_alias=AliasChoices("MODEL", "model"),
    )

    # Mistral AI
    mistral_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("MISTRAL_API_KEY", "MISTRALAI_API_KEY", "mistral_api_key"),
    )
    mistral_model: str = Field(
        default="mistral-small-latest",
        validation_alias=AliasChoices("MISTRAL_MODEL", "mistral_model"),
    )

    # Groq
    groq_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GROQ_API_KEY", "groq_api_key"),
    )
    groq_model: str = Field(
        default="llama-3.3-70b-versatile",
        validation_alias=AliasChoices("GROQ_MODEL", "groq_model"),
    )

    # Ollama
    ollama_model: str = Field(
        default="beam:cloud",
        validation_alias=AliasChoices("OLLAMA_MODEL", "ollama_model"),
    )
    ollama_base_url: str = Field(
        default="https://ollama.com",
        validation_alias=AliasChoices("OLLAMA_BASE_URL", "ollama_base_url"),
    )
    ollama_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OLLAMA_API_KEY", "ollama_api_key"),
    )

    # Gemini / Google Generative AI
    gemini_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GEMINI_API_KEY", "GOOGLE_API_KEY", "gemini_api_key"),
    )
    google_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("GOOGLE_API_KEY", "GEMINI_API_KEY", "google_api_key"),
    )
    gemini_model: str = Field(
        default="gemini-3.8-flash",
        validation_alias=AliasChoices("GEMINI_MODEL", "gemini_model"),
    )

    # OpenRouter
    openrouter_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("OPENROUTER_API_KEY", "openrouter_api_key"),
    )
    openrouter_model: str = Field(
        default="Nemotron 3 Nano Omni",
        validation_alias=AliasChoices("OPENROUTER_MODEL", "openrouter_model"),
    )

    # Hugging Face
    huggingface_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("HUGGINGFACE_API_KEY", "HF_TOKEN", "huggingface_api_key"),
    )
    huggingface_model: str = Field(
        default="",
        validation_alias=AliasChoices("HUGGINGFACE_MODEL", "huggingface_model"),
    )

    # PayPal REST app credentials. Never commit real values.
    paypal_client_id: str = Field(default="", alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(default="", alias="PAYPAL_CLIENT_SECRET")
    paypal_api_base: str = Field(
        default="https://api-m.sandbox.paypal.com", alias="PAYPAL_API_BASE"
    )
    paypal_webhook_id: str = Field(default="", alias="PAYPAL_WEBHOOK_ID")
    paypal_webhook_ids: str = Field(default="", alias="PAYPAL_WEBHOOK_IDS")
    paypal_business_email: str = Field(default="", alias="PAYPAL_EMAIL")

    eleven_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("ELEVENLABS_API_KEY", "ELEVEN_LAB_API_KEY", "eleven_api_key"),
    )
    twilo_account_sid: str = Field(default="", alias="TWILO_ACCOUNT_SID")
    twilo_auth_token: str = ""
    resend_api_key: str = ""
    twilo_whatsapp_number: str = ""
    max_discount: int = Field(default=30, alias="MAX_DISCOUNT_ALLOWED")
    min_discount: int = Field(default=5, alias="MIN_DISCOUNT_ALLOWED")
    redis_url: str = Field(default="", alias="REDIS_URL")
    postgres_url: str = ""
    database_url: str = ""
    db_pool_size: int = 50
    db_max_overflow: int = 50
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800
    db_checkpointer_pool_size: int = 20
    frontend_url: str = ""
    backend_url: str = ""
    demo_mode: bool = False
    port: int = 8000
    max_grace_period: int = 7

    # Recovery policy: auto loads the trained artifact when present, otherwise
    # serves the deterministic rules baseline. Set to "rules" to force it.
    policy_engine: str = Field(default="auto", alias="POLICY_ENGINE")
    policy_exploration: float = Field(default=0.0, alias="POLICY_EXPLORATION")

    # Global outreach window, expressed in the merchant's local clock.
    contact_window_start_hour: int = Field(default=9, alias="CONTACT_WINDOW_START_HOUR")
    contact_window_end_hour: int = Field(default=21, alias="CONTACT_WINDOW_END_HOUR")

    @property
    def webhook_ids(self) -> list[str]:
        raw = ",".join(filter(None, [self.paypal_webhook_id, self.paypal_webhook_ids]))
        return [item.strip() for item in raw.split(",") if item.strip()]


settings = Settings()

# Sync loaded keys into os.environ for libraries expecting standard environment variables
if settings.mistral_api_key and "MISTRAL_API_KEY" not in os.environ:
    os.environ["MISTRAL_API_KEY"] = settings.mistral_api_key
if settings.gemini_api_key:
    if "GEMINI_API_KEY" not in os.environ:
        os.environ["GEMINI_API_KEY"] = settings.gemini_api_key
    if "GOOGLE_API_KEY" not in os.environ:
        os.environ["GOOGLE_API_KEY"] = settings.gemini_api_key
if settings.groq_api_key and "GROQ_API_KEY" not in os.environ:
    os.environ["GROQ_API_KEY"] = settings.groq_api_key
if settings.huggingface_api_key and "HUGGINGFACE_API_KEY" not in os.environ:
    os.environ["HUGGINGFACE_API_KEY"] = settings.huggingface_api_key
if settings.openrouter_api_key and "OPENROUTER_API_KEY" not in os.environ:
    os.environ["OPENROUTER_API_KEY"] = settings.openrouter_api_key
