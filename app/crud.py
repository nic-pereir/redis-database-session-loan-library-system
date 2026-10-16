from datetime import date, timedelta
from typing import Optional

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, contains_eager

from app import cache
from app.config import settings
from app.models import Author, Book, Loan, LoanStatus, User
from app.schemas import AuthorCreate, BookCreate, BookUpdate, BookWithAuthorCreate, UserCreate
from core.security import hash_password, verify_password

OPEN_STATUSES = (LoanStatus.PENDING.value, LoanStatus.ACTIVE.value, LoanStatus.OVERDUE.value)


class BusinessError(Exception):
    """Erro de regra de negócio; o main.py converte em resposta HTTP."""

    def __init__(self, detail: str, status_code: int = 409):
        self.detail = detail
        self.status_code = status_code


def today() -> date:
    return date.today()


# ============================ USERS ============================
def get_user(db: Session, user_id: int) -> Optional[User]:
    return db.get(User, user_id)


def get_user_by_email(db: Session, email: str) -> Optional[User]:
    return db.scalar(select(User).where(User.email == email.lower()))


def create_user(db: Session, data: UserCreate) -> User:
    if get_user_by_email(db, data.email):
        raise BusinessError("E-mail já cadastrado.", 409)
    user = User(name=data.name, email=data.email.lower(), hashed_pwd=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, email: str, password: str) -> Optional[User]:
    user = get_user_by_email(db, email)
    if user is None or not verify_password(password, user.hashed_pwd):
        return None
    return user


# ============================ AUTHORS ============================
def create_author(db: Session, data: AuthorCreate) -> Author:
    author = Author(**data.model_dump())
    db.add(author)
    db.commit()
    db.refresh(author)
    return author


def get_author(db: Session, author_id: int) -> Optional[Author]:
    return db.get(Author, author_id)


def list_authors(db: Session, name: Optional[str], page: int, limit: int) -> tuple[list[Author], int]:
    stmt = select(Author)
    if name:
        stmt = stmt.where(Author.name.icontains(name, autoescape=True))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Author.name, Author.id).offset((page - 1) * limit).limit(limit)
    ).all()
    return list(items), total


def authors_with_book_count(db: Session):
    """LEFT JOIN autores -> livros: autor sem livro continua na lista, com books_count = 0."""
    stmt = (
        select(Author.id, Author.name, func.count(Book.id).label("books_count"))
        .outerjoin(Author.books)
        .group_by(Author.id, Author.name)
        .order_by(Author.name, Author.id)
    )
    return db.execute(stmt).all()


def authors_without_books(db: Session) -> list[Author]:
    """LEFT JOIN + IS NULL: quem não achou par do lado dos livros."""
    stmt = select(Author).outerjoin(Author.books).where(Book.id.is_(None)).order_by(Author.name, Author.id)
    return list(db.scalars(stmt).all())


# ============================ BOOKS ============================
BOOK_SORT_COLUMNS = {
    "title": Book.title,
    "created_at": Book.created_at,
    "published_at": Book.published_at,
}


def list_books(
    db: Session,
    *,
    title: Optional[str] = None,
    author: Optional[str] = None,
    author_id: Optional[int] = None,
    available: Optional[bool] = None,
    q: Optional[str] = None,
    sort: str = "title",
    page: int = 1,
    limit: int = 10,
) -> tuple[list[Book], int]:
    # INNER JOIN: só livros que têm autor (todos têm, FK é NOT NULL)
    stmt = select(Book).join(Book.author)

    # cada .where() encadeado é um AND
    if title:
        stmt = stmt.where(Book.title.icontains(title, autoescape=True))
    if author:
        stmt = stmt.where(Author.name.icontains(author, autoescape=True))
    if author_id is not None:
        stmt = stmt.where(Book.author_id == author_id)
    if available is not None:
        stmt = stmt.where(Book.available_copies > 0 if available else Book.available_copies == 0)
    if q:  # OR: procura no título ou na sinopse
        stmt = stmt.where(
            or_(Book.title.icontains(q, autoescape=True), Book.synopsis.icontains(q, autoescape=True))
        )

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # sort: "title" = crescente, "-title" = decrescente
    descending = sort.startswith("-")
    column = BOOK_SORT_COLUMNS[sort.lstrip("-")]
    column, tiebreak = (column.desc(), Book.id.desc()) if descending else (column.asc(), Book.id.asc())
    items = db.scalars(
        stmt.options(contains_eager(Book.author))
        .order_by(column, tiebreak)  # id desempata (mesma direção), mantendo a paginação estável
        .offset((page - 1) * limit)
        .limit(limit)
    ).all()
    return list(items), total


def get_book(db: Session, book_id: int) -> Optional[Book]:
    return db.get(Book, book_id)


