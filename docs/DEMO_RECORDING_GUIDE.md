# Control Tower demo recording guide

Guía única para grabar y presentar **NextWave Hackathon 2026 — Challenge 2: The Control Tower**.

El objetivo es producir una demo principal confiable con `MOCK_MODE=true`, una prueba separada de la integración real con OpenAI usando `MOCK_MODE=false` y, si sobra tiempo, un clip corto del Yuno API Manager local.

## Entregables de video recomendados

1. `01_control_tower_mock.mp4` — demo principal completa, 4–5 minutos.
2. `02_control_tower_openai.mp4` — prueba enfocada del assistant real, 2–3 minutos.
3. `03_yuno_api_manager_bonus.mp4` — clip opcional, 60–90 segundos.

La entrega principal debe funcionar sin el tercer video. El Challenge 2 se gana mostrando detección, diagnóstico, evidencia, costo, recomendación y trial-by-fire; Yuno API Manager es una superficie adicional.

## Límites que deben explicarse honestamente

- El flujo de pagos, detector, RCA, impacto y simulaciones usan datos sintéticos locales.
- `MOCK_MODE=true` reemplaza solamente la narración del modelo por texto determinístico.
- `MOCK_MODE=false` habilita OpenAI para el incident assistant.
- El LLM recibe evidencia estructurada y no recibe transacciones crudas ni `InjectionConfig`.
- Las recomendaciones requieren aprobación humana.
- **Simulate application** modifica solamente el simulador local.
- Ningún proveedor de pagos es contactado y no existe remediación automática.
- Telegram debe permanecer deshabilitado durante las grabaciones principales.
- El Yuno API Manager es un sandbox local; no contacta una API real de Yuno ni envía emails.

## Preflight técnico obligatorio

Antes de grabar la toma definitiva:

- [ ] `main` está sincronizada con `origin/main`.
- [ ] El worktree no contiene cambios de código inesperados.
- [ ] La suite completa termina sin fallas.
- [ ] La evaluación final no muestra regresiones.
- [ ] `.env` está ignorado por Git.
- [ ] No hay API keys ni tokens versionados.
- [ ] `TELEGRAM_NOTIFICATIONS_ENABLED=false`.
- [ ] FastAPI responde en `/health`.
- [ ] Streamlit se conecta al backend.
- [ ] **Reset demo** deja el dashboard limpio.
- [ ] El escenario conocido produce un incidente después de dos ventanas persistentes.
- [ ] Se cerraron Slack, WhatsApp, correo y notificaciones del sistema.

### Puertos seguros

Usar los puertos por defecto:

- FastAPI: `8000`
- Control Tower: `8501`
- Yuno API Manager opcional: `8502`

Para las grabaciones oficiales, mantener estos puertos reduce variables. El
launcher de Windows también admite puertos alternativos: define
`CONTROL_TOWER_API_URL` para sus procesos y ambos dashboards preservan esa
variable por encima del valor de `.env`.

## Preparación de pantalla y audio

- Resolución: 1920×1080.
- Framerate: 30 FPS.
- Zoom del browser: 90% como punto de partida.
- Usar una ventana privada/incógnita para obtener una sesión Streamlit limpia.
- Ocultar barra de favoritos, extensiones y datos personales.
- Activar “No molestar”.
- No grabar terminales, `.env`, logs ni credenciales.
- Usar cursor lento y deliberado; evitar movimientos circulares.
- Después de cada click, dejar entre uno y dos segundos para que el espectador vea el resultado.
- No hacer scroll mientras se está explicando una métrica.
- Grabar cada toma completa aunque después se edite.

## Inicio local en macOS/Linux

Abrir dos terminales desde la raíz del repositorio.

### Terminal 1 — backend en Mock Mode

```bash
source .venv/bin/activate
MOCK_MODE=true TELEGRAM_NOTIFICATIONS_ENABLED=false \
  uvicorn backend.main:app --port 8000
```

### Terminal 1 — backend con OpenAI real

