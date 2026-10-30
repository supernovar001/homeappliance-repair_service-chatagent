"""초기 테이블과 기본 데이터(설명서 1건, 지원 모델 2종)

Revision ID: 0001
Revises: 
Create Date: 2026-10-30 09:08:31.605631
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = '0001'
down_revision = None
branch_labels = None
depends_on = None

# 상담에 쓰는 세탁기 페이지(app.py의 WASHER_PAGES와 같아야 합니다. tests/test_seed.py가 확인합니다).
WASHER_PAGES = list(range(3, 10)) + list(range(14, 28)) + list(range(39, 44)) + list(range(47, 60)) + [64]


def seed():
    manuals = sa.table("manuals", sa.column("id"), sa.column("title"), sa.column("revision"), sa.column("file_name"),
                       sa.column("allowed_pages", postgresql.JSONB()))
    models = sa.table("supported_models", sa.column("id"), sa.column("series"), sa.column("washer_model"),
                      sa.column("dryer_model"), sa.column("manual_id"), sa.column("position"))
    op.bulk_insert(manuals, [{"id": "MFL71831423", "title": "워시타워 사용설명서", "revision": "Rev.06",
                              "file_name": "wachingmachine_service_manual.pdf", "allowed_pages": WASHER_PAGES}])
    op.bulk_insert(models, [
        {"id": "w10n", "series": "W10**N", "washer_model": "F13*J(*)N", "dryer_model": "RH10*J(*)N", "manual_id": "MFL71831423", "position": 1},
        {"id": "w1310n", "series": "W1310**N", "washer_model": "F13*J(*)NR", "dryer_model": "RH10*J(*)NR", "manual_id": "MFL71831423", "position": 2},
    ])


def upgrade():
    op.create_table('manuals',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('revision', sa.String(length=20), nullable=False),
    sa.Column('file_name', sa.String(length=200), nullable=False),
    sa.Column('allowed_pages', postgresql.JSONB(), nullable=False),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('metric_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('type', sa.String(length=30), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('duration_ms', sa.Integer(), nullable=True),
    sa.Column('route', sa.String(length=30), nullable=True),
    sa.Column('error_type', sa.String(length=40), nullable=True),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_metric_events_created_at'), 'metric_events', ['created_at'], unique=False)
    op.create_index(op.f('ix_metric_events_type'), 'metric_events', ['type'], unique=False)
    op.create_table('users',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('google_sub', sa.String(length=255), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('picture', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('email'),
    sa.UniqueConstraint('google_sub')
    )
    op.create_table('admin_audit_logs',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('admin_user_id', sa.Uuid(), nullable=True),
    sa.Column('action', sa.String(length=40), nullable=False),
    sa.Column('target_id', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['admin_user_id'], ['users.id'], ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('sessions',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('csrf_token', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('token_hash')
    )
    op.create_index(op.f('ix_sessions_expires_at'), 'sessions', ['expires_at'], unique=False)
    op.create_index(op.f('ix_sessions_user_id'), 'sessions', ['user_id'], unique=False)
    op.create_table('supported_models',
    sa.Column('id', sa.String(length=40), nullable=False),
    sa.Column('series', sa.String(length=40), nullable=False),
    sa.Column('washer_model', sa.String(length=40), nullable=False),
    sa.Column('dryer_model', sa.String(length=40), nullable=False),
    sa.Column('manual_id', sa.String(length=40), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.ForeignKeyConstraint(['manual_id'], ['manuals.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_table('products',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('supported_model_id', sa.String(length=40), nullable=False),
    sa.Column('nickname', sa.String(length=40), nullable=False),
    sa.Column('model_code', sa.String(length=40), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['supported_model_id'], ['supported_models.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_products_user_id'), 'products', ['user_id'], unique=False)
    op.create_table('conversations',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('title', sa.String(length=100), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_conversations_product_id'), 'conversations', ['product_id'], unique=False)
    op.create_index(op.f('ix_conversations_user_id'), 'conversations', ['user_id'], unique=False)
    op.create_table('memories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('product_id', sa.Uuid(), nullable=False),
    sa.Column('source_conversation_id', sa.Uuid(), nullable=True),
    sa.Column('symptom', sa.String(length=200), nullable=False),
    sa.Column('action', sa.String(length=300), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['product_id'], ['products.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['source_conversation_id'], ['conversations.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_memories_product_id'), 'memories', ['product_id'], unique=False)
    op.create_index(op.f('ix_memories_source_conversation_id'), 'memories', ['source_conversation_id'], unique=False)
    op.create_index(op.f('ix_memories_user_id'), 'memories', ['user_id'], unique=False)
    op.create_table('messages',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('kind', sa.String(length=30), nullable=False),
    sa.Column('content', sa.Text(), nullable=False),
    sa.Column('result', postgresql.JSONB(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_messages_conversation_id'), 'messages', ['conversation_id'], unique=False)
    op.create_table('bookmarks',
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('user_id', 'message_id')
    )
    op.create_table('checklist_items',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=False),
    sa.Column('key', sa.String(length=40), nullable=False),
    sa.Column('title', sa.String(length=200), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('pages', postgresql.JSONB(), nullable=False),
    sa.Column('kind', sa.String(length=20), nullable=False),
    sa.Column('enabled', sa.Boolean(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('inherited_from_item_id', sa.Uuid(), nullable=True),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['inherited_from_item_id'], ['checklist_items.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checklist_items_conversation_id'), 'checklist_items', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_checklist_items_message_id'), 'checklist_items', ['message_id'], unique=False)
    op.create_table('consultation_requests',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('user_id', sa.Uuid(), nullable=False),
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('client_request_id', sa.String(length=64), nullable=False),
    sa.Column('user_message_id', sa.Uuid(), nullable=False),
    sa.Column('assistant_message_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('stage', sa.String(length=30), nullable=True),
    sa.Column('error_type', sa.String(length=40), nullable=True),
    sa.Column('attempt', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('finished_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['assistant_message_id'], ['messages.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['user_message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('user_id', 'client_request_id')
    )
    op.create_index(op.f('ix_consultation_requests_conversation_id'), 'consultation_requests', ['conversation_id'], unique=False)
    op.create_index(op.f('ix_consultation_requests_user_id'), 'consultation_requests', ['user_id'], unique=False)
    op.create_table('conversation_memories',
    sa.Column('conversation_id', sa.Uuid(), nullable=False),
    sa.Column('memory_id', sa.Uuid(), nullable=False),
    sa.ForeignKeyConstraint(['conversation_id'], ['conversations.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['memory_id'], ['memories.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('conversation_id', 'memory_id')
    )
    op.create_table('checklist_events',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('item_id', sa.Uuid(), nullable=False),
    sa.Column('message_id', sa.Uuid(), nullable=True),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('outcome', sa.String(length=20), nullable=False),
    sa.Column('source', sa.String(length=20), nullable=False),
    sa.Column('evidence', sa.Text(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['item_id'], ['checklist_items.id'], ondelete='CASCADE'),
    sa.ForeignKeyConstraint(['message_id'], ['messages.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_checklist_events_item_id'), 'checklist_events', ['item_id'], unique=False)
    op.create_table('request_events',
    sa.Column('id', sa.BigInteger(), autoincrement=True, nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('seq', sa.Integer(), nullable=False),
    sa.Column('type', sa.String(length=20), nullable=False),
    sa.Column('data', postgresql.JSONB(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
    sa.ForeignKeyConstraint(['request_id'], ['consultation_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('request_id', 'seq')
    )
    op.create_index(op.f('ix_request_events_request_id'), 'request_events', ['request_id'], unique=False)
    op.create_table('request_memories',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('request_id', sa.Uuid(), nullable=False),
    sa.Column('memory_id', sa.Uuid(), nullable=True),
    sa.Column('version', sa.Integer(), nullable=False),
    sa.Column('snapshot', postgresql.JSONB(), nullable=True),
    sa.Column('deleted', sa.Boolean(), nullable=False),
    sa.ForeignKeyConstraint(['memory_id'], ['memories.id'], ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['request_id'], ['consultation_requests.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_request_memories_memory_id'), 'request_memories', ['memory_id'], unique=False)
    op.create_index(op.f('ix_request_memories_request_id'), 'request_memories', ['request_id'], unique=False)
    seed()


def downgrade():
    op.drop_index(op.f('ix_request_memories_request_id'), table_name='request_memories')
    op.drop_index(op.f('ix_request_memories_memory_id'), table_name='request_memories')
    op.drop_table('request_memories')
    op.drop_index(op.f('ix_request_events_request_id'), table_name='request_events')
    op.drop_table('request_events')
    op.drop_index(op.f('ix_checklist_events_item_id'), table_name='checklist_events')
    op.drop_table('checklist_events')
    op.drop_table('conversation_memories')
    op.drop_index(op.f('ix_consultation_requests_user_id'), table_name='consultation_requests')
    op.drop_index(op.f('ix_consultation_requests_conversation_id'), table_name='consultation_requests')
    op.drop_table('consultation_requests')
    op.drop_index(op.f('ix_checklist_items_message_id'), table_name='checklist_items')
    op.drop_index(op.f('ix_checklist_items_conversation_id'), table_name='checklist_items')
    op.drop_table('checklist_items')
    op.drop_table('bookmarks')
    op.drop_index(op.f('ix_messages_conversation_id'), table_name='messages')
    op.drop_table('messages')
    op.drop_index(op.f('ix_memories_user_id'), table_name='memories')
    op.drop_index(op.f('ix_memories_source_conversation_id'), table_name='memories')
    op.drop_index(op.f('ix_memories_product_id'), table_name='memories')
    op.drop_table('memories')
    op.drop_index(op.f('ix_conversations_user_id'), table_name='conversations')
    op.drop_index(op.f('ix_conversations_product_id'), table_name='conversations')
    op.drop_table('conversations')
    op.drop_index(op.f('ix_products_user_id'), table_name='products')
    op.drop_table('products')
    op.drop_table('supported_models')
    op.drop_index(op.f('ix_sessions_user_id'), table_name='sessions')
    op.drop_index(op.f('ix_sessions_expires_at'), table_name='sessions')
    op.drop_table('sessions')
    op.drop_table('admin_audit_logs')
    op.drop_table('users')
    op.drop_index(op.f('ix_metric_events_type'), table_name='metric_events')
    op.drop_index(op.f('ix_metric_events_created_at'), table_name='metric_events')
    op.drop_table('metric_events')
    op.drop_table('manuals')
