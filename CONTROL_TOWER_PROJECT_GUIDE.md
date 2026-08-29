# NextWave Hackathon 2026 — Challenge 2: The Control Tower
## Guía completa del proyecto, arquitectura, estrategia y plan de trabajo

> Documento interno del equipo. Objetivo: que cualquiera de las 4 pueda abrir el repo `nw`, entender qué ya existe, qué vamos a construir, cómo se divide el trabajo y cómo defender las decisiones frente al jurado.

---

## 0. TL;DR — Qué estamos construyendo

Elegimos **Challenge 2 — The Control Tower (Yuno)**.

Vamos a construir una torre de control de pagos que:

1. recibe un flujo continuo de transacciones sintéticas;
2. aprende cuál es la tasa de aprobación esperada según el comportamiento histórico;
3. detecta caídas reales de conversión sin alertar por ruido normal;
4. estima cuánto dinero se está perdiendo;
5. investiga la causa raíz cruzando dimensiones de pagos;
6. usa un agente LLM para explicar la evidencia, priorizar incidentes y recomendar una acción;
7. muestra todo en una interfaz visual por merchant;
8. soporta que el jurado inyecte un incidente desconocido y lo detecte sin que el equipo toque nada.

La idea central es:

```text
DATA / STREAM
    ↓
BASELINE ESTADÍSTICO
    ↓
ANOMALY DETECTOR
    ↓
INCIDENT
    ↓
ROOT-CAUSE ENGINE
    ↓
EVIDENCE PACKAGE
    ↓
LLM / AGENT
    ↓
EXPLANATION + PRIORITY + RECOMMENDATION
    ↓
DASHBOARD / ALERT
```

**Regla de oro:** el LLM no inventa el diagnóstico.  
La evidencia sale de datos + estadística + tools determinísticas. El LLM la orquesta, sintetiza y explica.

---

# 1. Qué exige oficialmente el challenge

El Challenge 2 pide un sistema que monitoree pagos en vivo y:

- detecte caídas de conversion / approval rate que importen;
- distinga incidentes reales de ruido normal, hora del día, fines de semana y variación estadística;
- diagnostique la causa raíz navegando dimensiones como:
  - Merchant
  - Provider
  - Payment Method
  - Country
  - Issuing Bank
  - Decline Code
- muestre evidencia:
  - qué cayó;
  - desde cuándo;
  - a quién afecta;
  - cuánto dinero cuesta;
  - por qué creemos ese diagnóstico;
- priorice varios incidentes simultáneos;
- diga honestamente **“insufficient evidence”** cuando no puede aislar una causa;
- recomiende una acción al humano;
- **NO ejecute automáticamente la remediación** en el MVP;
- soporte un **trial by fire**: el jurado inyecta un incidente no ensayado y el sistema debe reaccionar solo.

Además, para todos los challenges se exige:

- presentación;
- demo;
- repo público con README;
- architecture diagram;
- decision log;
- defensa técnica de cada decisión.

La defensa técnica pesa tanto como la demo, así que debemos poder explicar todo lo que construimos.

---

# 2. Qué ya existe en el repo `nw`

Ya tenemos un starter genérico funcional creado con Codex.

Estructura aproximada:

```text
nw/
├── AGENTS.md
├── REFERENCES.md
├── backend/
│   ├── __init__.py
│   ├── agent.py
│   ├── config.py
│   ├── main.py
│   ├── schemas.py
│   └── tools.py
├── frontend/
│   └── app.py
├── data/
│   └── sample_data.csv
├── tests/
│   └── test_health.py
├── .env.example
├── .gitignore
├── pytest.ini
├── requirements.txt
└── README.md
```

El starter ya probó este circuito:

```text
Streamlit
   ↓
FastAPI
   ↓
agent.py
   ↓
tools.py
   ↓
Pydantic structured result
   ↓
Streamlit
```

También tiene **MOCK MODE**, por lo que puede funcionar sin llamar a OpenAI.

Esto es importante porque:

- podemos construir casi todo sin gastar API;
- tenemos fallback si falla internet o API;
- mañana NO arrancamos desde cero;
- vamos a adaptar archivos existentes en vez de rehacer infraestructura.

### Archivos principales

