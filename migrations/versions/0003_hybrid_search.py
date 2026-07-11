"""Add indexed hybrid search fields.

Revision ID: 0003_hybrid_search
Revises: 0002_phase_5_full_text_indexing
Create Date: 2026-07-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_hybrid_search"
down_revision: str | Sequence[str] | None = "0002_phase_5_full_text_indexing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.add_column(
        "chunks",
        sa.Column("simple_search_vector", postgresql.TSVECTOR(), nullable=True),
    )
    op.add_column("chunks", sa.Column("identifier_text", sa.Text(), nullable=True))
    op.create_index(
        "ix_chunks_simple_search_vector",
        "chunks",
        ["simple_search_vector"],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_chunks_identifier_text_trgm",
        "chunks",
        ["identifier_text"],
        postgresql_using="gin",
        postgresql_ops={"identifier_text": "gin_trgm_ops"},
    )


def downgrade() -> None:
    op.drop_index("ix_chunks_identifier_text_trgm", table_name="chunks")
    op.drop_index("ix_chunks_simple_search_vector", table_name="chunks")
    op.drop_column("chunks", "identifier_text")
    op.drop_column("chunks", "simple_search_vector")
