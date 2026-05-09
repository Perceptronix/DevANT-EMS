from abc import ABC, abstractmethod
from typing import Dict, Any


class BaseAnalyzer(ABC):
    @abstractmethod
    def analyze(self, incident: Dict[str, Any]) -> Dict[str, Any]:
        ...
