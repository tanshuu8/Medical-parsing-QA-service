from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from app.core.config import settings

# Check if SQLite is used to add the check_same_thread argument
connect_args = {}
if settings.DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    settings.DATABASE_URL,
    connect_args=connect_args,
    echo=False
)


# Register SQLite event listener to ensure relational integrity
@event.listens_for(engine, "connect")
def set_sqlite_pragma(dbapi_connection, connection_record):
    """
    Enforces foreign key constraint checks on SQLite connections.
    SQLite disables foreign key triggers by default.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine
)


class Base(DeclarativeBase):
    """
    SQLAlchemy 2.0 Declarative Base class for ORM Models mapping schemas.
    """
    pass


def get_db():
    """
    Generator dependency yielding an isolated transactional SQLite session.
    Ensures proper cleanup and closure upon completion of request lifecycle.
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
