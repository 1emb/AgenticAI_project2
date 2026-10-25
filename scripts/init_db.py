"""Create (or recreate with --drop) all tables from the SQLAlchemy models."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from registrar.db import engine  # noqa: E402
from registrar.models import Base  # noqa: E402

if __name__ == "__main__":
    if "--drop" in sys.argv:
        Base.metadata.drop_all(engine)
        print("dropped all tables")
    Base.metadata.create_all(engine)
    print(f"created {len(Base.metadata.tables)} tables")
