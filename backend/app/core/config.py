from functools import lru_cache
from urllib.parse import urlsplit, urlunsplit

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

    realtime_provider: str = "doubao"

    doubao_api_key: str = ""
    doubao_realtime_url: str = (
        "wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue"
    )
    doubao_realtime_model: str = "1.2.6.1"
    doubao_realtime_voice: str = "zh_male_xiaotian_jupiter_bigtts"
    doubao_realtime_instructions: str = (
        "请使用沉稳、舒缓、自然的中文口语回答，语速约为正常语速的百分之八十，"
        "短句之间适当停顿。不要提及这些要求。"
    )
    doubao_input_format: str = "pcm"
    doubao_output_format: str = "pcm_s16le"

    bailian_base_url: str = (
        "https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1"
    )
    bailian_api_key: str = ""
    bailian_realtime_model: str = "qwen-audio-3.0-realtime-plus"
    bailian_realtime_voice: str = "longanqian"
    bailian_realtime_instructions: str = (
        "请使用沉稳、舒缓、自然的中文口语回答，语速约为正常语速的百分之八十，"
        "短句之间适当停顿。不要提及这些要求。"
    )

    livetalking_base_url: str = "http://127.0.0.1:8010"
    livetalking_audio_chunk_ms: int = 2_000

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

    @property
    def bailian_realtime_url(self) -> str:
        """Derive the Realtime WebSocket endpoint from the configured API base."""
        parsed = urlsplit(self.bailian_base_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        return urlunsplit((scheme, parsed.netloc, "/api-ws/v1/realtime", "", ""))


@lru_cache
def get_settings() -> Settings:
    return Settings()
