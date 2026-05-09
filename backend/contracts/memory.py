from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any


class BaseIncidentMemory(ABC):
    @abstractmethod
    async def store_incident(self, incident: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    async def find_similar(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def get_history(self, signature: str) -> List[Dict[str, Any]]:
        ...

    @abstractmethod
    async def mark_resolved(self, incident_id: str) -> None:
        ...


class BaseStateManager(ABC):
    @abstractmethod
    def update(self, key: str, value: Dict[str, Any]) -> None:
        ...

    @abstractmethod
    def get(self, key: str) -> Optional[Dict[str, Any]]:
        ...

    @abstractmethod
    def persist(self) -> None:
        ...
