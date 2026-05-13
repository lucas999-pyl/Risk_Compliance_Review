from __future__ import annotations

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "化工合规 RAG 工具"
    database_path: str = "data/risk-review.db"
    storage_dir: str = "data/objects"
    enable_llm: bool = Field(default=False, validation_alias=AliasChoices("RCR_ENABLE_LLM", "ENABLE_LLM"))
    openai_compatible_base_url: str | None = Field(default=None, validation_alias="OPENAI_API_BASE")
    openai_compatible_api_key: str | None = Field(default=None, validation_alias="OPENAI_API_KEY")
    chem_rag_embedding_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEM_RAG_EMBEDDING_BASE_URL", "OPENAI_API_BASE"),
    )
    chem_rag_embedding_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEM_RAG_EMBEDDING_API_KEY", "OPENAI_API_KEY"),
    )
    chem_rag_llm_base_url: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEM_RAG_LLM_BASE_URL", "OPENAI_API_BASE"),
    )
    chem_rag_llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("CHEM_RAG_LLM_API_KEY", "OPENAI_API_KEY"),
    )
    chem_rag_embedding_provider: str = "qwen"
    chem_rag_embedding_model: str = "text-embedding-v4"
    chem_rag_embedding_dimensions: int = 1024
    chem_rag_llm_provider: str = "qwen"
    chem_rag_llm_model: str = "qwen3.6-plus"
    chem_rag_vector_store_dir: str = "data/vector_store/chemical_rag"
    chem_rag_request_timeout_seconds: float = 20.0

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", populate_by_name=True)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return init_settings, dotenv_settings, env_settings, file_secret_settings
