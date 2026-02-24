# GastAI

Agente financiero personal que:
1. Lee notificaciones de gasto desde el correo (ej: banco / tarjeta).
2. Extrae transacciones (monto, comercio, fecha/hora).
3. Las guarda en DuckDB local.
4. Calcula gasto acumulado por categoría y alerta si rompes tu presupuesto semanal.

## Estado actual (Fase 1)
- Proyecto inicializado.
- Base de datos local (DuckDB) lista para crearse.
- Estructura para parser, agente, budgets.
- Script `main_local.py` (aún simulado) será el entrypoint.

## Futuro
- Conectar a Gmail API para leer correos reales.
- FastAPI + endpoint `/webhook/email`.
- Notificación push (Telegram).

## Privacidad
- Tus transacciones se guardan localmente en `./data/finanzas.duckdb`.
- Ese archivo NO debe subirse a git.
- Las credenciales (Gmail, Telegram, límites de gasto) van en `.env`, que tampoco se sube.