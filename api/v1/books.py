import logging
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db, session_log
from app import cache, crud
from app.schemas import (
    BookCreate,
    BookResponse,
    BookUpdate,
    BookWithAuthorCreate,
    Page,
    make_page,
)

logger = logging.getLogger("app.cache")

router = APIRouter(prefix="/books", tags=["books"])


@router.get("", response_model=Page[BookResponse])
def list_books(
    title: Optional[str] = Query(None, description="Busca parcial pelo título"),
    author: Optional[str] = Query(None, description="Busca parcial pelo nome do autor"),
    author_id: Optional[int] = Query(None, description="Id exato do autor"),
    available: Optional[bool] = Query(None, description="true = com cópia disponível; false = esgotado"),
    q: Optional[str] = Query(None, description="Busca parcial no título OU na sinopse"),
    sort: Literal["title", "-title", "created_at", "-created_at", "published_at", "-published_at"] = Query(
        "title", description="Prefixo '-' = ordem decrescente"
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
):
    # Cache-aside da listagem: a chave depende de TODOS os parâmetros da consulta
    key = cache.books_list_key({
        "title": title, "author": author, "author_id": author_id, "available": available,
        "q": q, "sort": sort, "page": page, "limit": limit,
    })
    cached = cache.get_json(key)
    if cached is not None:
        logger.info("CACHE HIT  %s", key)
        return cached
    logger.info("CACHE MISS %s", key)

    session_log("ENDPOINT /books: consultando o PostgreSQL")
    items, total = crud.list_books(
        db, title=title, author=author, author_id=author_id, available=available,
        q=q, sort=sort, page=page, limit=limit,
    )
    result = Page[BookResponse].model_validate(
        make_page(items, total, page, limit), from_attributes=True
    ).model_dump(mode="json")  # ORM -> dict JSON-friendly (datas viram texto)
    cache.set_json(key, result)
    return result


@router.get("/{book_id}", response_model=BookResponse)
def get_book(book_id: int, db: Session = Depends(get_db)):
    key = cache.book_key(book_id)

    cached = cache.get_json(key)
    if cached is not None:
        logger.info("CACHE HIT  %s", key)
        return cached
    logger.info("CACHE MISS %s", key)

    book = crud.get_book(db, book_id)
    if book is None:
        # 404 NÃO é cacheado: se o livro for criado em seguida, queremos achá-lo
        raise HTTPException(status_code=404, detail="Livro não encontrado.")

    data = BookResponse.model_validate(book).model_dump(mode="json")
    cache.set_json(key, data)
    return data


@router.post(
    "", response_model=BookResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
)
def create_book(data: BookCreate, db: Session = Depends(get_db)):
    return crud.create_book(db, data)


@router.post(
    "/with-author", response_model=BookResponse, status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(get_current_user)],
)
def create_book_with_author(data: BookWithAuthorCreate, db: Session = Depends(get_db)):
    """Cria autor + livro na MESMA transação: ou os dois entram, ou nenhum."""
    return crud.create_book_with_author(db, data)


@router.put("/{book_id}", response_model=BookResponse, dependencies=[Depends(get_current_user)])
def update_book(book_id: int, data: BookUpdate, db: Session = Depends(get_db)):
    book = crud.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Livro não encontrado.")
    return crud.update_book(db, book, data)


@router.delete(
    "/{book_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(get_current_user)]
)
def delete_book(book_id: int, db: Session = Depends(get_db)):
    book = crud.get_book(db, book_id)
    if book is None:
        raise HTTPException(status_code=404, detail="Livro não encontrado.")
    crud.delete_book(db, book)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
