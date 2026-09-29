#!/usr/bin/env python3
"""Diagnóstico READ-ONLY de suscripciones activas en producción."""
import os
from datetime import date
from pathlib import Path

import pymysql
from dotenv import load_dotenv

root = Path(__file__).parent.parent
load_dotenv(root / ".env.production")

cfg = {
    "host": os.getenv("DB_HOST"),
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME"),
    "port": int(os.getenv("DB_PORT", 3306)),
    "charset": "utf8mb4",
    "connect_timeout": 10,
}

conn = pymysql.connect(**cfg)
cur = conn.cursor(pymysql.cursors.DictCursor)
print(f"DB_HOST={cfg['host']}  DB_NAME={cfg['database']}  hoy={date.today()}")
print("=" * 70)


def q1(sql, args=None):
    cur.execute(sql, args or ())
    return list(cur.fetchone().values())[0]


def show(sql, args=None):
    cur.execute(sql, args or ())
    for r in cur.fetchall():
        print("   ", r)


print(f"\n[1] Total is_active=1 (todos los servicios): "
      f"{q1('SELECT COUNT(*) FROM subscriptions WHERE is_active=1')}")

print("\n[2] is_active=1 por servicio:")
show("""SELECT sv.service_id, sv.name, COUNT(*) AS n
       FROM subscriptions s JOIN services sv ON s.service_id=sv.service_id
       WHERE s.is_active=1 GROUP BY sv.service_id, sv.name""")

print(f"\n[3] is_active=1 Y NO vencidas (end_date>=hoy): "
      f"{q1('SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND end_date>=CURDATE()')}")

print(f"\n[4] is_active=1 pero YA VENCIDAS (end_date<hoy) → deberían estar inactivas: "
      f"{q1('SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND end_date<CURDATE()')}")

print("\n[5] Vencidas-pero-activas por servicio:")
show("""SELECT sv.name, COUNT(*) AS n
       FROM subscriptions s JOIN services sv ON s.service_id=sv.service_id
       WHERE s.is_active=1 AND s.end_date<CURDATE() GROUP BY sv.name""")

print(f"\n[6] VIP (sid=2) activas+vigentes, FILAS: "
      f"{q1('SELECT COUNT(*) FROM subscriptions WHERE is_active=1 AND service_id=2 AND end_date>=CURDATE()')}")
print(f"[7] VIP (sid=2) activas+vigentes, USUARIOS DISTINTOS: "
      f"{q1('SELECT COUNT(DISTINCT user_telegram_id) FROM subscriptions WHERE is_active=1 AND service_id=2 AND end_date>=CURDATE()')}")

print("\n[8] Usuarios con MÚLTIPLES subs VIP activas+vigentes (duplicados):")
show("""SELECT user_telegram_id, COUNT(*) AS n
       FROM subscriptions
       WHERE is_active=1 AND service_id=2 AND end_date>=CURDATE()
       GROUP BY user_telegram_id HAVING COUNT(*)>1 ORDER BY n DESC LIMIT 15""")

print(f"\n[9] Total filas en subscriptions: {q1('SELECT COUNT(*) FROM subscriptions')}")
print(f"[10] Total users: {q1('SELECT COUNT(*) FROM users')}")

conn.close()
