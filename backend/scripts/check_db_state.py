import sys
from pathlib import Path

# Ensure backend package root is on sys.path
BACKEND_ROOT = str(Path(__file__).resolve().parents[1])
if BACKEND_ROOT not in sys.path:
    sys.path.insert(0, BACKEND_ROOT)

from database.client import get_database_client
from database.repositories.entities import SignatureStateRepository, ErrorClusterRepository

client = get_database_client()
session = client.get_session()

sig_repo = SignatureStateRepository(session)
ec_repo = ErrorClusterRepository(session)

try:
    print('signature_states_count=', sig_repo.count())
    print('error_clusters_count=', ec_repo.count())
    sigs = sig_repo.get_all()[:10]
    for s in sigs:
        print(s.to_dict())
finally:
    session.close()
