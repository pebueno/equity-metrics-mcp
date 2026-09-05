"""Declarative base shared by every ORM model."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class carrying the project's shared metadata."""
