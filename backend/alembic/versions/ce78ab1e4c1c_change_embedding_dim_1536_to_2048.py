"""change_embedding_dim_1536_to_2048

Revision ID: ce78ab1e4c1c
Revises: 051b2df8478e
Create Date: 2026-08-10 19:49:51.649233

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'ce78ab1e4c1c'
down_revision: Union[str, Sequence[str], None] = '051b2df8478e'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Change embedding column from vector(1536) to vector(2048).

    Drops the ivfflat index (pgvector caps ivfflat/hnsw at 2000 dims).
    For codebases with typical symbol counts (<100k), exact cosine
    search on vector(2048) is fast enough without an ANN index.
    """
    op.drop_index("ix_code_embeddings_embedding", table_name="code_embeddings")
    op.execute("DELETE FROM code_embeddings")
    op.execute("ALTER TABLE code_embeddings ALTER COLUMN embedding TYPE vector(2048)")


def downgrade() -> None:
    """Revert to vector(1536) with ivfflat index."""
    op.execute("DELETE FROM code_embeddings")
    op.execute("ALTER TABLE code_embeddings ALTER COLUMN embedding TYPE vector(1536)")
    op.create_index(
        "ix_code_embeddings_embedding",
        "code_embeddings",
        ["embedding"],
        postgresql_using="ivfflat",
        postgresql_with={"lists": 100},
        postgresql_ops={"embedding": "vector_cosine_ops"},
    )
