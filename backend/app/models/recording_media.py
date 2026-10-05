"""Append-only metadata and encrypted blobs; no plaintext audio or transcript."""
import uuid
from datetime import datetime,timezone
from sqlalchemy import CheckConstraint,DateTime,ForeignKey,Integer,JSON,LargeBinary,String,UniqueConstraint,event
from sqlalchemy.orm import Mapped,mapped_column
from backend.app.db.base import Base

class RecordingAudioTransfer(Base):
    __tablename__="recording_audio_transfers"
    __table_args__=(UniqueConstraint("recording_id",name="uq_audio_recording"),CheckConstraint("pcm_bytes > 0 AND pcm_bytes <= 57600000",name="ck_audio_size"),CheckConstraint("length(sha256) = 64",name="ck_audio_sha"))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    visit_id: Mapped[str]=mapped_column(String(36),ForeignKey("visits.id",ondelete="RESTRICT"),index=True)
    recording_id: Mapped[str]=mapped_column(String(36))
    start_event_id: Mapped[str]=mapped_column(String(36),ForeignKey("visit_recording_events.id",ondelete="RESTRICT"))
    recorded_by: Mapped[str]=mapped_column(String(36),ForeignKey("users.id",ondelete="RESTRICT"))
    pcm_bytes: Mapped[int]=mapped_column(Integer)
    key_id: Mapped[str]=mapped_column(String(80))
    payload: Mapped[dict]=mapped_column(JSON)
    sha256: Mapped[str]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

class RecordingAudioChunk(Base):
    __tablename__="recording_audio_chunks"
    __table_args__=(UniqueConstraint("transfer_id","chunk_index",name="uq_audio_chunk_index"),CheckConstraint("chunk_index >= 0",name="ck_audio_chunk_index"),CheckConstraint("pcm_bytes > 0 AND pcm_bytes <= 262144",name="ck_audio_chunk_size"),CheckConstraint("length(sha256) = 64",name="ck_audio_chunk_sha"))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    transfer_id: Mapped[str]=mapped_column(String(36),ForeignKey("recording_audio_transfers.id",ondelete="RESTRICT"),index=True)
    chunk_index: Mapped[int]=mapped_column(Integer)
    pcm_bytes: Mapped[int]=mapped_column(Integer)
    pcm_sha256: Mapped[str]=mapped_column(String(64))
    encrypted_data: Mapped[bytes]=mapped_column(LargeBinary,deferred=True)
    payload: Mapped[dict]=mapped_column(JSON)
    sha256: Mapped[str]=mapped_column(String(64))

class RecordingTextEvent(Base):
    __tablename__="recording_text_events"
    __table_args__=(UniqueConstraint("transfer_id","version",name="uq_text_transfer_version"),UniqueConstraint("transfer_id","request_key",name="uq_text_transfer_request"),CheckConstraint("version > 0",name="ck_text_version"),CheckConstraint("length(sha256) = 64",name="ck_text_sha"),CheckConstraint("action IN ('audio_received','queued','started','failed','draft','review')",name="ck_text_action"))
    id: Mapped[str]=mapped_column(String(36),primary_key=True,default=lambda:str(uuid.uuid4()))
    transfer_id: Mapped[str]=mapped_column(String(36),ForeignKey("recording_audio_transfers.id",ondelete="RESTRICT"),index=True)
    version: Mapped[int]=mapped_column(Integer)
    action: Mapped[str]=mapped_column(String(30))
    request_key: Mapped[str]=mapped_column(String(100))
    recorded_by: Mapped[str]=mapped_column(String(36),ForeignKey("users.id",ondelete="RESTRICT"))
    encrypted_data: Mapped[bytes | None]=mapped_column(LargeBinary,nullable=True,deferred=True)
    payload: Mapped[dict]=mapped_column(JSON)
    sha256: Mapped[str]=mapped_column(String(64))
    created_at: Mapped[datetime]=mapped_column(DateTime(timezone=True),default=lambda:datetime.now(timezone.utc))

def _immutable(mapper,connection,target):
    raise ValueError("Audio and transcript evidence are append-only.")
for model in (RecordingAudioTransfer,RecordingAudioChunk,RecordingTextEvent):
    event.listen(model,"before_update",_immutable);event.listen(model,"before_delete",_immutable)
