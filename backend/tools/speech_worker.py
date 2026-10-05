"""Run: python -m backend.tools.speech_worker [--once]. No audio/text logs."""
import argparse, logging, time
from sqlalchemy import select
from backend.app.db.session import SessionLocal
from backend.app.models.recording_media import RecordingAudioTransfer
from backend.app.services.recording_media import RecordingMediaService as Service, MediaConflictError, MediaAuthorizationError
from backend.app.services.recording import RecordingAuthorizationError
from backend.app.services.audio_crypto import AudioIntegrityError, AudioConfigurationError
from backend.app.services.speech_engine import PersianSpeechEngine, SpeechModelUnavailable
logger=logging.getLogger(__name__)

def run_once(engine=None):
    with SessionLocal() as db:
        candidates=list(db.execute(select(RecordingAudioTransfer.visit_id,RecordingAudioTransfer.recording_id)))
    processed=0
    for visit_id,recording_id in candidates:
        with SessionLocal() as db:
            try:claim=Service.claim(db,visit_id,recording_id)
            except (MediaConflictError,AudioConfigurationError):
                logger.warning('Speech job claim unavailable.');continue
        if claim is None:continue
        pcm=None;content=None;error=None
        try:
            with SessionLocal() as db:pcm=Service.read_pcm(db,claim)
            if engine is None:engine=PersianSpeechEngine()
            content=engine.transcribe(pcm)
        except (MediaAuthorizationError,RecordingAuthorizationError):error='authorization_changed'
        except AudioIntegrityError:error='audio_integrity'
        except (SpeechModelUnavailable,AudioConfigurationError):error='model_unavailable'
        except Exception:error='engine_failed'
        finally:
            if pcm is not None:pcm[:]=b'\0'*len(pcm)
        with SessionLocal() as db:
            try:Service.finish_job(db,visit_id,recording_id,claim,content,error)
            except MediaConflictError:logger.warning('Stale speech result discarded.')
        processed+=1
    return processed

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--once',action='store_true');args=parser.parse_args()
    while True:
        run_once()
        if args.once:return
        time.sleep(5)

if __name__=='__main__':main()
