from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TOTPVerifyRequest(BaseModel):
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    temp_token: str = Field(min_length=32, max_length=64)


class SetupRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-zA-Z0-9_-]+$")
    password: str = Field(min_length=12, max_length=128)
    totp_code: str = Field(min_length=6, max_length=6, pattern=r"^\d{6}$")
    totp_secret: str = Field(min_length=16, max_length=32)
