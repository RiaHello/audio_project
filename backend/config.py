from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    bailian_api_key: str = ""
    bailian_asr_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_asr_model: str = "qwen3-asr-flash"
    bailian_tts_url: str = (
        "https://dashscope.aliyuncs.com/api/v1/services/aigc/multimodal-generation/generation"
    )
    bailian_tts_model: str = "qwen3-tts-flash"
    bailian_tts_voice: str = "Cherry"
    bailian_tts_language: str = "Chinese"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-v4-flash"

    amap_api_key: str = ""

    cors_origins: str = "http://localhost:5175,http://127.0.0.1:5175"
    audio_ttl_hours: int = 24

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()
