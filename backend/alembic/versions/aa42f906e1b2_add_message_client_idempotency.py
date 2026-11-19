"""Add scoped client message IDs for idempotent creation."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "aa42f906e1b2"
down_revision: Union[str, Sequence[str], None] = "7695be33c198"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("client_message_id", sa.String(length=100), nullable=True))
    op.create_index(
        "uq_messages_sender_conversation_client_id",
        "messages",
        ["conversation_id", "sender_id", "client_message_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_messages_sender_conversation_client_id", table_name="messages")
    op.drop_column("messages", "client_message_id")