Detener primero el backend anterior con `Ctrl+C` y luego ejecutar:

```bash
source .venv/bin/activate
MOCK_MODE=false TELEGRAM_NOTIFICATIONS_ENABLED=false \
  uvicorn backend.main:app --port 8000
```

`OPENAI_API_KEY` debe existir localmente en `.env`. Nunca mostrarla ni copiarla al video.

### Terminal 2 — Control Tower

```bash
source .venv/bin/activate
streamlit run frontend/app.py --server.port 8501
```

Abrir <http://127.0.0.1:8501>.

## Inicio local en Windows PowerShell

Desde la raíz, con `.venv` ya creado e instalado:

```powershell
.\start_demo.ps1
```

El launcher espera a que FastAPI esté sano y abre Control Tower en `8501` y el
Yuno API Manager local en `8502`. Los logs quedan en el directorio temporal
`nextwave-control-tower`; no se versionan. Para la toma oficial, usar los puertos
por defecto y mantener Telegram deshabilitado en `.env`.

### Verificación de salud

Fuera de la grabación:

```bash
curl http://127.0.0.1:8000/health
```

Respuesta esperada:

```json
{"status":"ok"}
```

### Reset limpio antes de abrir el browser

```bash
curl -X POST http://127.0.0.1:8000/monitor/reset
```

Después del reset, abrir una nueva ventana privada. Así también se limpia el historial local del chat de Streamlit.

## Grabación 1 — demo principal con `MOCK_MODE=true`

Duración objetivo: **4–5 minutos**.

Esta es la grabación más confiable y debe servir como backup de la demo live.

### Configuración exacta del incidente

- Merchant visible: `Rappi`
- Country: `Brazil`
- Anomaly scope: `Provider`
- Provider: `Stripe`
- Target approval rate: `20%`
- Duration: `6` simulated windows

### 0:00–0:25 — problema y estado normal

Mostrar:

- `Control Tower`.
- `LIVE MONITORING`.
- Merchant `Rappi`.
- `Executive summary`.
- `No active incidents`.

Voiceover sugerido en inglés:

> Payment conversion failures cost money every minute, but traditional alerts either create noise or arrive too late. Control Tower monitors payment traffic continuously and isolates the root cause with evidence before an operator has to cross multiple dashboards manually.

Esperar una o dos actualizaciones de cinco segundos.

> The system is processing real synthetic transaction windows. No alert is fired while traffic remains within the expected seasonal range.

### 0:25–0:55 — métricas normales

Señalar lentamente:

- `Approval rate · live`.
- Expected approval y gap.
- `Transactions · live`.
- Estimated loss en cero.
- Active incidents en cero.
- Country status en `Stable`.

Voiceover:

> These values come from the live simulator and statistical baseline. The detector requires enough volume, a material conversion drop and persistence across two windows, which prevents reacting to isolated noise.

### 0:55–1:25 — trial-by-fire desde Judge Lab

Abrir **Judge Lab** y seleccionar:

1. Country: `Brazil`.
2. Anomaly scope: `Provider`.
3. Merchant: `Rappi`.
4. Provider: `Stripe`.
5. Target approval rate: `20`.
6. Duration: `6`.
7. Click **Inject incident**.

Voiceover:

> The Judge Lab controls only the simulator. The detector never receives this configuration; it sees only the resulting transactions and must infer the incident independently.

Si aparece la advertencia de que la inyección todavía no llegó al threshold, no tocar nada. Esperar aproximadamente 10 segundos. El detector necesita dos ventanas persistentes.

### 1:25–2:05 — detección

Cuando aparezca `ACTIVE INCIDENT`, mostrar:

- Brazil.
- Expected versus actual approval.
- Drop en percentage points.
- Estimated loss.
- Confidence.
- Active incidents: `1`.

Voiceover:

> After two persistent windows, the system confirms a material incident. It estimates the affected volume and excess loss while keeping the incident scoped to the correct merchant and country.

