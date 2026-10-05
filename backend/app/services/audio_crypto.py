"""Independent AES-256-GCM key; ciphertext is bound to its record context."""
import base64,hashlib,json,os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.exceptions import InvalidTag
from backend.app.core.config import settings

class AudioConfigurationError(Exception):pass
class AudioIntegrityError(Exception):pass

def key():
    secret=settings.AUDIO_ENCRYPTION_KEY
    if not settings.AUDIO_PIPELINE_ENABLED or secret is None:raise AudioConfigurationError("Audio pipeline is not configured.")
    try:decoded=base64.b64decode(secret.get_secret_value(),validate=True)
    except (ValueError,TypeError):raise AudioConfigurationError("Audio key is invalid.") from None
    if len(decoded)!=32:raise AudioConfigurationError("Audio key must contain 32 bytes.")
    return decoded

def enabled():
    try:key();return True
    except AudioConfigurationError:return False

def digest(data):return hashlib.sha256(data).hexdigest()
def aad(context):return json.dumps(context,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
def encrypt(data,context,key_id):
    if key_id!=settings.AUDIO_KEY_ID:raise AudioConfigurationError("Audio key version unavailable.")
    nonce=os.urandom(12);return nonce+AESGCM(key()).encrypt(nonce,data,aad(context))
def decrypt(data,context,key_id):
    if key_id!=settings.AUDIO_KEY_ID:raise AudioConfigurationError("Audio key version unavailable.")
    try:return AESGCM(key()).decrypt(data[:12],data[12:],aad(context))
    except (InvalidTag,ValueError):raise AudioIntegrityError("Audio ciphertext integrity failed.") from None
