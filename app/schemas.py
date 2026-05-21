"""Compatibility re-export for Pydantic schemas.

Schema definitions live in their owning modules. Prefer importing from
`app.modules.<domain>.schemas` in new code.
"""

from app.modules.admin.alias_overrides.schemas import *  # noqa: F401,F403
from app.modules.admin.foods.schemas import *  # noqa: F401,F403
from app.modules.admin.tags.schemas import *  # noqa: F401,F403
from app.modules.admin.users.schemas import *  # noqa: F401,F403
from app.modules.auth.schemas import *  # noqa: F401,F403
from app.modules.chat.schemas import *  # noqa: F401,F403
from app.modules.favorites.schemas import *  # noqa: F401,F403
from app.modules.foods.schemas import *  # noqa: F401,F403
from app.modules.query_logs.schemas import *  # noqa: F401,F403
from app.modules.search.schemas import *  # noqa: F401,F403
from app.modules.users.schemas import *  # noqa: F401,F403
