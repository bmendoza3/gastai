# GastAI — Especificación del Producto

## Visión
Agente financiero personal que opera por WhatsApp.
Sin app, sin UI web. Todo sucede en el chat.

**Usuario objetivo**: personas que quieren entender sus gastos sin esfuerzo.
El bot hace el trabajo pesado — ellos solo clasifican con un mensaje.

---

## Flujo principal

```
[Banco] ──email──▶ [Gmail] ──polling──▶ [Ingest] ──▶ [DuckDB]
                                                          │
                                              [APScheduler cada 5min]
                                                          │
                                              [WhatsApp: notifica al usuario]
                                                          │
                                              [Usuario responde por chat]
                                                          │
                                              [Agente LLM clasifica tx]
```

### Notificación al llegar un gasto
```
GastAI: Nuevo gasto detectado 👀
  📍 Uber Eats
  💸 $8.450 CLP
  🕐 Hoy 13:42

¿Cómo lo clasificas?
  Categoría: transporte / comida / entretención / ...
  Tipo: previsto o imprevisto?
```

### El usuario responde (lenguaje natural)
```
Usuario: "comida, era previsto"
GastAI: "Listo ✅ Registrado como Comida · Previsto"
```

### Consulta de resumen
```
Usuario: "¿cómo voy esta semana?"
GastAI: "Semana 24/03 – 30/03
  🍔 Comida:       $42.300
  🚗 Transporte:   $18.900
  🎬 Entretención: $9.990
  Total: $71.190

[imagen con gráfico de torta]"
```

---

## Usuarios y multi-tenancy

### Identificación
- Cada usuario se identifica por su número de WhatsApp (`+56912345678`)
- No hay login, no hay contraseña
- P3: OTP por WhatsApp para onboarding

### Config de usuario (PoC — tabla `users` en DuckDB)
```sql
INSERT INTO users VALUES (
    '+56912345678',         -- phone
    'Bastián',              -- name
    'from:(@bancochile.cl) "compra"',  -- gmail_query
    'bancochile',           -- bank parser
    NOW()
);
```

### Onboarding (P3)
1. Usuario manda "hola" al número de GastAI
2. Bot pregunta nombre + banco
3. Solicita acceso Gmail (OAuth flow por URL)
4. Listo — empieza a monitorear

---

## Categorías de gasto

Enum fijo (extensible). El LLM sugiere, el usuario confirma o corrige.

| Código | Etiqueta | Ejemplos |
|---|---|---|
| `transporte` | Transporte | Uber, bencina, bus, metro |
| `comida` | Comida | Restaurants, delivery, cafés |
| `supermercado` | Supermercado | Lider, Jumbo, Santa Isabel |
| `salud` | Salud | Farmacia, médico, dentista |
| `entretenimiento` | Entretención | Netflix, cine, conciertos |
| `suscripciones` | Suscripciones | Spotify, apps, membresías |
| `ropa` | Ropa | Tiendas, Zara, Falabella |
| `educacion` | Educación | Cursos, libros, colegio |
| `hogar` | Hogar | Supermercado hogar, ferretería |
| `trabajo` | Trabajo | Coworking, materiales, software |
| `viajes` | Viajes | Vuelos, hoteles, airbnb |
| `otros` | Otros | Lo que no encaja |

### Intención de compra
- `previsto` — era un gasto planificado
- `imprevisto` — surgió sin planificarlo

---

## Perfil de usuario (base para estrategias)

Acumulado de clasificaciones → patrones:

```
Bastián (30 días):
  Top categoría: Comida (38% del gasto)
  Mayoría de gastos: imprevistos (61%)
  Gasto hormiga detectado: Uber Eats 4x esta semana ($34.200)
  Patrón: gastos altos los viernes
```

Estos perfiles permiten (P3+):
- Alertas personalizadas ("gastaste más de lo habitual en comida")
- Sugerencias de ahorro ("si evitas 2 deliveries/semana ahorras ~$30.000/mes")
- Comparativa mes a mes

