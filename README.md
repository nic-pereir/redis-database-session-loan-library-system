# Library Loan System API

A RESTful backend API built with **FastAPI**, **PostgreSQL**, **SQLAlchemy 2.0**, **Alembic** and **Redis**. It manages a library catalog (authors and books) and the book loan workflow, with JWT authentication, business rules for loans, filtering, sorting, pagination, database migrations and a Redis cache (cache-aside).

---

## Tech Stack

* **Framework:** [FastAPI](https://fastapi.tiangolo.com/) (Python 3.10+)
* **Database:** [PostgreSQL](https://www.postgresql.org/) (the test suite runs on SQLite, no setup needed)
* **Cache:** [Redis](https://redis.io/) via [redis-py](https://redis-py.readthedocs.io/)
* **ORM:** [SQLAlchemy 2.0](https://www.sqlalchemy.org/) (synchronous, typed `Mapped[...]` models)
* **Migrations:** [Alembic](https://alembic.sqlalchemy.org/)
* **Authentication:** OAuth2 password flow with JSON Web Tokens ([PyJWT](https://pyjwt.readthedocs.io/)); passwords hashed with [bcrypt](https://pypi.org/project/bcrypt/)
* **Validation & settings:** [Pydantic v2](https://docs.pydantic.dev/) and `pydantic-settings`
* **Server:** [Uvicorn](https://www.uvicorn.org/)

---

## Features & Business Rules

### Authentication & Security
* User registration and login with bcrypt-hashed passwords (8 to 72 characters).
* Bearer token (JWT) authentication for protected routes.
* Users can only see and manage **their own loans**. Accessing someone else's loan returns `404`.
* There are no admin roles: any authenticated user can create authors and books.

### Catalog & Search
* **Authors:** create, list (with name search and pagination) and get by id, including their books.
* **Authors reports:** `GET /authors/stats` (books count per author, using a `LEFT JOIN`) and `GET /authors/without-books`.
* **Books:** create, read, update and delete (a book with loan history cannot be deleted).
* **Filters:** `title` and `author` (case-insensitive partial match), `author_id`, `available` (with/without copies in stock) and `q` (matches title **or** synopsis).
* **Sorting:** single `sort` parameter; a `-` prefix means descending (`title`, `-title`, `created_at`, `-created_at`, `published_at`, `-published_at`).
* **Pagination:** `page` (≥ 1) and `limit` (1 to 100, default 10). Every list returns metadata:

```json
{
  "items": [
    { "id": 1, "title": "Dom Casmurro", "author": "Machado de Assis", "...": "..." }
  ],
  "page": 1,
  "limit": 10,
  "total": 1,
  "pages": 1
}
```

### Loan Management
* **Simultaneous limit:** at most **2 open loans** per user (`PENDING`, `ACTIVE` and `OVERDUE` all count).
* **Loan duration:** **14 days**, counted from the pickup.
* **Status lifecycle:**
  * `PENDING`: requested, waiting for pickup (one copy is reserved);
  * `ACTIVE`: picked up, in progress;
  * `OVERDUE`: past the due date (computed automatically when loans are read or changed);
  * `RETURNED`: returned, copy back in stock.
* **Renewals:** up to **3 renewals** per loan, **+14 days** each, only for `ACTIVE` loans (an overdue loan cannot be renewed).
* **Overdue lock:** a user with an overdue loan cannot request new ones.
* **Cooldown for the same book:** after returning a book, the user must wait **14 days** before borrowing it again if either (a) the loan reached the renewal limit, or (b) the user's last 3 loans in a row were all for that same book.
* A user cannot hold two open loans of the same book, and a `PENDING` request can be cancelled (the copy returns to stock).

All these numbers are configurable in `app/config.py`.

##⚡ Caching (Redis, cache-aside)
* `GET /books`, `GET /books/{id}` and `GET /authors/{id}/books` are cached in Redis as JSON, each with a TTL (default 5 minutes).
* Flow: look in Redis → **CACHE HIT** returns it; **CACHE MISS** queries the database, stores the result in Redis and returns it. Both events are logged.
* **Invalidation:** creating, updating or deleting a book (and any loan operation that changes its stock) clears the affected keys *after* the database commit.
* **Resilient:** if Redis is down, the API keeps working straight from the database and logs a warning. `GET /health` reports the Redis status.
* Errors (404) are never cached.

### Sessions & Transactions
* One SQLAlchemy `Session` per request (`get_db` dependency), always closed at the end and rolled back on errors. Set `DEBUG_SESSION_LOG=true` to watch its lifecycle in the log.
* `POST /books/with-author` creates an author **and** a book in a single transaction: if anything fails, neither is saved.

---


## Project Structure

```text
library-loan-system/
│
├── app/
│   ├── __init__.py
│   ├── main.py            # FastAPI app, router inclusion, business error handler
│   ├── config.py          # Settings (env vars + business rule parameters)
│   ├── database.py        # Engine, session factory and declarative Base
│   ├── cache.py           # Redis client, cache keys, get/set/invalidate helpers
│   ├── models.py          # SQLAlchemy ORM models
│   ├── schemas.py         # Pydantic schemas (requests, responses, pagination)
│   └── crud.py            # Queries and business rules (data access layer)
│
├── api/
│   ├── deps.py            # get_db and get_current_user dependencies
│   └── v1/
│       ├── router.py      # Groups all v1 routers
│       ├── auth.py        # Register, login, current user
│       ├── authors.py     # Author endpoints and reports
│       ├── books.py       # Book search, filters, CRUD
│       └── loans.py       # Loan request, pickup, renew, return, cancel
│
├── core/
│   └── security.py        # Password hashing and JWT creation
down
│
├── scripts/
│   └── redis_playground.py  # Hands-on Redis commands and TTL
│
├── alembic/               # Migration environment and versions
├── alembic.ini
├── .env.example           # Template for environment variables
├── .gitignore
├── requirements.txt
└── README.md
```

---

## Database Overview

* **User**: `id`, `name`, `email` (unique), `hashed_pwd`, `created_at`
* **Author**: `id`, `name`, `birth_date`, `biography`
* **Book**: `id`, `title`, `synopsis`, `published_at`, `total_copies`, `available_copies`, `author_id` (FK), `created_at`
* **Loan**: `id`, `user_id` (FK), `book_id` (FK), `borrowed_at`, `due_date`, `returned_at`, `renews_count`, `status` (`PENDING`, `ACTIVE`, `OVERDUE`, `RETURNED`)

Relationships: an Author has many Books; a User has many Loans; a Book has many Loans. Foreign keys use `ON DELETE RESTRICT`.

---

## API Endpoints

All routes are prefixed with `/api/v1`.

### Authentication (`/auth`)
* `POST /auth/register` - Create a user account.
* `POST /auth/login` - Get a JWT (form fields `username` = e-mail and `password`).
* `GET /auth/me` - Current user data.

### Authors (`/authors`)
* `GET /authors` - List authors (`name`, `page`, `limit`).
* `GET /authors/stats` - Every author with their number of books (including 0).
* `GET /authors/without-books` - Authors that have no books yet.
* `GET /authors/{id}` - Author details with their books.
* `GET /authors/{id}/books` - Paginated, sortable and cached list of the author's books.
* `POST /authors` - Create an author *(auth required)*.

### Books (`/books`)
* `GET /books` - Search, filter, sort and paginate (`title`, `author`, `author_id`, `available`, `q`, `sort`, `page`, `limit`).
* `GET /books/{id}` - Book details.
* `POST /books` - Create a book *(auth required)*.
* `POST /books/with-author` - Create an author and a book in one transaction *(auth required)*.
* `PUT /books/{id}` - Update a book *(auth required)*.
* `DELETE /books/{id}` - Remove a book without loan history *(auth required)*.

Example: `GET /api/v1/books?title=dom&author=machado&page=1&limit=10&sort=title`

### Loans (`/loans`) *(auth required)*
* `POST /loans` - Request a loan (`PENDING`). Validates the 2-loan limit, overdue lock, cooldown and stock.
* `GET /loans` - Your loans (`status`, `page`, `limit`).
* `GET /loans/{id}` - One of your loans.
* `POST /loans/{id}/pickup` - Confirm pickup (`PENDING` → `ACTIVE`, starts the 14 days).
* `POST /loans/{id}/renew` - Renew an active loan (+14 days, max 3 times).
* `POST /loans/{id}/return` - Return the book (`ACTIVE`/`OVERDUE` → `RETURNED`).
* `DELETE /loans/{id}` - Cancel a `PENDING` request.

### Other
* `GET /health` - Health check with Redis status (outside the `/api/v1` prefix).

---

## Getting Started

### Prerequisites
* **Python 3.10+**
* **PostgreSQL** running locally or hosted
* **Redis** running locally or hosted (optional: without it the API still works, just without cache)

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/library-loan-system.git
cd library-loan-system
```

### 2. Set Up Virtual Environment
```bash
# On Linux/macOS
python3 -m venv venv
source venv/bin/activate

# On Windows
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
```
The database driver is not pinned; install the one for your database (for PostgreSQL: `pip install psycopg2-binary`).

### 4. Environment Variables
Create a `.env` file in the root directory based on `.env.example`:

```env
DATABASE_URL=postgresql+psycopg2://postgres:password@localhost:5432/library_db
SECRET_KEY=your_super_secret_jwt_key
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

REDIS_URL=redis://localhost:6379/0
CACHE_ENABLED=true
CACHE_TTL_SECONDS=300
DEBUG_SESSION_LOG=false
```

### 5. Database Migrations (Alembic)
Apply the migrations to create the tables:

```bash
alembic upgrade head
```

After changing a model, generate a new migration first:

```bash
alembic revision --autogenerate -m "describe the change"
alembic upgrade head
```

### 6. Run the Application
Run from the project root:

```bash
uvicorn app.main:app --reload
```

The server starts at `http://127.0.0.1:8000`.

* **Swagger UI:** [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
* **ReDoc:** [http://127.0.0.1:8000/redoc](http://127.0.0.1:8000/redoc)



