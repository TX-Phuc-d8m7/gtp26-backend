"""Security compatibility facade.

The auth implementation lives in `app.modules.auth.service`; this facade gives
new modules a stable core import path while the codebase is being migrated.
"""

from app.modules.auth.service import *  # noqa: F401,F403

