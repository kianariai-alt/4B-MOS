"""Offline Persian inference. Only provisioned local weights are accepted."""
from pathlib import Path
import hashlib
import importlib.util
from backend.app.core.config import settings

class SpeechModelUnavailable(Exception): pass


def speech_ready():
    root=Path(settings.SPEECH_MODEL_DIRECTORY)
    return bool(settings.SPEECH_MODEL_DIRECTORY and root.is_dir() and
                all((root/name).is_file() for name in ('model.bin','config.json','tokenizer.json')) and
                importlib.util.find_spec('faster_whisper') is not None)


def model_fingerprint(root):
    sha=hashlib.sha256()
    for name in ('config.json','model.bin','tokenizer.json'):
        sha.update(name.encode())
        with (root/name).open('rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):sha.update(block)
    return sha.hexdigest()


class PersianSpeechEngine:
    def __init__(self):
        if not speech_ready():raise SpeechModelUnavailable('Local speech weights unavailable.')
        from faster_whisper import WhisperModel
        root=Path(settings.SPEECH_MODEL_DIRECTORY).resolve()
        self.fingerprint=model_fingerprint(root)
        self.model_id=settings.SPEECH_MODEL_ID
        self.model=WhisperModel(str(root),device='cpu',compute_type='int8',local_files_only=True)

    def transcribe(self,pcm):
        import numpy as np
        audio=np.frombuffer(pcm,dtype='<i2').astype(np.float32)/32768.0
        try:
            segments,_=self.model.transcribe(audio,language='fa',vad_filter=True,condition_on_previous_text=False)
            rows=[dict(start=s.start,end=s.end,text=s.text.strip(),speaker='unknown') for s in segments if s.text.strip()]
            if not rows:raise ValueError('No speech recognized.')
            return dict(text='\n'.join(s['text'] for s in rows),language='fa',engine='faster-whisper',model_id=self.model_id,model_fingerprint=self.fingerprint,segments=rows,speaker_identification_verified=False)
        finally:audio.fill(0)