Hacer scroll lento hacia:

- `Approval rate — live`.
- `Country status`.
- Brazil marcado como `Critical` o `Attention`.

### 2:05–2:45 — root cause y evidencia

Llegar a **Root cause, recommended recovery & simulation** y mostrar primero **Why is approval falling?**

Señalar:

- provider;
- Stripe;
- baseline approval;
- live approval;
- sample size;
- evidence confidence.

Voiceover:

> Detection and diagnosis are separate stages. The RCA compares payment dimensions and confirms Stripe as the strongest supported cause. If the evidence were ambiguous, the system would return insufficient evidence instead of inventing a diagnosis.

### 2:45–3:20 — recomendación

Mostrar **Recommended action** y señalar:

- porcentaje de traffic shift;
- target provider;
- estimated recovery per hour;
- expected approval;
- confidence;
- `Human approval required`;
- aclaración de que todo queda en el simulador.

Voiceover:

> Control Tower recommends a bounded recovery option, but it cannot execute production routing. The recommendation remains advisory and requires a human decision.

### 3:20–3:55 — assistant determinístico

En **Ask about this incident**, escribir exactamente:

```text
What is the strongest supported root cause?
```

Esperar la respuesta. Mostrar:

- el texto de respuesta;
- `Deterministic Mock Mode response`;
- el expander `Evidence used · 2 facts`.

Voiceover:

> In Mock Mode, the narration is deterministic and network-independent. The simulator, detector, economic impact, RCA and recommendation are still the real application pipeline. Only the final wording is generated locally.

### 3:55–4:30 — aprobación humana y dry-run

Si existe una recomendación elegible:

1. Click **Approve recommendation**.
2. Esperar que aparezca la confirmación de aprobación humana.
3. Click **Simulate application**.
4. Mostrar métricas before/expected/observed y el audit trail.
5. Click **Revert simulated change**.

Voiceover:

> This is not automatic remediation. A human explicitly approves a local counterfactual simulation. No provider is contacted and no live routing changes.

Después del rollback:

> The simulated action is reversible and auditable.

Si la recomendación no es elegible, no forzar el workflow. Mostrar la abstención y explicar que la seguridad tiene prioridad.

### 4:30–4:55 — notificaciones y cierre

Opcionalmente abrir **Notifications** y mostrar la alerta local. No activar Telegram.

> Operators also receive a local, merchant-scoped notification that can be acknowledged without leaving the Control Tower.

Abrir **Judge Lab**, hacer click en **Reset demo** y cerrar mostrando `No active incidents`.

> The complete flow is detect, diagnose, explain and recommend—with evidence, human control and a clean reset for the next unrehearsed judge input.

## Escenario adicional — dos incidentes simultáneos

El challenge pide demostrar separación y priorización. Puede grabarse como segmento adicional o mostrarse en una toma de ensayo.

1. Resetear el demo.
2. Inyectar `Rappi · Brazil · Provider · Stripe · 30%`.
3. Sin resetear, cambiar la configuración e inyectar `Carrefour · Mexico · Issuing bank · BBVA México · 30%`.
4. Esperar dos ventanas persistentes.
5. Mostrar que existen dos incidentes distintos.
6. Cambiar el merchant superior entre `Rappi` y `Carrefour` para mostrar evidencia independiente.
7. Explicar que Incident Engine los mantiene separados y los ordena por impacto y severidad.

Voiceover:

> Two unrelated failures are active at the same time. Control Tower keeps the provider incident for Rappi in Brazil separate from the issuing-bank incident for Carrefour in Mexico, then prioritizes them by business impact instead of merging their evidence.

## Grabación 2 — OpenAI real con `MOCK_MODE=false`

Duración objetivo: **2–3 minutos**.

El objetivo de esta toma es probar la integración real con OpenAI, no repetir todo el workflow de remediación.

### Preflight de OpenAI sin revelar la key

Con el backend apagado:

