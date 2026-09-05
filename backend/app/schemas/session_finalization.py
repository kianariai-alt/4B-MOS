from pydantic import BaseModel


class SessionFinalizationRead(BaseModel):
    session_id: str
    sha256: str
    payload: dict
