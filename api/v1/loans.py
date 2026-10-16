from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from api.deps import get_current_user, get_db
from app import crud
from app.models import LoanStatus, User
from app.schemas import LoanCreate, LoanResponse, Page, make_page

router = APIRouter(prefix="/loans", tags=["loans"])


@router.post("", response_model=LoanResponse, status_code=status.HTTP_201_CREATED)
def request_loan(
    data: LoanCreate, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    """Solicita um empréstimo (fica PENDING até a retirada)."""
    return crud.create_loan(db, user, data.book_id)


@router.get("", response_model=Page[LoanResponse])
def list_my_loans(
    status: Optional[LoanStatus] = None,
    page: int = Query(1, ge=1),
    limit: int = Query(10, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    items, total = crud.list_loans(db, user, status, page, limit)
    return make_page(items, total, page, limit)


@router.get("/{loan_id}", response_model=LoanResponse)
def get_loan(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return crud.get_loan(db, user, loan_id)


@router.post("/{loan_id}/pickup", response_model=LoanResponse)
def pickup(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Confirma a retirada: PENDING -> ACTIVE e começa a contar os 14 dias."""
    return crud.pickup_loan(db, user, loan_id)


@router.post("/{loan_id}/renew", response_model=LoanResponse)
def renew(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return crud.renew_loan(db, user, loan_id)


@router.post("/{loan_id}/return", response_model=LoanResponse)
def return_book(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    return crud.return_loan(db, user, loan_id)


@router.delete("/{loan_id}", status_code=status.HTTP_204_NO_CONTENT)
def cancel(loan_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """Cancela uma solicitação PENDING e devolve a cópia ao estoque."""
    crud.cancel_loan(db, user, loan_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