def create_book(db: Session, data: BookCreate) -> Book:
    if get_author(db, data.author_id) is None:
        raise BusinessError("Autor não encontrado.", 404)
    book = Book(**data.model_dump(), available_copies=data.total_copies)
    # Exercício 2: commit se der certo, rollback se der erro
    try:
        db.add(book)      # só registra na Session (ainda não foi pro banco)
        db.commit()       # envia o INSERT e confirma a transação
    except Exception:
        db.rollback()     # desfaz e deixa a Session utilizável de novo
        raise
    db.refresh(book)      # recarrega do banco (traz id, created_at, ...)
    cache.invalidate_book(book.id, [book.author_id])
    return book


def create_book_with_author(db: Session, data: BookWithAuthorCreate) -> Book:
    """Exercício 3: duas escritas, uma transação (atomicidade).

        BEGIN (implícito)  ->  INSERT author  ->  INSERT book  ->  COMMIT
                                      qualquer erro  ->  ROLLBACK (nenhum dos dois fica)
    """
    try:
        author = Author(**data.author.model_dump())
        db.add(author)
        db.flush()  # envia o INSERT do autor (gera author.id), mas NÃO confirma

        book = Book(
            **data.book.model_dump(),
            author_id=author.id,
            available_copies=data.book.total_copies,
        )
        db.add(book)
        db.commit()  # confirma os DOIS inserts de uma vez
    except Exception:
        db.rollback()  # desfaz os DOIS (inclusive o autor que já tinha sido "flushado")
        raise
    db.refresh(book)
    cache.invalidate_book(book.id, [book.author_id])
    return book


def update_book(db: Session, book: Book, data: BookUpdate) -> Book:
    changes = data.model_dump(exclude_unset=True)
    if "author_id" in changes and get_author(db, changes["author_id"]) is None:
        raise BusinessError("Autor não encontrado.", 404)
    if "total_copies" in changes:
        # mantém as cópias emprestadas: available = novo_total - emprestadas
        borrowed = book.total_copies - book.available_copies
        if changes["total_copies"] < borrowed:
            raise BusinessError(
                f"Existem {borrowed} cópias emprestadas; total_copies não pode ser menor que isso.", 409
            )
        book.available_copies = changes["total_copies"] - borrowed
    old_author_id = book.author_id
    for field, value in changes.items():
        setattr(book, field, value)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(book)
    # se trocou de autor, a lista dos DOIS autores muda
    cache.invalidate_book(book.id, [old_author_id, book.author_id])
    return book


def delete_book(db: Session, book: Book) -> None:
    has_loans = db.scalar(select(func.count()).select_from(Loan).where(Loan.book_id == book.id))
    if has_loans:
        raise BusinessError("Livro possui histórico de empréstimos e não pode ser removido.", 409)
    book_id, author_id = book.id, book.author_id
    try:
        db.delete(book)
        db.commit()
    except Exception:
        db.rollback()
        raise
    cache.invalidate_book(book_id, [author_id])


# ============================ LOANS ============================
def mark_overdue(db: Session, user_id: Optional[int] = None) -> None:
    """ACTIVE com prazo vencido vira OVERDUE (calculado sob demanda, sem job agendado)."""
    stmt = (
        update(Loan)
        .where(Loan.status == LoanStatus.ACTIVE.value, Loan.due_date < today())
        .values(status=LoanStatus.OVERDUE.value)
    )
    if user_id is not None:
        stmt = stmt.where(Loan.user_id == user_id)
    db.execute(stmt)
    db.commit()


def _get_own_loan(db: Session, user: User, loan_id: int) -> Loan:
    mark_overdue(db, user.id)
    loan = db.get(Loan, loan_id)
    # 404 (e não 403) para não revelar que o empréstimo existe
    if loan is None or loan.user_id != user.id:
        raise BusinessError("Empréstimo não encontrado.", 404)
    return loan


def get_loan(db: Session, user: User, loan_id: int) -> Loan:
    return _get_own_loan(db, user, loan_id)


def list_loans(
    db: Session, user: User, status: Optional[LoanStatus], page: int, limit: int
) -> tuple[list[Loan], int]:
    mark_overdue(db, user.id)
    stmt = select(Loan).where(Loan.user_id == user.id)
    if status:
        stmt = stmt.where(Loan.status == status.value)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    items = db.scalars(
        stmt.order_by(Loan.id.desc()).offset((page - 1) * limit).limit(limit)
    ).all()
    return list(items), total


def _cooldown_until(db: Session, user_id: int, book_id: int) -> Optional[date]:
    """Data até a qual o usuário está bloqueado de pegar este livro (ou None).

    Bloqueia por COOLDOWN_DAYS após a devolução quando, no último empréstimo desse livro:
      - o limite de renovações foi atingido, ou
      - os últimos MAX_CONSECUTIVE_LOANS empréstimos do usuário foram todos deste livro.
    """
    last_of_book = db.scalar(
        select(Loan)
        .where(Loan.user_id == user_id, Loan.book_id == book_id, Loan.status == LoanStatus.RETURNED.value)
        .order_by(Loan.returned_at.desc(), Loan.id.desc())
        .limit(1)
    )
    if last_of_book is None:
        return None

    hit_renewal_limit = last_of_book.renews_count >= settings.MAX_RENEWALS

    recent = db.scalars(
        select(Loan.book_id)
        .where(Loan.user_id == user_id)
        .order_by(Loan.id.desc())
        .limit(settings.MAX_CONSECUTIVE_LOANS)
    ).all()
    consecutive = len(recent) == settings.MAX_CONSECUTIVE_LOANS and all(b == book_id for b in recent)

    if hit_renewal_limit or consecutive:
        until = last_of_book.returned_at + timedelta(days=settings.COOLDOWN_DAYS)
        if today() < until:
            return until
    return None


