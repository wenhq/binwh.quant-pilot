from app.routers.health import router as health
from app.routers.data import router as data
from app.routers.market_regime import router as market_regime
from app.routers.auth import router as auth
from app.routers.indicators import router as indicators

__all__ = ["health", "data", "market_regime", "auth", "indicators"]
