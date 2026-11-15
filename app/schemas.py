from datetime import datetime
from typing import List

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator


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


class AdminLoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class AdminAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str = "admin"
    username: str


class EnquiryReportItem(BaseModel):
    id: int
    name: str
    email: str
    phone: str
    enquiry: str
    status: str
    created_at: datetime
    updated_at: datetime | None = None


class EnquiryStatusUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=50)


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductCreate(BaseModel):
    product_name: str = Field(min_length=1, max_length=255)
    price: float = Field(ge=0)
    image: str | None = Field(default=None, max_length=500)
    description: str | None = None
    status: str = Field(default="active")  # 'active' | 'inactive'


class ProductResponse(BaseModel):
    id: int
    product_name: str
    price: float
    image: str | None = None
    description: str | None = None
    status: str
    add_time: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Orders
# ---------------------------------------------------------------------------

class OrderDetailCreate(BaseModel):
    product_id: int | None = None
    product_name: str = Field(min_length=1, max_length=255)
    quantity: int = Field(ge=1)
    unit_price: float = Field(ge=0)
    total_price: float = Field(ge=0)


class OrderDetailResponse(BaseModel):
    id: int
    order_id: int
    product_id: int | None = None
    product_name: str
    quantity: int
    unit_price: float
    total_price: float

    model_config = ConfigDict(from_attributes=True)


class OrderHeadCreate(BaseModel):
    user_id: int | None = None
    customer_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=1, max_length=40)
    email: str = Field(default="")
    address: str = Field(min_length=1)
    order_type: str = Field(default="online")          # 'online' | 'offline'
    total_price: float = Field(ge=0)
    payment_mode: str = Field(min_length=1, max_length=50)
    payment_status: str = Field(default="pending")     # 'success' | 'cancel' | 'failed'
    paid_status: int = Field(default=0)                # 0 or 1
    send_email: bool = Field(default=True)
    send_whatsapp: bool = Field(default=True)
    items: List[OrderDetailCreate]


class OrderHeadResponse(BaseModel):
    id: int
    user_id: int | None = None
    customer_name: str
    phone: str
    email: str
    address: str
    order_type: str
    total_price: float
    payment_mode: str
    payment_status: str
    paid_status: int
    order_datetime: datetime
    items: List[OrderDetailResponse] = []
    email_sent: bool = False
    whatsapp_sent: bool = False
    whatsapp_url: str | None = None
    gst_number: str = "27AABCM1234F1Z1"

    model_config = ConfigDict(from_attributes=True)


class OrderStatusUpdateRequest(BaseModel):
    payment_status: str | None = None  # 'success' | 'pending' | 'failed' | 'cancelled'
    paid_status: int | None = None     # 0 or 1


# ---------------------------------------------------------------------------
# Cart
# ---------------------------------------------------------------------------

class CartItemAdd(BaseModel):
    product_id: int
    quantity: int = Field(default=1, ge=1)


class CartItemUpdate(BaseModel):
    quantity: int = Field(ge=0)


class CartItemResponse(BaseModel):
    id: int
    product_id: int
    product_name: str
    price: float
    image: str | None = None
    quantity: int
    subtotal: float

    model_config = ConfigDict(from_attributes=True)


class CartResponse(BaseModel):
    items: List[CartItemResponse] = []
    total: float = 0.0
    count: int = 0


# ---------------------------------------------------------------------------
# Addresses
# ---------------------------------------------------------------------------

class AddressCreate(BaseModel):
    label: str = Field(default="Home", max_length=50)
    full_name: str = Field(min_length=1, max_length=160)
    phone: str = Field(min_length=1, max_length=40)
    address_line1: str = Field(min_length=1, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str = Field(min_length=1, max_length=100)
    state: str = Field(min_length=1, max_length=100)
    pincode: str = Field(min_length=1, max_length=20)
    is_default: bool = False


class AddressUpdate(BaseModel):
    label: str | None = Field(default=None, max_length=50)
    full_name: str | None = Field(default=None, max_length=160)
    phone: str | None = Field(default=None, max_length=40)
    address_line1: str | None = Field(default=None, max_length=255)
    address_line2: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    state: str | None = Field(default=None, max_length=100)
    pincode: str | None = Field(default=None, max_length=20)
    is_default: bool | None = None


class AddressResponse(BaseModel):
    id: int
    user_id: int
    label: str
    full_name: str
    phone: str
    address_line1: str
    address_line2: str | None = None
    city: str
    state: str
    pincode: str
    is_default: bool
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Checkout
# ---------------------------------------------------------------------------

class CheckoutRequest(BaseModel):
    address_id: int | None = None
    address: AddressCreate | None = None
    payment_mode: str = Field(default="Cash on Delivery", max_length=50)



