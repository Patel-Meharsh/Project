from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Keep credentials out of source control. Define both values in Backend/.env.
    # With psycopg2-binary installed, use postgresql:// or postgresql+psycopg2://.
    DATABASE_URL: str
    SECRET_KEY: str
    ENVIRONMENT: str = "development"
    ALLOWED_ORIGINS: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


settings = Settings()
