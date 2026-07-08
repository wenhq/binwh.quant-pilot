from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "mysql+asyncmy://root:password@127.0.0.1:3306/quantpilot"
    host: str = "0.0.0.0"
    port: int = 8000

    # JWT / cookie auth
    jwt_secret_key: str = "change-me-in-production-use-a-real-secret"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Guosen secondary data source (限免, may stop working).
    gs_api_key: str | None = None
    gs_api_base: str = "https://dgzt.guosen.com.cn/skills"

    # Rate-limited batch import knobs (avoid IP bans from akshare/Guosen).
    import_rate_seconds: float = 2.0
    import_concurrency: int = 2
    import_circuit_threshold: int = 5
    import_circuit_cooldown: float = 300.0  # 源熔断后冷却秒数

    # market_regime ML 超参 (见 docs/plans/2026-06-22-001 ML 闭环 plan)
    regime_n_components: int = 3            # HMM 状态数 (平静/动荡)
    regime_pca_variance: float = 0.95       # PCA 保留累计方差比例
    regime_vol_span: int = 21               # 实现波动率 ewm span (交易日)
    regime_return_windows: tuple[int, ...] = (5, 21, 63)  # 多周期收益率窗口
    regime_random_state: int = 42           # 可复现性

    # 定时行情同步 (上海时间)
    market_sync_hour: int = 15
    market_sync_minute: int = 5
    market_sync_retry_minutes: int = 30

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