#### `backend/main.py`
Expone los endpoints de FastAPI.

Por ejemplo:

```text
GET /health
POST /analyze
```

No debería cambiar demasiado.

#### `backend/schemas.py`
Define los contratos de datos con Pydantic.

Mañana este archivo pasa de schemas genéricos a:

- `Transaction`
- `Incident`
- `Diagnosis`
- `EvidencePackage`
- posiblemente `IncidentInjection`

#### `backend/tools.py`
Contiene funciones determinísticas.

En el starter son tools genéricas. Para Control Tower serán cosas como:

```text
get_live_metrics()
analyze_dimension()
estimate_loss()
rank_root_causes()
find_similar_incident()
```

#### `backend/agent.py`
Es la capa de OpenAI / agente.

Debe recibir evidencia estructurada y devolver:

- explicación;
- prioridad;
- confidence;
- recomendación;
- eventualmente abstención.

#### `frontend/app.py`
Es la interfaz Streamlit actual.

La vamos a transformar en dashboard de Control Tower.

---

# 3. AGENTS.md, REFERENCES.md y skills

## AGENTS.md

Es el archivo que le explica a Codex **cómo queremos que trabaje en este repo**.

Reglas importantes:

- priorizar simplicidad y confiabilidad;
- construir un happy path completo antes de agregar features;
- no sobrearquitecturar;
- preservar código que ya funciona;
- probar realmente antes de decir “done”;
- usar herramientas externas sólo si resuelven un problema concreto.

## REFERENCES.md

Es una lista de referencias externas que Codex puede consultar si hace falta.

No significa que todos esos repos estén instalados.

### Referencias disponibles

#### OpenAI Cookbook
Usar si necesitamos ejemplos oficiales de:

- Responses API;
- tool calling;
- structured outputs;
- agents;
- evals;
- retrieval.

#### OpenAI Agents SDK
Instalar **sólo si realmente lo necesitamos**.

No hay obligación de usarlo.

#### Matt Pocock Skills
Ya instalamos varias skills útiles para Codex, por ejemplo:

- `prototype`
- `diagnosing-bugs`
- `code-review`
- `grill-with-docs`
- `resolving-merge-conflicts`

Sirven para que Codex trabaje mejor; **no forman parte del producto**.

#### Vercel Agent Skills
Usar sólo si después migramos el frontend a React/Next.js.

#### Vercel Chatbot
Referencia de UI/UX para apps de IA.

#### Awesome AI Agents
Sólo para descubrir herramientas si aparece una necesidad concreta.

### Regla para mañana

No preguntar:

> “¿Qué tecnología podemos meter?”

Preguntar:

> “¿Qué problema concreto necesitamos resolver?”

Y recién ahí consultar una referencia.

---

# 4. Modelo de datos sintético

## Merchants

Usaremos:

- **Rappi**
- **Carrefour**
- **Despegar**

Conceptualmente representan tres perfiles distintos de negocio:

- delivery / tecnología;
- retail;
- viajes / movilidad.

## Países

Los tres del caso oficial:

- **Mexico**
- **Brazil**
- **Colombia**

## Providers

- **Stripe**
- **Adyen**
- **dLocal**

## Payment Methods

MVP:

- `CARD` — los tres países;
- `PIX` — Brazil;
- `PSE` — Colombia;
- `OXXO` — Mexico.

Esto mantiene el dominio pequeño pero suficientemente realista.

## Issuing Banks

### Mexico

- BBVA México
- Banorte
- Santander México
- Citibanamex

### Brazil

- Itaú
- Bradesco
- Banco do Brasil
- Nubank

### Colombia

- Bancolombia
- Davivienda
- Banco de Bogotá
- BBVA Colombia

No afirmamos que todos sean integraciones específicas de Yuno. Son valores realistas para un dataset sintético.

## Decline Codes

MVP:

| Code | Meaning |
|---|---|
| `05` | Do not honor |
| `51` | Insufficient funds |
| `54` | Expired card |
| `57` | Transaction not permitted |
| `61` | Exceeds amount limit |
| `91` | Issuer unavailable |
| `96` | System malfunction |

Para aprobadas:

```text
status = approved
decline_code = null
```

## Transaction schema

