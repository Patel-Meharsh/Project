from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://postgres:password@localhost:5432/gateway_inventory"
    SECRET_KEY: str   = "CHANGE-ME-use-a-real-secret-in-production"
    ENVIRONMENT: str  = "development"   # development | production
    ALLOWED_ORIGINS: str = ""           # comma-separated, e.g. "https://app.yourdomain.com"

    class Config:
        env_file = ".env"

settings = Settings()
