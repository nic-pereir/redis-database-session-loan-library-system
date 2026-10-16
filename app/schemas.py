import math
from datetime import date, datetime
from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models import LoanStatus

T = TypeVar("T")


# ----- PAGINATION -----
class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    limit: int
    pages: int


def make_page(items: list, total: int, page: int, limit: int) -> dict:
    return {
        "items": items,
        "total": total,
        "page": page,
        "limit": limit,
        "pages": math.ceil(total / limit) if total else 0,
    }


# ----- USER / AUTH -----
class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    email: EmailStr
    # bcrypt só aceita até 72 bytes
    password: str = Field(min_length=8, max_length=72)


class UserResponse(BaseModel):
    id: int
    name: str
    email: EmailStr
    created_at: datetime
    model_config = ConfigDict(from_attributes=True)


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


# ----- AUTHOR -----
class AuthorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    birth_date: date
    biography: Optional[str] = None


class AuthorCreate(AuthorBase):
    pass


class AuthorSummary(BaseModel):
    id: int
    name: str
    model_config = ConfigDict(from_attributes=True)


# ----- BOOK -----
class BookCore(BaseModel):
    """Campos do livro, sem dizer quem é o autor."""
    title: str = Field(min_length=1, max_length=255)
    synopsis: Optional[str] = None
    published_at: date
    total_copies: int = Field(ge=1)


class BookBase(BookCore):
    author_id: int


class BookCreate(BookBase):
    """available_copies começa igual a total_copies (calculado no servidor)."""


class BookWithAuthorCreate(BaseModel):
    author: AuthorCreate
    book: BookCore


class BookUpdate(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)
    synopsis: Optional[str] = None
    published_at: Optional[date] = None
    total_copies: Optional[int] = Field(default=None, ge=1)
    author_id: Optional[int] = None


class BookResponse(BookBase):
    id: int
    available_copies: int
    created_at: datetime
    author: str  # author's name
    model_config = ConfigDict(from_attributes=True)

    @field_validator("author", mode="before")
    @classmethod
    def author_name(cls, v):
        # o model traz o objeto Author; a resposta expõe só o nome
        return getattr(v, "name", v)


class AuthorResponse(AuthorBase):
    id: int
    books: list[BookResponse] = []
    model_config = ConfigDict(from_attributes=True)


class AuthorStats(BaseModel):
    id: int
    name: str
    books_count: int


# ----- LOANS -----
class LoanCreate(BaseModel):
    book_id: int


class LoanResponse(BaseModel):
    id: int
    user_id: int
    book_id: int
    borrowed_at: date
    due_date: date
    returned_at: Optional[date] = None
    renews_count: int
    status: LoanStatus
    model_config = ConfigDict(from_attributes=True)