```text
Transaction
- transaction_id
- merchant
- provider
- payment_method
- country
- issuing_bank
- decline_code
- status
- amount
- timestamp
```

---

# 5. Histórico, split temporal y baseline

Vamos a simular **1 año** de historia.

La idea es dividir temporalmente:

```text
Jan–Apr   → TRAIN
May–Aug   → VALIDATION
Sep–Dec   → TEST
```

Esto es un **time split** real: no mezclamos futuro con pasado.

## ¿Qué aprende el baseline?

Para el MVP, la idea base es aprender el comportamiento esperado de conversión según:

```text
merchant × country × hour_of_week
```

`hour_of_week` tiene 168 slots:

```text
Monday 00:00
Monday 01:00
...
Sunday 23:00
```

Así el sistema aprende que:

- Rappi puede comportarse distinto un viernes a la noche;
- Carrefour puede tener otra curva el domingo;
- Despegar puede variar por hora/día.

Esto ayuda a no confundir estacionalidad normal con incidentes.

Además, para mejorar el trial-by-fire sin complicar demasiado, podemos precomputar baselines para slices adicionales con volumen suficiente, por ejemplo:

```text
merchant × country × provider
merchant × country × payment_method
merchant × country × issuing_bank
```

No hace falta un deep learning model.

---

# 6. Detector de anomalías MVP

La primera versión debe ser estadística, simple y defendible.

Para cada ventana live:

```text
expected_conversion
actual_conversion
n_transactions
```

Regla inicial sugerida:

```text
minimum volume >= 50 transactions
AND
absolute drop >= 8 percentage points
AND
z-score <= -3
AND
persists for 2 consecutive windows
```

Ejemplo normal:

```text
expected = 89%
actual = 86%
→ NO ALERT
```

Ejemplo anómalo:

```text
expected = 89%
actual = 61%
→ ALERT
```

### Ventana live

Propuesta inicial:

```text
5 simulated minutes
```

El tiempo de demo puede acelerarse.

Ejemplo:

```text
1 segundo real ≈ 1 minuto simulado
```

No queremos llamar a APIs por cada transacción.

El pipeline debe agrupar datos por ventanas.

---

# 7. Simulación del stream

No vamos a hacer:

```text
transaction → OpenAI
transaction → OpenAI
transaction → OpenAI
```

Eso sería lento, caro y técnicamente innecesario.

Haremos:

```text
Synthetic generator
      ↓
batch / window of transactions
      ↓
aggregation
      ↓
statistical detector
      ↓
only if anomaly:
root-cause + OpenAI
```

Podemos generar, por ejemplo:

```text
50–100 transactions per tick
```

para que el dashboard se vea vivo sin sobrecargar.

---

# 8. Root Cause Engine — cómo funciona

Detectar:

> “Rappi Brazil cayó”

NO es suficiente.

La causa raíz tiene que explicar **qué dimensión o intersección está fallando**.

Ejemplo:

```text
Rappi · Brazil

Expected: 91%
Observed: 63%
```

Primero analizamos provider:

```text
Stripe   90 → 88
Adyen    91 → 89
dLocal   92 → 41
```

Entonces investigamos dentro de dLocal:

```text
dLocal × payment_method

CARD   91 → 89
PIX    93 → 27
```

Después decline codes:

```text
code 91
normal share = 3%
live share = 48%
```

Resultado:

```text
ROOT CAUSE

Rappi
× Brazil
× dLocal
× PIX
× decline code 91

since 14:03
```

## Implementación

El root-cause engine debe ser mayormente Python / pandas.

Tools posibles:

```text
analyze_by_provider()
analyze_by_payment_method()
analyze_by_issuing_bank()
analyze_decline_codes()
rank_candidate_slices()
estimate_explained_loss()
```

El motor puede explorar slices y quedarse con las que:

- tienen suficiente volumen;
- muestran deterioro estadísticamente relevante;
- explican una proporción grande del exceso de rechazos / pérdida.

## Insufficient evidence

Ejemplo:

```text
dLocal explains 40%
Stripe explains 37%
Adyen explains 23%
```

No hay una causa dominante.

Resultado:

```text
diagnosis_status = insufficient_evidence
```

El LLM debe explicarlo claramente y NO inventar una causa.

---

# 9. Cálculo del impacto económico

