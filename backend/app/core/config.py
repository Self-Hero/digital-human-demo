from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "digital-human-demo"
    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    cors_origins: str = "http://localhost:5173"

    asr_provider: str = "mock"
    llm_provider: str = "mock"
    tts_provider: str = "mock"
    avatar_provider: str = "mock"

    bailian_base_url: str = "https://dashscope.aliyuncs.com"
    bailian_api_key: str = ""
    bailian_realtime_model: str = "qwen-audio-3.0-realtime-plus"
    bailian_realtime_voice: str = "Cherry"

    llm_timeout_seconds: float = 30.0
    llm_system_prompt: str = "你是一个简洁、自然的中文数字人助手。"
    asr_language: str = "zh-CN"
    asr_sample_rate: int = 16_000
    tts_sample_rate: int = 16_000
    tts_audio_format: str = "pcm"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
