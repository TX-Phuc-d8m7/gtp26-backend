"""SQLAlchemy metadata import hub."""

from app.db.session import Base
from app.modules.admin.alias_overrides import models as _alias_override_models  # noqa: F401
from app.modules.chat import models as _chat_models  # noqa: F401
from app.modules.favorites import models as _favorite_models  # noqa: F401
from app.modules.foods import models as _food_models  # noqa: F401
from app.modules.places import models as _place_models  # noqa: F401
from app.modules.query_logs import models as _query_log_models  # noqa: F401
from app.modules.users import models as _user_models  # noqa: F401

__all__ = ["Base"]
