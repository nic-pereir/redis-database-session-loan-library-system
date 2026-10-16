from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    # Redis / cache
    REDIS_URL: str = "redis://localhost:6379/0"
    CACHE_ENABLED: bool = True
    CACHE_TTL_SECONDS: int = 300         # 5 minutos

    # mostra no log o ciclo de vida da Session
    DEBUG_SESSION_LOG: bool = False

    # Regras de negócio da biblioteca
    LOAN_DAYS: int = 14                  # prazo inicial (e de cada renovação)
    MAX_ACTIVE_LOANS: int = 2            # empréstimos em aberto por usuário
    MAX_RENEWALS: int = 3                # renovações por empréstimo
    MAX_CONSECUTIVE_LOANS: int = 3       # mesmo livro "3 vezes seguidas"
    COOLDOWN_DAYS: int = 14         

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
