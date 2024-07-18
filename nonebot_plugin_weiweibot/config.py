from pydantic import BaseModel

class Config(BaseModel):
    """Plugin Config Here"""
    SESSION_EXPIRE_TIMEOUT = "PT30S"