def create_loan(db: Session, user: User, book_id: int) -> Loan:
    mark_overdue(db, user.id)

    # with_for_update trava a linha do livro (Postgres/MySQL) e evita duas pessoas pegando a última cópia
    book = db.get(Book, book_id, with_for_update=True)
    if book is None:
        raise BusinessError("Livro não encontrado.", 404)

    open_loans = db.scalars(
        select(Loan).where(Loan.user_id == user.id, Loan.status.in_(OPEN_STATUSES))
    ).all()

    if any(l.status == LoanStatus.OVERDUE.value for l in open_loans):
        raise BusinessError("Você possui empréstimo atrasado. Devolva antes de pegar novos livros.", 403)
    if len(open_loans) >= settings.MAX_ACTIVE_LOANS:
        raise BusinessError(f"Limite de {settings.MAX_ACTIVE_LOANS} empréstimos simultâneos atingido.", 409)
    if any(l.book_id == book_id for l in open_loans):
        raise BusinessError("Você já possui um empréstimo em aberto deste livro.", 409)

    until = _cooldown_until(db, user.id, book_id)
    if until:
        raise BusinessError(f"Período de carência para este livro até {until.isoformat()}.", 409)

    if book.available_copies < 1:
        raise BusinessError("Não há cópias disponíveis deste livro.", 409)

    start = today()
    loan = Loan(
        user_id=user.id,
        book_id=book_id,
        borrowed_at=start,
        due_date=start + timedelta(days=settings.LOAN_DAYS),
        renews_count=0,
        status=LoanStatus.PENDING.value,
    )
    book.available_copies -= 1  # a cópia fica reservada enquanto aguarda retirada
    db.add(loan)
    db.commit()
    db.refresh(loan)
    # o estoque mudou: o livro em cache está com available_copies velho
    cache.invalidate_book(book.id, [book.author_id])
    return loan


def pickup_loan(db: Session, user: User, loan_id: int) -> Loan:
    loan = _get_own_loan(db, user, loan_id)
    if loan.status != LoanStatus.PENDING.value:
        raise BusinessError("Apenas empréstimos PENDING podem ser retirados.", 409)
    start = today()
    loan.status = LoanStatus.ACTIVE.value
    loan.borrowed_at = start  # o prazo de 14 dias conta a partir da retirada
    loan.due_date = start + timedelta(days=settings.LOAN_DAYS)
    db.commit()
    db.refresh(loan)
    return loan


def cancel_loan(db: Session, user: User, loan_id: int) -> None:
    loan = _get_own_loan(db, user, loan_id)
    if loan.status != LoanStatus.PENDING.value:
        raise BusinessError("Apenas empréstimos PENDING podem ser cancelados.", 409)
    book = db.get(Book, loan.book_id, with_for_update=True)
    book.available_copies += 1
    book_id, author_id = book.id, book.author_id
    db.delete(loan)
    db.commit()
    cache.invalidate_book(book_id, [author_id])


def renew_loan(db: Session, user: User, loan_id: int) -> Loan:
    loan = _get_own_loan(db, user, loan_id)
    if loan.status == LoanStatus.OVERDUE.value:
        raise BusinessError("Empréstimo atrasado não pode ser renovado. Devolva o livro.", 409)
    if loan.status != LoanStatus.ACTIVE.value:
        raise BusinessError("Apenas empréstimos ACTIVE podem ser renovados.", 409)
    if loan.renews_count >= settings.MAX_RENEWALS:
        raise BusinessError(f"Limite de {settings.MAX_RENEWALS} renovações atingido.", 409)
    loan.due_date = loan.due_date + timedelta(days=settings.LOAN_DAYS)
    loan.renews_count += 1
    db.commit()
    db.refresh(loan)
    return loan


def return_loan(db: Session, user: User, loan_id: int) -> Loan:
    loan = _get_own_loan(db, user, loan_id)
    if loan.status not in (LoanStatus.ACTIVE.value, LoanStatus.OVERDUE.value):
        raise BusinessError("Apenas empréstimos ACTIVE ou OVERDUE podem ser devolvidos.", 409)
    book = db.get(Book, loan.book_id, with_for_update=True)
    book.available_copies += 1
    loan.status = LoanStatus.RETURNED.value
    loan.returned_at = today()
    db.commit()
    db.refresh(loan)
    cache.invalidate_book(book.id, [book.author_id])
    return loan
