from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db

get_config_dep = Depends(get_settings)
get_db_dep = Depends(get_db)

ConfigDependency = Annotated[Settings, get_config_dep]
DatabaseDependency = Annotated[AsyncSession, get_db_dep]


async def get_current_user_dep() -> None:
    """Reserved dependency for the later authentication stage."""
    return None
