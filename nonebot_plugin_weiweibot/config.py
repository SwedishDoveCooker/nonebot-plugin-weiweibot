from datetime import timedelta
from pydantic import BaseModel, Field

class MyModel(BaseModel):
    SESSION_EXPIRE_TIMEOUT: timedelta = Field(default=timedelta(seconds=30))
