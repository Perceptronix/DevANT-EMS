from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseRegressionEngine(ABC):
    @abstractmethod
    async def detect_regression(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def compare_historical(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        ...

    @abstractmethod
    async def calculate_similarity(self, a: Dict[str, Any], b: Dict[str, Any]) -> float:
        ...
