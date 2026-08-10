"""add_users_and_repo_ownership

Revision ID: a3f9c1e5b7d2
Revises: ce78ab1e4c1c
Create Date: 2026-08-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import uuid


# revision identifiers, used by Alembic.
revision: str = 'a3f9c1e5b7d2'
down_revision: Union[str, Sequence[str], None] = 'ce78ab1e4c1c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

ADMIN_ID = str(uuid.UUID('7c1f2a3b-4c5d-4e6f-8a9b-0c1d2e3f4a5b'))
ADMIN_PASSWORD_HASH = '4a6f3e8c2d5b1f7a$74b293ae7326bb2226dfeca61edbc1806ad7db7259cad2487a5043e2fb4ba893'


def upgrade() -> None:
    """Upgrade schema."""
    # Create users table
    op.create_table(
        'users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('username', sa.String(length=100), nullable=False),
        sa.Column('password_hash', sa.String(length=200), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('username'),
        sa.UniqueConstraint('token'),
    )

    # Seed the default admin user (admin / admin)
    op.execute(
        sa.text(
            "INSERT INTO users (id, username, password_hash, token, created_at) "
            "VALUES (CAST(:id AS uuid), 'admin', :pwd, NULL, now())"
        ).bindparams(id=ADMIN_ID, pwd=ADMIN_PASSWORD_HASH)
    )

    # Clean slate: remove all existing repos (cascades to files/symbols/embeddings/chat/deps/docs)
    op.execute(sa.text("DELETE FROM repositories"))

    # Add per-user ownership
    op.add_column('repositories', sa.Column('user_id', sa.UUID(), nullable=False))
    op.create_foreign_key(
        'fk_repositories_user_id', 'repositories', 'users', ['user_id'], ['id'], ondelete='CASCADE'
    )

    # Replace global github_url unique with per-user unique
    op.drop_constraint('repositories_github_url_key', 'repositories', type_='unique')
    op.create_unique_constraint(
        'uq_repositories_user_github', 'repositories', ['user_id', 'github_url']
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('uq_repositories_user_github', 'repositories', type_='unique')
    op.create_unique_constraint('repositories_github_url_key', 'repositories', ['github_url'])
    op.drop_constraint('fk_repositories_user_id', 'repositories', type_='foreignkey')
    op.drop_column('repositories', 'user_id')
    op.drop_table('users')
