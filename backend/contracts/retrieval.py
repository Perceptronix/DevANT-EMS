from abc import ABC, abstractmethod
from typing import List, Dict, Any


class BaseRetriever(ABC):
    @abstractmethod
    async def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def rank(self, candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        ...
