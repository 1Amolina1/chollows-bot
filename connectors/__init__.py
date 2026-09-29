from .base import BaseConnector, Deal, NewsItem
from .wallapop import WallapopConnector
from .chollometro import ChollometroConnector
from .stores import OnlineStoresConnector
from .google_alerts import GoogleDealsConnector
from .news import TechNewsAggregator

__all__ = [
    "BaseConnector",
    "Deal",
    "NewsItem",
    "WallapopConnector",
    "ChollometroConnector",
    "OnlineStoresConnector",
    "GoogleDealsConnector",
    "TechNewsAggregator",
]
