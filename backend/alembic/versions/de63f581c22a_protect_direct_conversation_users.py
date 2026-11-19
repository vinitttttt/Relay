"""Protect canonical direct-conversation participants from deletion."""

from typing import Sequence, Union

from alembic import op

revision: str = "de63f581c22a"
down_revision: Union[str, Sequence[str], None] = "aa42f906e1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite requires a table rebuild to add foreign keys to existing columns.
    with op.batch_alter_table("conversations", recreate="auto") as batch_op:
        batch_op.create_foreign_key(
            "fk_conversations_direct_user_low_id_users",
            "users",
            ["direct_user_low_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_conversations_direct_user_high_id_users",
            "users",
            ["direct_user_high_id"],
            ["id"],
            ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("conversations", recreate="auto") as batch_op:
        batch_op.drop_constraint(
            "fk_conversations_direct_user_high_id_users", type_="foreignkey"
        )
        batch_op.drop_constraint(
            "fk_conversations_direct_user_low_id_users", type_="foreignkey"
        )
