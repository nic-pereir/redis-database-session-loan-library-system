"""Initial Redis commands and TTL.

You need a Redis instance running at localhost:6379.
Run the following from the project root: `python scripts/redis_playground.py`

Tip: Open another terminal and run `redis-cli monitor` to see each command as it reaches Redis.
"""
import time

import redis

client = redis.Redis(host="localhost", port=6379, decode_responses=True)
# decode_responses=True => returns a str

print("PING ->", client.ping())

print("\n=== SET / GET / EXISTS / DELETE ===")
client.set("nome", "Nicolly")
print("GET nome      ->", client.get("nome"))
print("EXISTS nome   ->", client.exists("nome"), "(1 = existe)")
client.delete("nome")
print("EXISTS nome   ->", client.exists("nome"), "(0 = não existe mais)")
print("GET nome      ->", client.get("nome"), "(None = chave inexistente)")

print("\n=== TTL ===")
client.set("codigo_verificacao", "123456", ex=60)
print("TTL codigo_verificacao ->", client.ttl("codigo_verificacao"), "segundos")

client.set("expira_10s", "x", ex=10)
client.set("expira_1min", "x", ex=60)
client.set("expira_5min", "x", ex=5 * 60)
for k in ("expira_10s", "expira_1min", "expira_5min"):
    print(f"TTL {k:<12} ->", client.ttl(k))

client.set("sem_ttl", "x")
print("TTL sem_ttl      ->", client.ttl("sem_ttl"), "(-1 = existe e nunca expira)")
print("TTL nao_existe   ->", client.ttl("nao_existe"), "(-2 = a chave não existe)")

print("\nVendo a expiração acontecer (espera 3 s)...")
client.set("rapida", "oi", ex=2)
print("agora :", client.get("rapida"))
time.sleep(3)
print("depois:", client.get("rapida"), "(sumiu sozinha)")

# cleaning
client.delete("codigo_verificacao", "expira_10s", "expira_1min", "expira_5min", "sem_ttl")
