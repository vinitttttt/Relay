"""Store canonical participant IDs and prevent duplicate direct pairs."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "7695be33c198"
down_revision: Union[str, Sequence[str], None] = "fdbe86193732"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    direct_ids = bind.execute(
        sa.text("SELECT id FROM conversations WHERE conversation_type = 'direct'")
    ).scalars().all()

    participant_pairs: dict[int, tuple[int, int]] = {}
    seen_pairs: set[tuple[int, int]] = set()
    for conversation_id in direct_ids:
        user_ids = bind.execute(
            sa.text(
                "SELECT user_id FROM conversation_members "
                "WHERE conversation_id = :conversation_id ORDER BY user_id"
            ),
            {"conversation_id": conversation_id},
        ).scalars().all()
        if len(user_ids) != 2:
            raise RuntimeError(
                "Cannot add direct-pair uniqueness: an existing direct conversation "
                "does not have exactly two members."
            )

        pair = (int(user_ids[0]), int(user_ids[1]))
        if pair in seen_pairs:
            raise RuntimeError(
                "Cannot add direct-pair uniqueness: duplicate direct conversations "
                "already exist for a user pair."
            )
        participant_pairs[int(conversation_id)] = pair
        seen_pairs.add(pair)

    existing_columns = {
        column["name"] for column in sa.inspect(bind).get_columns("conversations")
    }
    if "direct_user_low_id" not in existing_columns:
        op.add_column(
            "conversations",
            sa.Column("direct_user_low_id", sa.Integer(), nullable=True),
        )
    if "direct_user_high_id" not in existing_columns:
        op.add_column(
            "conversations",
            sa.Column("direct_user_high_id", sa.Integer(), nullable=True),
        )

    for conversation_id, (low_user_id, high_user_id) in participant_pairs.items():
        bind.execute(
            sa.text(
                "UPDATE conversations SET direct_user_low_id = :low_user_id, "
                "direct_user_high_id = :high_user_id WHERE id = :conversation_id"
            ),
            {
                "low_user_id": low_user_id,
                "high_user_id": high_user_id,
                "conversation_id": conversation_id,
            },
        )

    op.create_index(
        "uq_conversations_direct_user_pair",
        "conversations",
        ["direct_user_low_id", "direct_user_high_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "uq_conversations_direct_user_pair", table_name="conversations"
    )
    op.drop_column("conversations", "direct_user_high_id")
    op.drop_column("conversations", "direct_user_low_id")
