import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from app import cache, crud
from app.schemas import AuthorCreate, AuthorResponse, AuthorStats, BookResponse, Page, make_page

logger = logging.getLogger("app.cache")

router = APIRouter(prefix="/authors", tags=["authors"])


@router.post(
    "", response_model=AuthorResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
)
def create_author(data: AuthorCreate, db: Session = Depends(get_db)):
    return crud.create_author(db, data)


@router.get("", response_model=Page[AuthorResponse])
def list_authors(
    name: Optional[str] = Query(None, description="Busca parcial pelo nome"),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    items, total = crud.list_authors(db, name, page, limit)
    return make_page(items, total, page, limit)


# Rotas fixas ANTES de "/{author_id}", senão "stats" seria lido como id e daria 422
@router.get("/stats", response_model=list[AuthorStats])
def authors_stats(db: Session = Depends(get_db)):
    """LEFT JOIN: todos os autores com a contagem de livros (inclui 0)."""
    return crud.authors_with_book_count(db)


@router.get("/without-books", response_model=list[AuthorResponse])
def authors_without_books(db: Session = Depends(get_db)):
    """Autores que ainda não têm nenhum livro cadastrado."""
    return crud.authors_without_books(db)


@router.get("/{author_id}", response_model=AuthorResponse)
def get_author(author_id: int, db: Session = Depends(get_db)):
    author = crud.get_author(db, author_id)
    if author is None:
        raise HTTPException(status_code=404, detail="Autor não encontrado.")
    return author


@router.get("/{author_id}/books", response_model=Page[BookResponse])
def list_author_books(
    author_id: int,
    sort: Literal["title", "-title", "created_at", "-created_at", "published_at", "-published_at"] = "title",
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    """Livros de um autor (com cache)."""
    key = cache.author_books_key(author_id, page, limit, sort)
    cached = cache.get_json(key)
    if cached is not None:
        logger.info("CACHE HIT  %s", key)
        return cached
    logger.info("CACHE MISS %s", key)

    if crud.get_author(db, author_id) is None:
        raise HTTPException(status_code=404, detail="Autor não encontrado.")
    items, total = crud.list_books(db, author_id=author_id, sort=sort, page=page, limit=limit)
    result = Page[BookResponse].model_validate(
        make_page(items, total, page, limit), from_attributes=True
    ).model_dump(mode="json")
    cache.set_json(key, result)
    return result