NO debemos sumar todos los rechazos.

Siempre existe un nivel normal de rechazo.

Usaremos:

```text
expected_approved_amount
=
total_attempted_amount × expected_approval_rate
```

y luego:

```text
estimated_loss
=
expected_approved_amount - actual_approved_amount
```

Ejemplo:

```text
attempted = $100,000
expected approval = 90%
expected approved = $90,000
actual approved = $62,000

estimated incident loss = $28,000
```

También podemos llevarlo a:

```text
estimated_loss_per_hour
```

para la vista ejecutiva.

---

# 10. Incident schema

Propuesta:

```text
Incident
- incident_id
- merchant
- country
- detected_at
- expected_conversion
- actual_conversion
- conversion_drop_pp
- affected_volume
- estimated_loss
- estimated_loss_per_hour
- severity
- anomaly_score
- status
```

---

# 11. Diagnosis / Evidence schema

```text
EvidenceItem
- dimension
- value
- baseline_metric
- live_metric
- delta
- sample_size
- explained_loss_share

Diagnosis
- incident_id
- root_cause_dimensions
- evidence[]
- confidence
- diagnosis_status
- explanation
- recommended_action
```

---

# 12. Rol del LLM / agent

El LLM NO debería recibir miles de transacciones.

Recibe un `EvidencePackage` ya calculado.

Ejemplo:

```json
{
  "merchant": "Rappi",
  "country": "Brazil",
  "provider": "dLocal",
  "payment_method": "PIX",
  "expected_conversion": 0.93,
  "actual_conversion": 0.27,
  "decline_code": "91",
  "estimated_loss_per_hour": 5820,
  "confidence": 0.94
}
```

El agente produce algo como:

```text
dLocal's PIX processing in Brazil has degraded significantly since 14:03.
The change is concentrated in decline code 91 and explains most of the lost approvals.

Estimated impact: $5,820/hour.

Recommended action:
Investigate the dLocal PIX route and consider rerouting affected traffic to the healthiest provider.
```

El agente:

- sintetiza;
- prioriza;
- adapta la explicación a humano;
- recomienda;
- sabe abstenerse.

No calcula la estadística principal.

---

# 13. Recomendación sí; ejecución automática no

El challenge pide recomendar una acción.

Por lo tanto:

```text
DETECT
→ DIAGNOSE
→ RECOMMEND
```

pero NO:

```text
→ auto-reroute real traffic
```

Eso queda fuera del MVP.

## Post-MVP recomendado: Remediation Simulator

Podemos simular:

```text
Option A
reroute 25% to Adyen
expected conversion 74%

Option B
reroute 50% to Adyen
expected conversion 84%

Option C
reroute 75% to Stripe
expected conversion 89%
```

El agente recomienda la mejor.

Pero la UI muestra:

```text
RECOMMENDATION ONLY
Human approval required
```

---

# 14. Incident injection — trial by fire

Esta es una feature MVP obligatoria.

El jurado debe poder crear un incidente que nuestro detector NO conoce de antemano.

Panel de testing / judge:

```text
INJECT INCIDENT

Merchant: Rappi
Country: Brazil
Provider: dLocal
Payment Method: PIX

Target approval rate: 35%

[ INJECT ]
```

Antes:

```text
approval ≈ 92%
```

Después de inject:

```text
generator empieza a producir aprobaciones ≈ 35%
```

Importante:

**el detector NO recibe la configuración del injector.**

Sólo ve nuevas transacciones.

El sistema debe descubrir el incidente desde los datos.

### Por qué no usamos “Failure severity”

Preferimos:

```text
Target approval rate
```

porque es más interpretable y directamente controlable.

---

# 15. Dashboard MVP

Primero usamos **Streamlit** porque ya está funcionando.

No migramos a Next.js antes de tener el happy path.

## Navegación

Tenemos 3 merchants:

```text
[Rappi] [Carrefour] [Despegar]
```

Cada merchant representa un usuario/contexto independiente.

En MVP no implementamos authentication real.

El backend debe filtrar estrictamente por `merchant`.

Si después usamos Supabase, podemos agregar auth/RLS.

## Vista por merchant

Parte superior:

