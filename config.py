import os
from dotenv import load_dotenv

dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(dotenv_path)

ODOO_URL = os.getenv("ODOO_URL")
ODOO_DB = os.getenv("ODOO_DB")
ODOO_USERNAME = os.getenv("ODOO_USERNAME")
ODOO_API_KEY = os.getenv("ODOO_API_KEY")

# JWT Configuration
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "default_secret_for_development_only")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# Database Configuration (Falls back to SQLite for local development)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./true_harvest.db")

TRUE_HARVEST_COMPANY_ID = 3

