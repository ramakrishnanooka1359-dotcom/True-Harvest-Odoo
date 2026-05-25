import xmlrpc.client
import threading
from config import ODOO_URL, ODOO_DB, ODOO_USERNAME, ODOO_API_KEY

# Authenticate once at startup to get the uid
_common = xmlrpc.client.ServerProxy(f"{ODOO_URL}/xmlrpc/2/common", allow_none=True)
uid = _common.authenticate(ODOO_DB, ODOO_USERNAME, ODOO_API_KEY, {})

if not uid:
    raise Exception("Authentication Failed")

# Thread-local storage so each worker thread has its own ServerProxy.
# xmlrpc.client.ServerProxy is NOT thread-safe — sharing one instance across
# FastAPI's thread pool causes concurrent requests to corrupt each other,
# producing CORS errors and "Product not found" responses.
_local = threading.local()

class _ThreadSafeModels:
    """Wraps execute_kw so each thread gets its own private ServerProxy."""
    def execute_kw(self, *args, **kwargs):
        if not hasattr(_local, 'proxy'):
            _local.proxy = xmlrpc.client.ServerProxy(
                f"{ODOO_URL}/xmlrpc/2/object", allow_none=True
            )
        return _local.proxy.execute_kw(*args, **kwargs)

models = _ThreadSafeModels()
