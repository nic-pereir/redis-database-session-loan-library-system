from fastapi import APIRouter

from api.v1 import auth, authors, books, loans

api_router = APIRouter()
api_router.include_router(auth.router)
api_router.include_router(authors.router)
api_router.include_router(books.router)
api_router.include_router(loans.router)
