from abc import ABC, abstractmethod
from typing import Dict, Any, List


class BaseEvidenceBuilder(ABC):
    @abstractmethod
    def build_bundle(self, incident: Dict[str, Any], history: List[Dict[str, Any]]) -> Dict[str, Any]:
        ...
