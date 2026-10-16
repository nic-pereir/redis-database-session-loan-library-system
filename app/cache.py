"""Cache com Redis (padrão cache-aside).

Regras deste módulo:
  * O cache é uma OTIMIZAÇÃO, nunca uma dependência: se o Redis cair, a API continua
    funcionando (só mais lenta, indo direto ao banco). Por isso todo acesso ao Redis
    está protegido por try/except RedisError.
  * Guardamos JSON (texto) no Redis. Ele não conhece objetos Python.
  * Toda chave nasce com TTL: mesmo que a gente esqueça de invalidar algo, o dado
    velho some sozinho em CACHE_TTL_SECONDS.
"""
import hashlib
import json
import logging
from typing import Any, Iterable, Optional

import redis

from app.config import settings

logger = logging.getLogger("app.cache")

# decode_responses=True: o Redis devolve str (e não bytes)
# timeouts curtos: se o Redis estiver fora do ar, não deixamos a requisição pendurada
redis_client = redis.Redis.from_url(
    settings.REDIS_URL,
    decode_responses=True,
    socket_connect_timeout=1,
    socket_timeout=1,
)


# ============================ CHAVES ============================
# Padrão "tipo:identificador". Os ":" não têm função técnica, só organizam
# (ferramentas como o RedisInsight agrupam por ":").
def book_key(book_id: int) -> str:
    return f"book:{book_id}"


BOOK_LIST_PREFIX = "books:list:"


def books_list_key(params: dict) -> str:
    # Cada combinação de filtros/ordenação/página é uma consulta diferente => chave diferente.
    # O hash só encurta a chave (não é segurança).
    digest = hashlib.md5(json.dumps(params, sort_keys=True).encode()).hexdigest()
    return f"{BOOK_LIST_PREFIX}{digest}"


def author_books_prefix(author_id: int) -> str:
    return f"authors:{author_id}:books:"


def author_books_key(author_id: int, page: int, limit: int, sort: str) -> str:
    return f"{author_books_prefix(author_id)}{page}:{limit}:{sort}"


# ============================ OPERAÇÕES ============================
def get_json(key: str) -> Optional[Any]:
    """Devolve o valor guardado, ou None se não existe (CACHE MISS) ou se o Redis falhou."""
    if not settings.CACHE_ENABLED:
        return None
    try:
        raw = redis_client.get(key)
    except redis.RedisError as exc:
        logger.warning("Redis indisponível no GET (%s): seguindo sem cache", exc)
        return None
    return json.loads(raw) if raw is not None else None


def set_json(key: str, value: Any, ttl: Optional[int] = None) -> None:
    if not settings.CACHE_ENABLED:
        return
    try:
        redis_client.set(key, json.dumps(value), ex=ttl or settings.CACHE_TTL_SECONDS)
    except redis.RedisError as exc:
        logger.warning("Redis indisponível no SET (%s): seguindo sem cache", exc)


def delete(*keys: str) -> None:
    if not settings.CACHE_ENABLED or not keys:
        return
    try:
        redis_client.delete(*keys)
    except redis.RedisError as exc:
        logger.warning("Redis indisponível no DELETE (%s)", exc)


def delete_prefix(prefix: str) -> None:
    """Apaga todas as chaves que começam com `prefix`.

    Usa SCAN (percorre aos poucos) e não KEYS (trava o Redis inteiro enquanto varre).
    """
    if not settings.CACHE_ENABLED:
        return
    try:
        keys = list(redis_client.scan_iter(match=f"{prefix}*", count=100))
        if keys:
            redis_client.delete(*keys)
    except redis.RedisError as exc:
        logger.warning("Redis indisponível no delete_prefix (%s)", exc)


def invalidate_book(book_id: int, author_ids: Iterable[int] = ()) -> None:
    """Chame DEPOIS do commit sempre que um livro (ou seu estoque) mudar.

    Apaga: o livro, todas as listagens /books (qualquer filtro) e as listas
    de livros dos autores envolvidos.
    """
    delete(book_key(book_id))
    delete_prefix(BOOK_LIST_PREFIX)
    for author_id in set(author_ids):
        delete_prefix(author_books_prefix(author_id))
    logger.info("CACHE INVALIDATED book=%s authors=%s", book_id, sorted(set(author_ids)))


def ping() -> bool:
    try:
        return bool(redis_client.ping())
    except redis.RedisError:
        return False
