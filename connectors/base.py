from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class Deal:
    title: str
    price: float
    url: str
    source: str
    deal_id: str
    original_price: Optional[float] = None
    discount_pct: Optional[int] = None
    location: str = ""
    image_url: str = ""
    extra: Dict[str, Any] = field(default_factory=dict)

    def formatted_price(self) -> str:
        if self.price == 0.0:
            return "GRATIS"
        return f"{self.price:.2f}€"


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    topic: str
    published_at: str
    news_id: str
    summary: str = ""


class BaseConnector(ABC):
    """
    Interfície comuna per a tots els connectors de cerca de cholls/ofertes.
    Permet afegir noves fonts sense modificar la lògica principal de cerca ni el report.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Nom identificador de la font (ex: 'Wallapop', 'Chollometro', 'Amazon')"""
        pass

    @abstractmethod
    def search(self, product: str, alternative_names: List[str], max_price: float) -> List[Deal]:
        """
        Cerca ofertes per al producte i la seva llista de variants intel·ligents
        garantint que no superin el preu màxim especificat.
        """
        pass