```text
ALERT CARD
- severity
- country
- provider / failing slice
- conversion drop
- money lost
- diagnosis
- recommendation
```

Parte inferior:

```text
LIVE MONITORING
- Mexico
- Brazil
- Colombia
```

Gráficos mostrando approval rate y salud por provider.

También debe haber una vista ejecutiva resumida.

---

# 16. Alerting MVP

No necesitamos WhatsApp en el MVP.

Basta con generar un objeto de alerta estructurado:

```json
{
  "severity": "critical",
  "merchant": "Rappi",
  "country": "Brazil",
  "root_cause": "dLocal × PIX × decline code 91",
  "estimated_loss_per_hour": 5820,
  "recommendation": "Investigate dLocal PIX route and consider rerouting."
}
```

y mostrarlo claramente en UI / notification center.

WhatsApp, Slack o email pueden ir después.

---

# 17. Context Awareness

La idea de noticias, clima, partidos, feriados u outages externos queda **POST-MVP**.

No debe contaminar el diagnóstico principal.

Orden correcto:

```text
internal transaction evidence
        ↓
root cause
        ↓
optional external context enrichment
```

Nunca usar contexto externo como explicación causal sin evidencia interna.

---

# 18. Base de datos

El starter actual funciona con datos locales / CSV.

Eso alcanza para empezar.

No hace falta Supabase para el MVP si no agrega valor.

Podemos agregar Supabase si necesitamos:

- persistencia;
- historial de incidentes;
- múltiples usuarios reales;
- auth;
- row-level security;
- compartir estado entre procesos.

No agregar DB sólo para “usar tecnología”.

---

# 19. Frontend pro: Next.js + Vercel

El orden correcto es:

```text
PHASE 1
Streamlit MVP
→ everything works

PHASE 2
optional Next.js / React
→ Vercel
```

No reemplazar Streamlit antes de tener una demo segura.

La ventaja es que el backend FastAPI + agent + tools puede mantenerse.

```text
Next.js
   ↓
FastAPI
   ↓
detector / RCA / OpenAI
```

Si Next falla, Streamlit queda como fallback.

---

# 20. Test set sintético

Construiremos un harness con al menos 30 escenarios.

| # | Scenario | Expected |
|---:|---|---|
| 1 | Normal weekday Mexico | No alert |
| 2 | Normal weekday Brazil | No alert |
| 3 | Normal weekday Colombia | No alert |
| 4 | Weekend natural variation | No alert |
| 5 | Low-volume random noise | No alert |
| 6 | One high-value decline | No alert |
| 7 | Stripe degradation Brazil | Detect Stripe |
| 8 | Adyen degradation Mexico | Detect Adyen |
| 9 | dLocal degradation Colombia | Detect dLocal |
| 10 | PIX outage Brazil | Detect PIX |
| 11 | PSE outage Colombia | Detect PSE |
| 12 | OXXO outage Mexico | Detect OXXO |
| 13 | BBVA México outage | Detect issuing bank |
| 14 | Itaú over-declining | Detect issuing bank |
| 15 | Bancolombia outage | Detect issuing bank |
| 16 | Decline code 91 spike | Detect code |
| 17 | dLocal × Itaú × Brazil | Detect intersection |
| 18 | Stripe × PSE × Colombia | Detect intersection |
| 19 | Adyen × BBVA × Mexico | Detect intersection |
| 20 | Rappi merchant-specific failure | Detect merchant |
| 21 | Despegar card-only degradation | Detect method / merchant |
| 22 | Stripe BR + BBVA MX | Detect 2 incidents |
| 23 | PSE CO + Itaú BR | Detect 2 incidents |
| 24 | Two incidents same country/different merchants | Separate |
| 25 | Critical + mild incident | Correct priority |
| 26 | Low-volume suspicious slice | Insufficient evidence |
| 27 | Two equally plausible causes | Insufficient evidence |
| 28 | Natural time-of-day drop | No alert |
| 29 | Repeat of previous incident | Recognize repeat if memory is implemented |
| 30 | Random unseen injected slice | Generic detection works |

## Métricas

Mediremos:

```text
Detection recall
False-positive rate
Root-cause accuracy
Multi-incident separation accuracy
Abstention accuracy
Mean detection latency
Estimated-loss error
```

