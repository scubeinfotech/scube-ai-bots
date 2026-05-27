"""
Application configuration and settings
"""
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings

# Make .env values available via os.getenv for modules outside BaseSettings.
load_dotenv()


class Settings(BaseSettings):
    """Application settings"""
    
    # API Configuration
    api_title: str = "Centralized LLM Platform API"
    api_version: str = "0.1.0"
    api_secret_key: str = os.getenv("API_SECRET_KEY", "dev-secret-key-change-in-prod")
    
    # Database Configuration
    database_url: str = os.getenv(
        "DATABASE_URL",
        "postgresql://llmuser:changeme123@localhost:5432/llm_chatbot"
    )
    
    # LLM Configuration
    ollama_url: str = os.getenv("OLLAMA_URL", "http://localhost:11434")
    default_model: str = os.getenv("DEFAULT_MODEL", "llama3.1:8b")
    llm_provider: str = os.getenv("LLM_PROVIDER", "mock")
    llm_primary: str = os.getenv("LLM_PRIMARY", "groq")
    llm_secondary: str = os.getenv("LLM_SECONDARY", "gemini")
    llm_tertiary: str = os.getenv("LLM_TERTIARY", "openrouter")
    llm_provider_timeout_ms: int = int(os.getenv("LLM_PROVIDER_TIMEOUT_MS", "3000"))
    llm_max_retries: int = int(os.getenv("LLM_MAX_RETRIES", "1"))
    llm_groq_model: str = os.getenv("LLM_GROQ_MODEL", "llama-3.3-70b-versatile")
    llm_gemini_model: str = os.getenv("LLM_GEMINI_MODEL", "gemini-1.5-flash")
    llm_openai_model: str = os.getenv("LLM_OPENAI_MODEL", "gpt-4o-mini")
    llm_openrouter_model: str = os.getenv("LLM_OPENROUTER_MODEL", "openai/gpt-4o-mini")
    
    # Environment
    environment: str = os.getenv("ENVIRONMENT", "development")
    debug: bool = environment == "development"
    
    # CORS (raw string; parsed in app.main)
    allowed_origins: str = "*"

    # Conversation history window included in each LLM prompt.
    # Kept conservative by default; total history is still capped by
    # `chat_history_char_budget` to avoid blowing token limits.
    chat_history_turns: int = int(os.getenv("CHAT_HISTORY_TURNS", "10"))
    chat_history_char_budget: int = int(os.getenv("CHAT_HISTORY_CHAR_BUDGET", "4000"))

    # Allow chat requests whose Origin/Referer points at localhost or a
    # private RFC1918 IP to bypass the per-tenant domain allowlist. Useful in
    # development; should be disabled in production by setting
    # ``ALLOW_LOCAL_ORIGINS=false`` in the tenant's .env.
    allow_local_origins: bool = os.getenv("ALLOW_LOCAL_ORIGINS", "true").strip().lower() in ("1", "true", "yes")

    # Email / SMTP Configuration (for OTP verification during onboarding)
    smtp_host: str = os.getenv("SMTP_HOST", "")
    smtp_port: int = int(os.getenv("SMTP_PORT", "587"))
    smtp_user: str = os.getenv("SMTP_USER", "")
    smtp_password: str = os.getenv("SMTP_PASSWORD", "")
    smtp_from_email: str = os.getenv("SMTP_FROM_EMAIL", "noreply@scubeinfotech.com.sg")
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "SCUBE AI Onboarding")
    smtp_tls: bool = os.getenv("SMTP_TLS", "true").strip().lower() in ("1", "true", "yes")

    # Google OAuth Configuration
    google_client_id: str = os.getenv("GOOGLE_CLIENT_ID", "")
    google_client_secret: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    google_redirect_uri: str = os.getenv("GOOGLE_REDIRECT_URI", "http://localhost:8001/api/public/auth/google/callback")

    # WhatsApp Configuration
    whatsapp_access_token: str = os.getenv("WHATSAPP_ACCESS_TOKEN", "")
    whatsapp_phone_number_id: str = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "")
    whatsapp_business_account_id: str = os.getenv("WHATSAPP_BUSINESS_ACCOUNT_ID", "")
    whatsapp_verify_token: str = os.getenv("WHATSAPP_VERIFY_TOKEN", "my_secure_verify_token")

    # RAG retrieval tuning. ``rag_min_score`` is the minimum cosine-ish
    # similarity a chunk must clear to be injected into the prompt; weak
    # chunks below this threshold are dropped to reduce noise. The char
    # budget caps how much retrieved text we splice into the prompt so
    # we don't blow the LLM context window on long-tail crawls.
    rag_min_score: float = float(os.getenv("RAG_MIN_SCORE", "0.05"))
    rag_context_char_budget: int = int(os.getenv("RAG_CONTEXT_CHAR_BUDGET", "1500"))

    circuit_breaker_enabled: bool = os.getenv("CIRCUIT_BREAKER_ENABLED", "true").strip().lower() in ("1", "true", "yes")
    circuit_breaker_threshold: int = int(os.getenv("CIRCUIT_BREAKER_THRESHOLD", "3"))
    circuit_breaker_timeout: int = int(os.getenv("CIRCUIT_BREAKER_TIMEOUT", "60"))

    response_validator_enabled: bool = os.getenv("RESPONSE_VALIDATOR_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    pii_sanitizer_enabled: bool = os.getenv("PII_SANITIZER_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    semantic_cache_enabled: bool = os.getenv("SEMANTIC_CACHE_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    response_feedback_enabled: bool = os.getenv("RESPONSE_FEEDBACK_ENABLED", "false").strip().lower() in ("1", "true", "yes")
    llm_ab_test_percentage: int = int(os.getenv("LLM_AB_TEST_PERCENTAGE", "0"))

    redis_url: str = os.getenv("REDIS_URL", "")

    class Config:
        case_sensitive = False
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()
