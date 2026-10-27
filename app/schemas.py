from datetime import datetime

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator


class OtpSendRequest(BaseModel):
    email: EmailStr


class OtpVerifyRequest(BaseModel):
    email: EmailStr
    code: str = Field(pattern=r"^\d{4}$")


class SignupRequest(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=40)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)

    @field_validator("name", "phone")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value

    @model_validator(mode="after")
    def passwords_match(self) -> "SignupRequest":
        if self.password != self.confirm_password:
            raise ValueError("Passwords do not match.")
        return self


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)


class EnquiryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    email: EmailStr
    phone: str = Field(min_length=1, max_length=40)
    enquiry: str = Field(min_length=1, max_length=5000)

    @field_validator("name", "phone", "enquiry")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("This field cannot be blank.")
        return value


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    phone: str
    created_at: datetime


class AuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class OtpSendResponse(BaseModel):
    message: str
    expires_in_seconds: int


class OtpVerifyResponse(BaseModel):
    verified: bool


class EnquiryResponse(BaseModel):
    id: int
    status: str
    created_at: datetime