```bash
source .venv/bin/activate
MOCK_MODE=false .venv/bin/python -c \
  "from backend.config import settings; print('key configured:', bool(settings.openai_api_key), 'mock mode:', settings.mock_mode)"
```

Resultado esperado:

```text
key configured: True mock mode: False
```

Esta salida no revela la API key.

Luego iniciar FastAPI con `MOCK_MODE=false`, iniciar Streamlit, ejecutar `/monitor/reset` y abrir una sesión privada nueva.

### 0:00–0:20 — límite del modelo

Mostrar el dashboard limpio.

> This recording uses the real OpenAI path. The model receives only a bounded incident snapshot with application-owned evidence and has no tools or write access.

### 0:20–0:55 — inyección y detección

Repetir el escenario conocido:

- Rappi;
- Brazil;
- Provider;
- Stripe;
- 20%;
- 6 windows.

Mientras se esperan los dos ticks:

> The anomaly is still detected and diagnosed deterministically. OpenAI is used only after the application has established the incident facts.

### 0:55–1:25 — evidencia previa al LLM

Mostrar brevemente:

- approval gap;
- root cause;
- estimated loss;
- recommendation.

> These facts already exist before the model is called. The LLM cannot change the root cause, impact or recommendation status.

### 1:25–2:20 — respuesta real estructurada

En **Ask about this incident**, escribir exactamente:

```text
Based only on the incident evidence, summarize the root cause, estimated hourly impact, and safest recommended next step.
```

No tocar el input ni hacer otro click mientras aparece `Checking the incident evidence`. La UI puede esperar hasta 70 segundos.

La toma demuestra OpenAI real solamente si aparece:

```text
OpenAI · structured evidence-only response
```

Abrir `Evidence used · N facts`.

Voiceover:

> The answer is generated by OpenAI through a structured response. Every factual claim must reference one of the incident facts returned by the application. The model cannot approve, simulate or modify routing.

### Si aparece fallback

Si la etiqueta dice:

```text
Deterministic fallback after the LLM was unavailable
```

la app sobrevivió correctamente, pero esa toma no demuestra OpenAI real. Revisar fuera del video:

- API key configurada;
- conectividad;
- modelo disponible;
- créditos/cuota;
- logs del backend.

No mostrar la key ni los logs en la grabación final.

## Grabación 3 opcional — Yuno API Manager

Duración objetivo: **60–90 segundos**.

Iniciar la superficie opcional:

```bash
source .venv/bin/activate
streamlit run frontend/yuno_demo.py --server.port 8502
```

Abrir <http://127.0.0.1:8502>.

Secuencia:

1. Mostrar `Yuno API Manager` y `API connected`.
2. Click **Load healthy sandbox baseline**.
3. Mostrar estado `Healthy`, requests, success rate y P95 latency.
4. Click **Invalid amount**.
5. Mostrar `Integration issue isolated`.
6. Mostrar el alert y email preview local.
7. Click **Invalid signature**.
8. Mostrar `Security check completed` y explicar que el tráfico no confiable no crea ruido operacional.
9. Cerrar mostrando `Demo boundary`.

Voiceover:

> The Yuno API Manager is a separate local sandbox for integration operations. Trusted malformed traffic is isolated and produces a local operations record, while an invalid signature is rejected without creating alert noise. Nothing is sent to Yuno or an email provider.

No presentar esta superficie como integración productiva con Yuno.

## Telegram

Telegram es opcional y no forma parte de la grabación principal.

Para todas las tomas oficiales:

```dotenv
TELEGRAM_NOTIFICATIONS_ENABLED=false
```

La UI de **Notifications** funciona como inbox local aun con Telegram apagado. Esto permite mostrar alertas sin depender de internet ni de un bot externo.

Si se prepara una prueba separada de Telegram, nunca mostrar `.env`, el token ni
el chat ID. La integración requiere:

