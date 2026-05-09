from typing import Dict, List
from pathlib import Path

# Simple service ownership map; in practice parse CODEOWNERS
SERVICE_OWNERS: Dict[str, List[str]] = {
    "auth-service": ["alice"],
    "payments": ["bob"]
}


def parse_codeowners(path: str) -> Dict[str, List[str]]:
    p = Path(path)
    mapping = {}
    if not p.exists():
        return mapping
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) >= 2:
            pattern = parts[0]
            owners = [o.lstrip("@") for o in parts[1:]]
            mapping[pattern] = owners
    return mapping


def owners_for_service(service: str) -> List[str]:
    return SERVICE_OWNERS.get(service, [])