No inventamos métricas en el pitch.

Se miden realmente.

---

# 21. Uso de OpenAI y presupuesto

La estrategia NO es llamar OpenAI para todo.

Usamos:

```text
Python:
- synthetic data
- baseline
- detector
- loss calculation
- root cause statistics

OpenAI:
- only when an incident exists
- explanation
- prioritization
- recommendation
- uncertainty
```

Durante desarrollo:

```text
MOCK_MODE=true
```

La mayoría del tiempo.

Cuando el core esté estable:

```text
MOCK_MODE=false
```

y hacemos evaluaciones reales.

Si quedan créditos al final, se usan en trabajo de alto valor:

- múltiples runs del test set;
- prompt variants;
- adversarial judge-like inputs;
- uncertainty tests;
- evals;
- code review;
- bug diagnosis;
- stress testing;
- Q&A técnico.

No agregamos features inútiles sólo para gastar crédito.

---

# 22. DECISIONS.md — obligatorio y muy importante

Crear:

```text
DECISIONS.md
```

Ejemplo:

```markdown
## Decision: seasonal statistical baseline vs Isolation Forest

Alternatives:
1. Fixed threshold
2. Isolation Forest
3. Seasonal baseline + z-score

Chosen:
Seasonal baseline + z-score

Why:
- interpretable
- low latency
- handles hour/week seasonality
- easy to validate
- robust for unseen incident injection
- simpler to defend under time pressure
```

Registrar decisiones como:

- CSV/local vs Supabase;
- Streamlit vs Next.js;
- z-score/EWMA vs Isolation Forest;
- deterministic RCA vs LLM-only;
- 5-minute windows;
- threshold selection;
- no auto-remediation;
- mock mode;
- OpenAI only on incidents.

Esto nos ayuda muchísimo en la defensa técnica.

---

# 23. División del equipo

Después de congelar los schemas, las cuatro pueden trabajar en paralelo.

## Persona A — Data / Simulator

Responsable de:

```text
historical generator
live stream
incident injector
test scenarios
```

## Persona B — ML / Detection

Responsable de:

```text
baseline
rolling metrics
anomaly detector
monetary impact
incident separation / priority
```

## Persona C — Root Cause / AI

Responsable de:

```text
drill-down engine
evidence package
OpenAI agent
explanation
recommendation
insufficient evidence
```

## Persona D — UI / Integration

Responsable de:

```text
merchant dashboard
live charts
incident cards
judge injector
FastAPI integration
```

Todas deben entender el sistema completo para defenderlo.

---

# 24. Orden de implementación

## Paso 0 — Freeze contracts

Antes de separarnos:

```text
Transaction
Incident
EvidenceItem
Diagnosis
InjectionConfig
```

Todas importamos los mismos schemas.

## Paso 1 — Construir un happy path mínimo

Objetivo:

```text
normal stream
↓
inject one incident
↓
detector fires
↓
root cause found
↓
LLM/mock explanation
↓
UI shows alert
```

Nada más.

## Paso 2 — Trial by fire

Agregar:

```text
judge-controlled injection
unknown slice
```

## Paso 3 — Robustness

Agregar:

- normal noise;
- insufficient evidence;
- two simultaneous incidents;
- prioritization.

## Paso 4 — Evaluation

Ejecutar test harness.

## Paso 5 — Polish

Recién después:

- mejores gráficos;
- UI pro;
- Next/Vercel;
- external context;
- remediation simulator;
- WhatsApp;
- RAG.

---

# 25. Issues MVP propuestas

## `[MVP-00] Freeze domain schemas and API contracts`
**Owner:** equipo completo  
**Bloquea:** todos los demás

Definir y commitear:

- `Transaction`
- `Incident`
- `EvidenceItem`
- `Diagnosis`
- `InjectionConfig`
- payloads de API

Definition of Done:
- todos los schemas viven en `backend/schemas.py` o módulo compartido;
- las cuatro tracks pueden trabajar sin inventar campos propios;
- ejemplos JSON documentados.

---

## `[MVP-01] Build one-year synthetic historical transaction generator`
**Track:** Data

Checklist:
- 3 merchants;
- 3 countries;
- 3 providers;
- 4 methods;
- banks definidos;
- decline codes;
- timestamps;
- amounts;
- seasonal approval behavior;
- reproducible random seed;
- Jan–Apr / May–Aug / Sep–Dec split.

