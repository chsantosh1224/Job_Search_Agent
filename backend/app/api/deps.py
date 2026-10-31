from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.db import session_scope


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
