"""Encrypted audio and append-only transcription/review evidence."""
from alembic import op
import sqlalchemy as sa
revision='f0c3d6b1a275'
down_revision='e9b2c5a0f164'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('recording_audio_transfers',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('visit_id',sa.String(36),sa.ForeignKey('visits.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('recording_id',sa.String(36),nullable=False),
        sa.Column('start_event_id',sa.String(36),sa.ForeignKey('visit_recording_events.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('recorded_by',sa.String(36),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('pcm_bytes',sa.Integer(),nullable=False),sa.Column('key_id',sa.String(80),nullable=False),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('recording_id',name='uq_audio_recording'),sa.CheckConstraint('pcm_bytes > 0 AND pcm_bytes <= 57600000',name='ck_audio_size'),sa.CheckConstraint('length(sha256) = 64',name='ck_audio_sha'))
    op.create_index('ix_recording_audio_transfers_visit_id','recording_audio_transfers',['visit_id'])
    op.create_table('recording_audio_chunks',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('transfer_id',sa.String(36),sa.ForeignKey('recording_audio_transfers.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('chunk_index',sa.Integer(),nullable=False),sa.Column('pcm_bytes',sa.Integer(),nullable=False),sa.Column('pcm_sha256',sa.String(64),nullable=False),
        sa.Column('encrypted_data',sa.LargeBinary(),nullable=False),sa.Column('payload',sa.JSON(),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),
        sa.UniqueConstraint('transfer_id','chunk_index',name='uq_audio_chunk_index'),sa.CheckConstraint('chunk_index >= 0',name='ck_audio_chunk_index'),sa.CheckConstraint('pcm_bytes > 0 AND pcm_bytes <= 262144',name='ck_audio_chunk_size'),sa.CheckConstraint('length(sha256) = 64',name='ck_audio_chunk_sha'))
    op.create_index('ix_recording_audio_chunks_transfer_id','recording_audio_chunks',['transfer_id'])
    op.create_table('recording_text_events',
        sa.Column('id',sa.String(36),primary_key=True),sa.Column('transfer_id',sa.String(36),sa.ForeignKey('recording_audio_transfers.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False),sa.Column('action',sa.String(30),nullable=False),sa.Column('request_key',sa.String(100),nullable=False),
        sa.Column('recorded_by',sa.String(36),sa.ForeignKey('users.id',ondelete='RESTRICT'),nullable=False),sa.Column('encrypted_data',sa.LargeBinary(),nullable=True),
        sa.Column('payload',sa.JSON(),nullable=False),sa.Column('sha256',sa.String(64),nullable=False),sa.Column('created_at',sa.DateTime(timezone=True),nullable=False),
        sa.UniqueConstraint('transfer_id','version',name='uq_text_transfer_version'),sa.UniqueConstraint('transfer_id','request_key',name='uq_text_transfer_request'),
        sa.CheckConstraint('version > 0',name='ck_text_version'),sa.CheckConstraint('length(sha256) = 64',name='ck_text_sha'),sa.CheckConstraint("action IN ('audio_received','queued','started','failed','draft','review')",name='ck_text_action'))
    op.create_index('ix_recording_text_events_transfer_id','recording_text_events',['transfer_id'])

def downgrade():
    tables=('recording_text_events','recording_audio_chunks','recording_audio_transfers')
    if any(op.get_bind().scalar(sa.text('SELECT COUNT(*) FROM '+table)) for table in tables):
        raise RuntimeError('Downgrade refused: encrypted recording evidence would be lost.')
    for table in tables:op.drop_table(table)
