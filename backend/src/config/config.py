import os
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(_ENV_FILE, ".env"), extra="ignore")

    mistral_api_key: str = Field(default="", alias="MISTRAL_API_KEY")

    # PayPal REST app credentials. Never commit real values.
    paypal_client_id: str = Field(default="", alias="PAYPAL_CLIENT_ID")
    paypal_client_secret: str = Field(default="", alias="PAYPAL_CLIENT_SECRET")
    paypal_api_base: str = Field(
        default="https://api-m.sandbox.paypal.com", alias="PAYPAL_API_BASE"
    )
    paypal_webhook_id: str = Field(default="", alias="PAYPAL_WEBHOOK_ID")
    paypal_webhook_ids: str = Field(default="", alias="PAYPAL_WEBHOOK_IDS")
    paypal_business_email: str = Field(default="", alias="PAYPAL_EMAIL")

    eleven_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    twilo_account_sid: str = Field(default="", alias="TWILO_ACCOUNT_SID")
    twilo_auth_token: str = ""
    resend_api_key: str = ""
    twilo_whatsapp_number: str = ""
    model: str = ""
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
if settings.mistral_api_key and "MISTRAL_API_KEY" not in os.environ:
    os.environ["MISTRAL_API_KEY"] = settings.mistral_api_key