- `TELEGRAM_NOTIFICATIONS_ENABLED=true`;
- `TELEGRAM_BOT_TOKEN` y `TELEGRAM_CHAT_ID` configurados localmente;
- opcionalmente, un `TELEGRAM_DASHBOARD_URL` público HTTPS para agregar el botón
  **Open Control Tower**. Una URL local no genera ese botón.

El mensaje es solamente informativo: resume incidente, evidencia, impacto y
recomendación. Telegram no aprueba, rechaza, simula ni revierte cambios. La
entrega es best-effort; si Telegram o la red fallan, el monitoreo y el inbox local
siguen funcionando.

## Troubleshooting rápido

### La UI dice “Monitoring is reconnecting”

1. Verificar que FastAPI esté corriendo en `8000`.
2. Ejecutar `curl http://127.0.0.1:8000/health`.
3. Confirmar `CONTROL_TOWER_API_URL=http://127.0.0.1:8000`.
4. Usar puertos por defecto.
5. Refrescar la sesión privada.

### El incidente no aparece

1. Confirmar Rappi + Brazil + Provider + Stripe + 20%.
2. Confirmar duración mínima de 6 ventanas.
3. Esperar al menos dos actualizaciones de cinco segundos.
4. Mantener el merchant superior en Rappi.
5. Resetear y repetir desde una sesión limpia.

### El assistant falla inmediatamente

- Confirmar que FastAPI sigue corriendo.
- Confirmar que la UI apunta a `8000`.
- En OpenAI real, esperar sin interrumpir hasta 70 segundos.
- Revisar los logs fuera del video.

### La respuesta dice Mock cuando se esperaba OpenAI

- Reiniciar FastAPI con `MOCK_MODE=false`.
- Verificar la configuración con el preflight que no revela la key.
- Crear un incidente nuevo después del restart.

### La respuesta dice fallback

- La degradación segura funcionó.
- La toma no demuestra una respuesta real de OpenAI.
- Revisar conectividad, modelo, cuota y backend antes de regrabar.

### La recomendación no permite aprobar

- No forzar el flujo.
- Mostrar el motivo de abstención.
- Resetear y usar el escenario conocido.
- La ausencia de una acción insegura es comportamiento esperado.

## Checklist de aceptación de cada archivo

### `01_control_tower_mock.mp4`

- [ ] Se ve el estado sano antes de inyectar.
- [ ] Se ve la configuración de Judge Lab.
- [ ] Se explica que `InjectionConfig` llega solamente al simulador.
- [ ] Se ve la detección después de persistencia.
- [ ] Se ve approval gap, evidencia, costo y confianza.
- [ ] Se ve la recomendación.
- [ ] Se puede mostrar y reconocer la alerta del inbox local.
- [ ] El assistant muestra `Deterministic Mock Mode response`.
- [ ] El dry-run se presenta como local y humano-gated.
- [ ] Se revierte o completa el dry-run.
- [ ] Se ejecuta Reset demo al final.
- [ ] No aparecen secretos, terminales ni notificaciones privadas.

### `02_control_tower_openai.mp4`

- [ ] Se ve un incidente confirmado.
- [ ] Se explica que los hechos existen antes de llamar al modelo.
- [ ] La pregunta está limitada a la evidencia.
- [ ] Aparece `OpenAI · structured evidence-only response`.
- [ ] Se abre `Evidence used`.
- [ ] No aparece la API key.
- [ ] No se confunde fallback con una respuesta real.

### `03_yuno_api_manager_bonus.mp4`

- [ ] Se aclara que es sandbox local.
- [ ] Se muestra baseline sano.
- [ ] Se muestra un error confiable aislado.
- [ ] Se muestra invalid signature sin ruido operacional.
- [ ] No se afirma que exista integración productiva con Yuno.

## Referencias del repositorio

- [README y operación completa](../README.md)
- [Submission package](../SUBMISSION.md)
- [Decision log](../DECISIONS.md)
- [Judge Lab scope y limitaciones](judge_lab_scope_limitations.md)
- [Diseño de routing simulado con aprobación humana](post_03_human_approved_simulated_routing.md)
