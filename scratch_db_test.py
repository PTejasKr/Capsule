from backend.config import settings
from backend.database import is_pg, DB_PATH

print("DATABASE_URL:", settings.DATABASE_URL)
print("is_pg:", is_pg())
print("DB_PATH:", DB_PATH)
