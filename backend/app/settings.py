from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Prefer backend/.env, but also allow repo-root .env (common in this project).
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    neo4j_uri: str = Field(default="bolt://localhost:7687", validation_alias=AliasChoices("NEO4J_URI"))
    neo4j_user: str = Field(default="neo4j", validation_alias=AliasChoices("NEO4J_USER", "NEO4J_USERNAME"))
    neo4j_password: str = Field(default="neo4j_password", validation_alias=AliasChoices("NEO4J_PASSWORD"))

    # LLM config (default: DeepSeek via OpenAI-compatible API).
    llm_provider: str = Field(
        default="deepseek",
        description="deepseek | openrouter | openai",
        validation_alias=AliasChoices("LLM_PROVIDER"),
    )
    llm_base_url: str | None = Field(default=None, validation_alias=AliasChoices("LLM_BASE_URL"))
    llm_api_key: str | None = Field(default=None, validation_alias=AliasChoices("LLM_API_KEY"))
    llm_model: str = Field(default="deepseek-chat", validation_alias=AliasChoices("LLM_MODEL"))

    # Keys (read from env). We'll select based on llm_provider unless llm_api_key is set.
    deepseek_api_key: str | None = Field(default=None, validation_alias=AliasChoices("DEEPSEEK_API_KEY", "DEEPSEEK_KEY"))
    openrouter_api_key: str | None = Field(
        default=None, validation_alias=AliasChoices("OPENROUTER_API_KEY", "OPENROUTER_KEY")
    )
    openai_api_key: str | None = Field(default=None, validation_alias=AliasChoices("OPENAI_API_KEY"))

    # Embeddings (required for RAG, similarity, clustering, FAISS). System will fail with clear errors if not configured.
    embedding_provider: str | None = Field(
        default=None,
        description="siliconflow | openai | openrouter | deepseek | (None will cause errors in core features)",
        validation_alias=AliasChoices("EMBEDDING_PROVIDER"),
    )
    embedding_base_url: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_BASE_URL"))
    embedding_api_key: str | None = Field(default=None, validation_alias=AliasChoices("EMBEDDING_API_KEY"))
    embedding_model: str | None = Field(
        default="text-embedding-3-small",
        validation_alias=AliasChoices("EMBEDDING_MODEL"),
    )

    siliconflow_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("SILICONFLOW_API_KEY", "SILICON_FLOW_API_KEY", "SILICONCLOUD_API_KEY"),
    )

    # Phase1 extraction gate controls (quality-first pipeline).
    phase1_gate_allow_weak: bool = Field(
        default=False,
        validation_alias=AliasChoices("PHASE1_GATE_ALLOW_WEAK"),
    )

    # P1-Top3: Group-layer clustering control
    group_clustering_threshold: float = Field(
        default=0.85,
        validation_alias=AliasChoices("GROUP_CLUSTERING_THRESHOLD"),
    )
    group_clustering_method: str = Field(
        default="hybrid",
        validation_alias=AliasChoices("GROUP_CLUSTERING_METHOD"),
    )

    ingest_llm_max_workers: int = Field(
        default=4,
        validation_alias=AliasChoices("INGEST_LLM_MAX_WORKERS"),
    )

    ingest_llm_heartbeat_seconds: int = Field(
        default=20,
        validation_alias=AliasChoices("INGEST_LLM_HEARTBEAT_SECONDS"),
    )

    llm_timeout_seconds: int = Field(
        default=60,
        validation_alias=AliasChoices("LLM_TIMEOUT_SECONDS"),
    )

    llm_client_max_retries: int = Field(
        default=0,
        validation_alias=AliasChoices("LLM_CLIENT_MAX_RETRIES"),
    )

    rag_llm_timeout_seconds: int = Field(
        default=45,
        validation_alias=AliasChoices("RAG_LLM_TIMEOUT_SECONDS"),
    )

    rag_llm_max_tokens: int = Field(
        default=900,
        validation_alias=AliasChoices("RAG_LLM_MAX_TOKENS"),
    )

    pageindex_enabled: bool = Field(
        default=False,
        validation_alias=AliasChoices("PAGEINDEX_ENABLED"),
    )

    pageindex_index_dir: str = Field(
        default="storage/pageindex",
        validation_alias=AliasChoices("PAGEINDEX_INDEX_DIR"),
    )

    neo4j_connection_timeout_seconds: float = Field(
        default=15.0,
        validation_alias=AliasChoices("NEO4J_CONNECTION_TIMEOUT_SECONDS"),
    )

    # ── Parallel processing controls ──

    phase1_chunk_claim_max_workers: int = Field(
        default=4, ge=1, le=8,
        validation_alias=AliasChoices("PHASE1_CHUNK_CLAIM_MAX_WORKERS"),
    )

    phase1_grounding_max_workers: int = Field(
        default=2, ge=1, le=6,
        validation_alias=AliasChoices("PHASE1_GROUNDING_MAX_WORKERS"),
    )

    phase2_conflict_max_workers: int = Field(
        default=3, ge=1, le=6,
        validation_alias=AliasChoices("PHASE2_CONFLICT_MAX_WORKERS"),
    )

    ingest_pre_llm_max_workers: int = Field(
        default=4, ge=1, le=8,
        validation_alias=AliasChoices("INGEST_PRE_LLM_MAX_WORKERS"),
    )

    faiss_embed_max_workers: int = Field(
        default=3, ge=1, le=6,
        validation_alias=AliasChoices("FAISS_EMBED_MAX_WORKERS"),
    )

    llm_global_max_concurrent: int = Field(
        default=16, ge=1, le=32,
        validation_alias=AliasChoices("LLM_GLOBAL_MAX_CONCURRENT"),
    )

    data_root: str = ".."
    storage_dir: str = "storage"

    # ── Textbook / autoyoutu integration ──

    autoyoutu_dir: str = Field(
        default="",
        description="Path to autoyoutu project directory",
        validation_alias=AliasChoices("AUTOYOUTU_DIR"),
    )
    youtu_ssh_host: str = Field(
        default="", validation_alias=AliasChoices("YOUTU_SSH_HOST"),
    )
    youtu_ssh_user: str = Field(
        default="", validation_alias=AliasChoices("YOUTU_SSH_USER"),
    )
    youtu_ssh_key_path: str = Field(
        default="", validation_alias=AliasChoices("YOUTU_SSH_KEY_PATH"),
    )
    textbook_youtu_schema: str = Field(
        default="textbook_dem",
        validation_alias=AliasChoices("TEXTBOOK_YOUTU_SCHEMA"),
    )
    textbook_chapter_max_tokens: int = Field(
        default=8000, ge=1000, le=64000,
        validation_alias=AliasChoices("TEXTBOOK_CHAPTER_MAX_TOKENS"),
    )
    discovery_prompt_policy_path: str = Field(
        default="storage/discovery/prompt_policy_bandit.json",
        validation_alias=AliasChoices("DISCOVERY_PROMPT_POLICY_PATH"),
    )
    global_community_version: str = Field(
        default="v1",
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_VERSION"),
    )
    global_community_max_nodes: int = Field(
        default=50000,
        ge=100,
        le=500000,
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_MAX_NODES"),
    )
    global_community_max_edges: int = Field(
        default=100000,
        ge=100,
        le=1000000,
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_MAX_EDGES"),
    )
    global_community_top_keywords: int = Field(
        default=8,
        ge=1,
        le=50,
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_TOP_KEYWORDS"),
    )
    global_community_tree_comm_embedding_model: str = Field(
        default="all-MiniLM-L6-v2",
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_TREE_COMM_EMBEDDING_MODEL"),
    )
    global_community_tree_comm_struct_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        validation_alias=AliasChoices("GLOBAL_COMMUNITY_TREE_COMM_STRUCT_WEIGHT"),
    )

    def effective_llm_api_key(self) -> str | None:
        if self.llm_api_key:
            return self.llm_api_key
        if self.llm_provider == "deepseek":
            return self.deepseek_api_key or self.openai_api_key
        if self.llm_provider == "openrouter":
            return self.openrouter_api_key or self.openai_api_key
        if self.llm_provider == "openai":
            return self.openai_api_key
        return self.openai_api_key or self.deepseek_api_key or self.openrouter_api_key

    def effective_llm_base_url(self) -> str | None:
        if self.llm_base_url:
            return self.llm_base_url
        if self.llm_provider == "deepseek":
            return "https://api.deepseek.com/v1"
        if self.llm_provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        return None

    def effective_embedding_api_key(self) -> str | None:
        if self.embedding_api_key:
            return self.embedding_api_key
        provider = self.effective_embedding_provider()
        if provider == "siliconflow":
            return self.siliconflow_api_key
        if provider == "openrouter":
            return self.openrouter_api_key or self.openai_api_key
        if provider == "deepseek":
            return self.deepseek_api_key or self.openai_api_key
        if provider == "openai":
            return self.openai_api_key
        # default: try whatever exists
        return self.openai_api_key or self.siliconflow_api_key or self.openrouter_api_key or self.deepseek_api_key

    def effective_embedding_base_url(self) -> str | None:
        if self.embedding_base_url:
            return self.embedding_base_url
        provider = self.effective_embedding_provider()
        if provider == "siliconflow":
            # SiliconFlow publishes both .cn and .com endpoints; default to .cn but allow override via EMBEDDING_BASE_URL.
            return "https://api.siliconflow.cn/v1"
        if provider == "openrouter":
            return "https://openrouter.ai/api/v1"
        if provider == "deepseek":
            return "https://api.deepseek.com/v1"
        return None

    def effective_embedding_provider(self) -> str:
        explicit = (self.embedding_provider or "").lower().strip()
        if explicit:
            return explicit
        # inference: if a dedicated key is present, assume that provider
        if self.siliconflow_api_key:
            return "siliconflow"
        if self.openai_api_key:
            return "openai"
        if self.openrouter_api_key:
            return "openrouter"
        if self.deepseek_api_key:
            return "deepseek"
        return ""

    def effective_embedding_model(self) -> str | None:
        provider = self.effective_embedding_provider()
        if provider == "siliconflow":
            # If user didn't explicitly set a model, prefer BGE-M3 as requested.
            if self.embedding_model and self.embedding_model != "text-embedding-3-small":
                return self.embedding_model
            return "BAAI/bge-m3"
        return self.embedding_model


settings = Settings()
