from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+psycopg://postgres:root@localhost:5432/Inventory_Management"
    SECRET_KEY: str   = "J42fvvoUDpMyR61CXTQ1Pa2b92CsqxnXAKy6YjlJfzJa1RX8XlZ60uf9B5RZ0FCS"
    ENVIRONMENT: str  = "development"   # development | production
    ALLOWED_ORIGINS: str = ""           # comma-separated, e.g. "https://app.yourdomain.com"

    class Config:
        env_file = ".env"

settings = Settings()
