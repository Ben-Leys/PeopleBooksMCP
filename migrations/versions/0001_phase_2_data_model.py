"""Add Phase 2 PostgreSQL data model.

Revision ID: 0001_phase_2_data_model
Revises:
Create Date: 2026-07-07
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_phase_2_data_model"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "doc_versions",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("code", name="uq_doc_versions_code"),
    )

    op.create_table(
        "books",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "doc_version_id",
            sa.BigInteger(),
            sa.ForeignKey("doc_versions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("code", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("seed_url", sa.Text(), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("id", "doc_version_id", name="uq_books_id_doc_version"),
        sa.UniqueConstraint("doc_version_id", "code", name="uq_books_doc_version_code"),
    )

    op.create_table(
        "nav_nodes",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("doc_version_id", sa.BigInteger(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "parent_id",
            sa.BigInteger(),
            sa.ForeignKey("nav_nodes.id", ondelete="CASCADE"),
            nullable=True,
        ),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("node_type", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "discovered_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["book_id", "doc_version_id"],
            ["books.id", "books.doc_version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["parent_id", "book_id", "doc_version_id"],
            ["nav_nodes.id", "nav_nodes.book_id", "nav_nodes.doc_version_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "id",
            "book_id",
            "doc_version_id",
            name="uq_nav_nodes_id_book_doc_version",
        ),
        sa.UniqueConstraint("book_id", "stable_id", name="uq_nav_nodes_book_stable_id"),
    )
    op.create_index("ix_nav_nodes_parent_position", "nav_nodes", ["parent_id", "position"])

    op.create_table(
        "pages",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("doc_version_id", sa.BigInteger(), nullable=False),
        sa.Column("book_id", sa.BigInteger(), nullable=False),
        sa.Column("nav_node_id", sa.BigInteger(), nullable=True),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("normalized_path", sa.Text(), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("raw_html", sa.Text(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("fetch_status", sa.Text(), nullable=False, server_default="queued"),
        sa.Column(
            "queued_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")
        ),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("indexed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "fetch_status IN ('queued', 'fetching', 'fetched', 'failed', 'parsed', 'indexed')",
            name="ck_pages_fetch_status",
        ),
        sa.ForeignKeyConstraint(
            ["book_id", "doc_version_id"],
            ["books.id", "books.doc_version_id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nav_node_id", "book_id", "doc_version_id"],
            ["nav_nodes.id", "nav_nodes.book_id", "nav_nodes.doc_version_id"],
        ),
        sa.UniqueConstraint(
            "doc_version_id",
            "normalized_url",
            name="uq_pages_doc_version_normalized_url",
        ),
        sa.UniqueConstraint(
            "doc_version_id",
            "normalized_path",
            name="uq_pages_doc_version_normalized_path",
        ),
    )
    op.create_index(
        "ix_pages_fetch_queue", "pages", ["doc_version_id", "fetch_status", "queued_at"]
    )
    op.create_index("ix_pages_book_id", "pages", ["book_id"])

    op.create_table(
        "sections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "page_id",
            sa.BigInteger(),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("section_path", postgresql.ARRAY(sa.Text()), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("parser_version", sa.Text(), nullable=False),
        sa.Column(
            "source_metadata",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint("id", "page_id", name="uq_sections_id_page"),
        sa.UniqueConstraint("page_id", "stable_id", name="uq_sections_page_stable_id"),
    )
    op.create_index("ix_sections_page_ordinal", "sections", ["page_id", "ordinal"])

    op.create_table(
        "chunks",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "page_id",
            sa.BigInteger(),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "section_id",
            sa.BigInteger(),
            sa.ForeignKey("sections.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("stable_id", sa.Text(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["section_id", "page_id"],
            ["sections.id", "sections.page_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("section_id", "stable_id", name="uq_chunks_section_stable_id"),
    )
    op.create_index("ix_chunks_page_ordinal", "chunks", ["page_id", "ordinal"])

    op.create_table(
        "fetch_events",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column(
            "page_id",
            sa.BigInteger(),
            sa.ForeignKey("pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("fetch_status", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True),
        sa.Column("content_hash", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column(
            "metadata", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index("ix_fetch_events_page_created_at", "fetch_events", ["page_id", "created_at"])

    op.execute(
        """
        CREATE FUNCTION prevent_fetch_events_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'fetch_events rows are append-only';
        END;
        $$;
        """
    )
    op.execute(
        """
        CREATE TRIGGER fetch_events_no_update
        BEFORE UPDATE ON fetch_events
        FOR EACH ROW EXECUTE FUNCTION prevent_fetch_events_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER fetch_events_no_delete
        BEFORE DELETE ON fetch_events
        FOR EACH ROW EXECUTE FUNCTION prevent_fetch_events_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER fetch_events_no_truncate
        BEFORE TRUNCATE ON fetch_events
        FOR EACH STATEMENT EXECUTE FUNCTION prevent_fetch_events_mutation();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS fetch_events_no_truncate ON fetch_events")
    op.execute("DROP TRIGGER IF EXISTS fetch_events_no_delete ON fetch_events")
    op.execute("DROP TRIGGER IF EXISTS fetch_events_no_update ON fetch_events")
    op.execute("DROP FUNCTION IF EXISTS prevent_fetch_events_mutation")
    op.drop_table("fetch_events")
    op.drop_table("chunks")
    op.drop_table("sections")
    op.drop_table("pages")
    op.drop_table("nav_nodes")
    op.drop_table("books")
    op.drop_table("doc_versions")