DoD:
- genera dataset reproducible;
- respeta schemas;
- produce comportamiento estacional realista;
- exporta CSV/Parquet o DataFrame utilizable.

---

## `[MVP-02] Build live stream simulator and generic incident injector`
**Track:** Data

Checklist:
- simulated ticks;
- batch generation;
- configurable speed;
- injection by merchant/country/provider/method/bank/code;
- `target_approval_rate`;
- injector hidden from detector.

DoD:
- stream normal funciona;
- se puede inyectar un slice desconocido;
- detector sólo recibe transacciones;
- demo puede acelerar el tiempo.

---

## `[MVP-03] Build synthetic evaluation harness with 30 scenarios`
**Track:** Data / Testing

Checklist:
- implementar escenarios 1–30;
- expected outputs;
- deterministic seeds;
- runner;
- summary metrics.

DoD:
- puede ejecutarse con un comando;
- produce pass/fail por scenario;
- deja resultados listos para métricas del pitch.

---

## `[MVP-04] Build seasonal approval baseline`
**Track:** ML

Checklist:
- train Jan–Apr;
- validation May–Aug;
- test Sep–Dec;
- baseline merchant × country × hour_of_week;
- optional supported slices;
- baseline variance / uncertainty;
- min volume.

DoD:
- devuelve expected approval para cualquier ventana válida;
- no usa información futura;
- tiene tests básicos;
- decisión documentada en `DECISIONS.md`.

---

## `[MVP-05] Implement anomaly detector and monetary impact`
**Track:** ML

Checklist:
- rolling window;
- actual vs expected;
- min volume;
- absolute drop;
- z-score or chosen significance test;
- consecutive-window rule;
- loss estimate;
- incident object.

DoD:
- normal noise no alerta en casos básicos;
- degradación fuerte alerta;
- calcula `estimated_loss`;
- threshold configurable.

---

## `[MVP-06] Support simultaneous incidents and prioritization`
**Track:** ML / Incident engine

Checklist:
- identify multiple anomalous slices;
- avoid duplicate alerts for same underlying problem;
- separate unrelated incidents;
- severity ranking;
- priority using monetary impact + confidence.

DoD:
- scenarios 22–25 separated correctly;
- emits ordered incident list;
- no merge de incidentes claramente independientes.

---

## `[MVP-07] Implement deterministic root-cause drill-down engine`
**Track:** RCA

Checklist:
- analyze provider;
- method;
- issuing bank;
- decline code;
- relevant intersections;
- compare live vs baseline;
- rank candidate slices;
- compute explained-loss share;
- minimum evidence threshold.

DoD:
- returns structured evidence package;
- correct root cause on initial synthetic incidents;
- does not call OpenAI;
- supports generic unseen slices.

---

## `[MVP-08] Implement LLM diagnosis, explanation, recommendation and abstention`
**Track:** AI

Checklist:
- consume evidence package, not raw transaction dump;
- structured output;
- operations explanation;
- executive summary;
- recommendation only;
- `insufficient_evidence`;
- mock mode;
- real OpenAI mode;
- tool/use logging if relevant.

DoD:
- stable structured response;
- no unsupported claims;
- can abstain;
- API usage limited to incident diagnosis;
- prompt documented.

---

## `[MVP-09] Build merchant Control Tower dashboard`
**Track:** Frontend

Checklist:
- merchant selector/tabs;
- Rappi / Carrefour / Despegar isolated context;
- summary metrics;
- country monitoring;
- provider health;
- live approval charts;
- backend calls.

DoD:
- user can switch merchant;
- displayed data filtered by merchant;
- live metrics understandable without explanation;
- works with mock backend.

---

## `[MVP-10] Build incident cards + judge injection UI`
**Track:** Frontend

Checklist:
- critical alert card;
- country;
- failing slice;
- expected vs actual conversion;
- money lost;
- diagnosis;
- recommendation;
- injector controls;
- target approval rate;
- inject button;
- active incident state.

DoD:
- judge can configure/inject incident;
- no developer code change required;
- alert updates automatically;
- injection config never passed directly to detector.

---