---

## Detección de gastos hormiga

**Definición**: misma categoría/comercio, múltiples veces en poco tiempo, montos pequeños que suman.

**Regla base**:
- Mismo comercio ≥ 3 veces en 7 días → alerta
- Categoría con >40% del gasto total semanal → mención en reporte

**Mensaje de alerta**:
```
GastAI: ⚠️ Gasto hormiga detectado
Uber Eats: 4 pedidos esta semana → $34.200
¿Lo tenías en radar?
```

---

## Reportes y gráficos

Todos enviados como imagen PNG por WhatsApp.

| Reporte | Frecuencia | Contenido |
|---|---|---|
| Resumen semanal | Automático cada lunes | Gasto por categoría (torta) + total |
| Consulta libre | A pedido ("¿cómo voy?") | Barras por categoría + texto |
| Gasto hormiga | Al detectar | Texto simple con alerta |
| Comparativa | A pedido ("vs mes pasado") | Barras comparativas |

**Stack gráficos**: matplotlib → BytesIO → upload Meta API → enviar como imagen

---

## Parsers bancarios

| Banco | Estado | Parser |
|---|---|---|
| Banco de Chile | ✅ Implementado | `parsers/bancodechile.py` |
| Santander | ⬜ Pendiente | `parsers/santander.py` |
| BCI | ⬜ Pendiente | `parsers/bci.py` |
| Scotiabank | ⬜ Pendiente | `parsers/scotiabank.py` |
| MACH / FPAY | ⬜ Pendiente | Requiere otro canal (no email) |

Todos los parsers implementan el mismo contrato:
```python
def parse_<banco>_email(sender: str, subject: str, body: str) -> ParsedExpense | None:
    ...

@dataclass
class ParsedExpense:
    description: str    # comercio / descripción
    amount_clp: float   # monto (negativo = gasto)
    timestamp: datetime
    account_hint: str   # últimos 4 dígitos o alias (metadata, no ID de usuario)
```

---

## Stack técnico

| Capa | Tecnología | Razón |
|---|---|---|
| API | FastAPI | Ya implementado, async nativo |
| DB | DuckDB | Local, embebido, SQL completo, rápido para analytics |
| LLM | Ollama (dev) / Groq (gratuito) / Claude (prod) | OpenAI-compatible, swap sin cambiar código |
| Scheduling | APScheduler | Embebido en FastAPI, simple |
| WhatsApp | Meta Cloud API | Estándar, escalable |
| Gráficos | matplotlib | Liviano, sin servidor |
| Email | Gmail API OAuth2 | Ya implementado |

---

## Variables de entorno requeridas

```env
# LLM
LLM_BASE_URL=http://localhost:11434/v1
LLM_API_KEY=ollama
LLM_MODEL=llama3.2:3b

# WhatsApp
META_PHONE_NUMBER_ID=
META_ACCESS_TOKEN=
META_VERIFY_TOKEN=gastai_verify_2025

# Gmail (por usuario — en el futuro, por user en DB)
GMAIL_CREDENTIALS_FILE=credentials/gmail_credentials.json
GMAIL_TOKEN_FILE=credentials/gmail_token.json

# App
POLLING_INTERVAL_MINUTES=5
MAX_USERS=50
```

---

## Escalabilidad (visión App Store)

El backend ya es una API REST. Para escalar:

1. **Auth**: reemplazar config YAML/DB por auth real (JWT o magic link por WhatsApp)
2. **DB**: migrar DuckDB → PostgreSQL (mismas queries SQL, cambio de driver)
3. **Gmail por usuario**: OAuth flow propio por usuario, tokens en DB
4. **Deploy**: containerizar (Docker), deploy en Railway/Fly/GCP
5. **App móvil**: consume la misma API REST, WhatsApp sigue siendo el canal principal
6. **Multi-banco**: parsers adicionales por demanda de usuarios

El código está diseñado para que estos cambios sean localizados, no rewrites.
