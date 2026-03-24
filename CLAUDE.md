# GastAI — Instrucciones para Claude

## Qué es este proyecto
Agente financiero personal que opera **exclusivamente por WhatsApp**.
Lee alertas de gasto del email bancario del usuario, las ingesta en DuckDB,
y notifica proactivamente al usuario para que las clasifique por chat.

PoC inicial: ~6 usuarios (familia/cercanos). Diseñado para escalar a producto público.

## Stack
- **Backend**: FastAPI + Uvicorn (Python 3.12)
- **DB**: DuckDB embebido (`data/finanzas.duckdb`)
- **LLM**: OpenAI-compatible — Ollama local por defecto, Groq como fallback gratuito, Claude/GPT en prod
- **Mensajería**: Meta WhatsApp Cloud API (chip Entel pendiente de registrar en Meta Business)
- **Ingesta**: Gmail API (OAuth2 por usuario)
- **Scheduling**: APScheduler embebido en FastAPI (polling Gmail cada N min)

## Arquitectura de datos — MULTI-TENANT desde el inicio

Todo gira alrededor de `user_phone` como identificador primario.

### Tablas principales
```sql
users (
    phone        TEXT PRIMARY KEY,   -- +56912345678
    name         TEXT,
    gmail_query  TEXT,               -- filtro Gmail de este usuario
    bank         TEXT,               -- 'bancochile' | 'santander' | etc.
    created_at   TIMESTAMP
)

transactions (
    tx_id        TEXT PRIMARY KEY,
    user_phone   TEXT REFERENCES users(phone),
    ts           TIMESTAMP,
    description  TEXT,
    amount_clp   DOUBLE,
    category     TEXT,               -- enum: ver CATEGORÍAS
    intent       TEXT,               -- 'previsto' | 'imprevisto'
    needs_review BOOLEAN,
    source       TEXT                -- 'gmail' | 'manual'
)
```

> **IMPORTANTE**: La columna es `user_phone`, NO `account_id`. El campo `account_id`/`account_hint`
> del banco es metadata del parser, no el identificador de usuario.

## Categorías de gasto (enum fijo)
```
transporte, comida, supermercado, salud, entretenimiento,
suscripciones, ropa, educacion, hogar, trabajo, viajes, otros
```
El LLM puede *sugerir* la categoría, pero debe ser una de estas.

## Patrones de código

### Endpoints
```python
from fastapi import APIRouter, Request
router = APIRouter()

@router.post("/endpoint")
async def handler(request: Request):
    db = request.app.state.db  # conexión DuckDB inyectada via lifespan
    ...
```

### Notificación proactiva
```python
# Al ingestar una tx nueva, SIEMPRE notificar al usuario
await notify_user(phone, tx)  # llama send_message() de whatsapp_cloud.py
```

### LLM
- Usar siempre el cliente OpenAI-compatible configurado en `agents.py`
- No hardcodear modelos: leer de `settings.LLM_MODEL`
- El sistema debe funcionar con modelos pequeños (llama3.2:3b) — prompts concisos

## LLM — Setup actual
Ollama está corriendo (puerto 11434) pero **sin modelos descargados**.
Opciones en orden de preferencia para desarrollo:
1. `ollama pull llama3.2:3b` — más liviano, suficiente para clasificación
2. Groq API (gratuita, OpenAI-compatible) — cambiar solo `.env`:
   ```
   LLM_BASE_URL=https://api.groq.com/openai/v1
   LLM_API_KEY=gsk_...
   LLM_MODEL=llama-3.3-70b-versatile
   ```

## WhatsApp — Setup pendiente
1. Abrir chip Entel + registrar número en WhatsApp Business
2. Crear Meta Business Account → WhatsApp → agregar número
3. Obtener `META_PHONE_NUMBER_ID` y `META_ACCESS_TOKEN`
4. Para desarrollo local: usar ngrok + endpoint `/whatsapp/webhook` (test sin Meta)

## Roadmap de implementación

### P1 — Flujo completo mínimo (hacer primero)
- [ ] Migrar schema DB: `account_id` → `user_phone`, agregar tabla `users`
- [ ] Config de usuarios (YAML o tabla `users`)
- [ ] APScheduler: polling Gmail cada 5 min por usuario
- [ ] Notificación proactiva al ingestar tx nueva
- [ ] Categorías fijas en tools + validación

### P2 — Reportes y análisis
- [ ] Gráfico matplotlib → PNG → enviar por WhatsApp
- [ ] Reporte semanal automático (resumen + gráfico)
- [ ] Detección gastos hormiga (mismo comercio >3 veces/semana)

### P3 — Escalabilidad
- [ ] Auth por usuario (OTP por WhatsApp)
- [ ] Más parsers bancarios (Santander, BCI, Scotiabank)
- [ ] Telegram adapter (misma lógica, distinto transport)
- [ ] API REST para futura app móvil

## Qué NO hacer
- No crear UI web — todo por WhatsApp
- No usar `account_id` del banco como identificador de usuario
- No hardcodear números de teléfono ni tokens en código
- No romper compatibilidad del endpoint `/whatsapp/incoming` (Meta lo llama)
- No usar f-strings para inyectar valores en SQL — usar parámetros `?`