## `[MVP-11] End-to-end alert integration`
**Track:** Integration

Checklist:
- stream → detector;
- detector → incident;
- incident → RCA;
- RCA → agent;
- agent → frontend;
- structured alert;
- errors;
- health endpoint;
- mock fallback.

DoD:
- one complete happy path works from UI;
- no manual intervention after injection;
- errors shown safely;
- known-good demo scenario documented.

---

## `[MVP-12] Trial-by-fire hardening and final evaluation`
**Track:** equipo completo

Checklist:
- normal noise;
- one incident;
- two incidents;
- narrow slice;
- insufficient evidence;
- random unseen injection;
- latency;
- restart/failure recovery;
- run evaluation harness;
- save metrics.

DoD:
- system passes agreed critical scenarios;
- final measured metrics saved;
- demo input ready;
- fallback mode ready;
- no blocking bug.

---

# 26. Post-MVP backlog

Sólo si el MVP está estable.

## `[POST-01] Remediation simulator`
Simular rerouting y estimar qué acción tendría mejor outcome.

## `[POST-02] External context awareness`
Buscar outages/noticias/eventos como enrichment secundario.

## `[POST-03] WhatsApp / Slack alerts`
Enviar la alerta.

## `[POST-04] Incident memory`
Reconocer incidentes repetidos.

## `[POST-05] Next.js frontend + Vercel`
Reemplazar Streamlit manteniendo FastAPI.

## `[POST-06] Supabase persistence / RLS`
Persistir incidents/users/history.

## `[POST-07] RAG for Account Managers`
Consultar historial/documentación.

---

# 27. Cronograma sugerido

Adaptar a la hora real disponible, pero mantener el orden.

## Primeros 20–30 min

- freeze schemas;
- crear issues;
- asignar responsables;
- crear `DECISIONS.md`;
- confirmar contratos.

## Primer bloque

4 tracks en paralelo:

```text
A → generator
B → baseline/detector
C → RCA/agent
D → dashboard
```

## Primer checkpoint

Objetivo:

```text
one injected incident
→ detected
→ diagnosed
→ displayed
```

aunque sea feo.

## Segundo bloque

- simultaneous incidents;
- insufficient evidence;
- trial injector;
- evaluation.

## Último bloque

- polish;
- metrics;
- README;
- architecture;
- decision log;
- backup demo;
- pitch.

No agregar features grandes cerca del freeze.

---

# 28. Demo story

La demo debe sentirse como una película, no como un tour por archivos.

Ejemplo:

> “Everything is healthy.”

Dashboard normal.

> “At 14:03, something changes.”

Se inyecta incidente.

```text
conversion drops
↓
system detects
↓
root cause drill-down
↓
alert appears
```

Luego:

> “The system isolates dLocal × PIX in Brazil, sees decline code 91 spike, estimates $5,820/hour in lost approvals, and recommends investigation/rerouting.”

Después:

> “Now a second unrelated incident occurs.”

Sistema separa y prioriza.

Finalmente:

> “Now the judge can inject any unseen combination.”

Trial by fire.

---

# 29. Principios que NO debemos romper

1. **Working demo > fancy architecture.**
2. **Evidence > LLM speculation.**
3. **One happy path first.**
4. **No automatic remediation in Challenge 2.**
5. **No OpenAI call per transaction.**
6. **No frontend rewrite before core works.**
7. **No Supabase/Vercel just for buzzwords.**
8. **Measure metrics; never invent them.**
9. **Always keep mock/fallback mode.**
10. **Every major decision goes to `DECISIONS.md`.**
11. **Every teammate must understand the whole architecture.**
12. **The system must survive an unseen judge injection.**

---

# 30. Definition of success for the MVP

El MVP está terminado cuando podemos hacer esto sin tocar código:

```text
1. select merchant
2. system runs normally
3. judge configures unknown incident
4. click INJECT
5. stream changes
6. detector notices anomaly
7. system estimates monetary impact
8. root-cause engine isolates affected slice
9. LLM/mock produces evidence-based explanation
10. system recommends action
11. dashboard updates
12. second incident can be injected and separated
13. ambiguous case can return insufficient evidence
```

Si eso funciona y lo podemos defender, tenemos un producto competitivo.
