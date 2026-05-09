"""
Phase 2 Database Setup Script

Runs migrations, enables pgvector, creates all tables, and verifies connection.
"""
import os
import sys
import logging
from pathlib import Path

# Add backend directory to path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Load .env file
try:
    from dotenv import load_dotenv
    env_file = Path(__file__).parent.parent.parent / ".env"
    if env_file.exists():
        load_dotenv(env_file)
except ImportError:
    pass

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def main():
    """Execute full database setup."""
    logger.info("=" * 80)
    logger.info("DevANT Phase 2: Database Setup")
    logger.info("=" * 80)
    
    # Check environment
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("❌ DATABASE_URL not set in .env")
        sys.exit(1)
    
    logger.info(f"✓ DATABASE_URL configured: {db_url[:60]}...")
    
    # Import after env is checked
    try:
        from database.client import DatabaseClient, get_database_client
        from database.models import Base
        from sqlalchemy import text, event
    except ImportError as e:
        logger.error(f"❌ Import error: {e}")
        logger.info("   Install SQLAlchemy and psycopg2-binary:")
        logger.info("   pip install sqlalchemy psycopg2-binary")
        sys.exit(1)
    
    # 1. Test connection
    logger.info("\n[1/4] Testing database connection...")
    try:
        client = get_database_client()
        if client.health_check():
            logger.info("✓ Database connection successful")
        else:
            logger.error("❌ Health check failed")
            sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Connection failed: {e}")
        sys.exit(1)
    
    # 2. Enable pgvector
    logger.info("\n[2/4] Enabling pgvector extension...")
    try:
        with client.engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector;"))
            conn.commit()
        logger.info("✓ pgvector extension enabled")
    except Exception as e:
        logger.error(f"❌ pgvector setup failed: {e}")
        sys.exit(1)
    
    # 3. Create tables via SQLAlchemy
    logger.info("\n[3/4] Creating database tables...")
    try:
        Base.metadata.create_all(bind=client.engine)
        logger.info("✓ All tables created successfully")
    except Exception as e:
        logger.error(f"❌ Table creation failed: {e}")
        sys.exit(1)
    
    # 4. Run SQL migration file
    logger.info("\n[4/4] Running migration script...")
    migration_path = Path(__file__).parent / "database" / "migrations" / "001_initial_schema.sql"
    if not migration_path.exists():
        logger.warning(f"⚠ Migration file not found: {migration_path}")
    else:
        try:
            with open(migration_path, 'r') as f:
                sql = f.read()
            
            with client.engine.connect() as conn:
                # Split SQL into statements and execute
                for statement in sql.split(';'):
                    stmt = statement.strip()
                    if stmt and not stmt.startswith('--'):
                        try:
                            conn.execute(text(stmt))
                        except Exception as e:
                            # Some statements may fail if they already exist; that's ok
                            logger.debug(f"  Statement skipped: {stmt[:50]}... ({e})")
                conn.commit()
            logger.info("✓ Migration script executed")
        except Exception as e:
            logger.error(f"❌ Migration failed: {e}")
            sys.exit(1)
    
    # 5. Verify tables exist
    logger.info("\n[Verification] Checking tables...")
    try:
        from database.repositories.entities import (
            ProjectRepository, RawEventRepository, ErrorClusterRepository,
            ClusterEmbeddingRepository, IncidentRepository, AlertRepository,
            GitHubEventRepository, DeploymentRepository, TicketRepository,
            MuteRepository, SignatureStateRepository
        )
        
        session = client.get_session()
        
        # Try creating repositories (confirms tables exist)
        repos = [
            ("ProjectRepository", ProjectRepository),
            ("RawEventRepository", RawEventRepository),
            ("ErrorClusterRepository", ErrorClusterRepository),
            ("ClusterEmbeddingRepository", ClusterEmbeddingRepository),
            ("IncidentRepository", IncidentRepository),
            ("AlertRepository", AlertRepository),
            ("GitHubEventRepository", GitHubEventRepository),
            ("DeploymentRepository", DeploymentRepository),
            ("TicketRepository", TicketRepository),
            ("MuteRepository", MuteRepository),
            ("SignatureStateRepository", SignatureStateRepository),
        ]
        
        for name, repo_cls in repos:
            repo = repo_cls(session)
            count = repo.count()
            logger.info(f"  ✓ {name:40s} — {count} records")
        
        session.close()
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}")
        sys.exit(1)
    
    logger.info("\n" + "=" * 80)
    logger.info("✅ Database setup complete!")
    logger.info("=" * 80)
    logger.info("\nNext steps:")
    logger.info("1. Start the backend: cd backend && uvicorn main:app --reload --port 8000")
    logger.info("2. Start the frontend: cd frontend && npm run dev")
    logger.info("3. Open http://localhost:3000 in your browser")


if __name__ == "__main__":
    main()
