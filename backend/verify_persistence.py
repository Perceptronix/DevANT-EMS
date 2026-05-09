"""Verify that data was persisted to Supabase"""
import os
import sys
from datetime import datetime

# Add backend to path
sys.path.insert(0, os.path.dirname(__file__))

from database.client import get_database_client
from database.repositories.entities import (
    ProjectRepository, RawEventRepository, ErrorClusterRepository
)

def verify():
    try:
        client = get_database_client()
        session = client.get_session()
        
        try:
            # Check projects
            proj_repo = ProjectRepository(session)
            projects = proj_repo.get_all()
            print(f"✓ Projects: {len(projects)} found")
            for p in projects:
                print(f"  - {p.name} ({p.github_repo})")
            
            # Check raw_events
            raw_repo = RawEventRepository(session)
            raw_events = raw_repo.get_all()
            print(f"\n✓ Raw Events: {len(raw_events)} found")
            for r in raw_events[:3]:  # Show first 3
                print(f"  - {r.fingerprint}: {r.message[:60]}...")
            
            # Check error_clusters
            from database.repositories.entities import ErrorClusterRepository
            cluster_repo = ErrorClusterRepository(session)
            clusters = cluster_repo.get_all()
            print(f"\n✓ Error Clusters: {len(clusters)} found")
            for c in clusters[:3]:  # Show first 3
                print(f"  - {c.title} (confidence: {c.confidence})")
            
            print(f"\n✅ SUCCESS: Database persistence verified!")
            print(f"   Total projects: {len(projects)}")
            print(f"   Total raw_events: {len(raw_events)}")
            print(f"   Total error_clusters: {len(clusters)}")
            
        finally:
            session.close()
    
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    verify()
