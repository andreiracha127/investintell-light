"""
SQLAlchemy declarative base with a naming convention for constraints/indexes.

The naming convention ensures Alembic autogenerate produces stable, deterministic
migration names rather than DB-engine-generated ones (e.g. unnamed check constraints).
"""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Standard naming convention for all constraints and indexes.
# Keys: ix=index, uq=unique, ck=check, fk=foreign key, pk=primary key.
_NAMING_CONVENTION: dict[str, str] = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=_NAMING_CONVENTION)
