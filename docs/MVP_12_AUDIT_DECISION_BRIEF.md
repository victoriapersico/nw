# NextWave Hackathon 2026 — MVP-12 Audit & Decision Brief

## Cómo usar este documento

Este documento resume el estado real del repositorio para **Challenge 2: The Control Tower** antes de comenzar la implementación de GitHub Issue **MVP-12 — Trial-by-fire hardening and final evaluation**.

Pegale este documento completo a ChatGPT y pedile que actúe como **Technical Product Manager + Lead Engineer de hackathon**.

La respuesta debe ayudar a decidir qué corregir, qué devolver a issues anteriores y qué aceptar como limitación del MVP. No debe asumir que una funcionalidad está terminada porque exista un archivo o porque los unit tests estén verdes.

## Pedido para ChatGPT

Analizá toda la evidencia de este documento y devolvé:

1. Un veredicto claro: `GO`, `GO WITH CONDITIONS` o `NO-GO` para comenzar MVP-12.
2. La estrategia mínima recomendada para llegar a una demo confiable.
3. Qué problemas deben corregirse dentro de MVP-12 y cuáles deben volver a MVP-03/04/05/06/07/08/09/10/11.
4. Qué alcance exacto debería prometer el judge injector.
5. Si conviene:
   - ampliar el detector para slices angostos; o
   - restringir/documentar los slices soportados para la demo.
6. Si conviene usar OpenAI real o MOCK MODE durante la demo.
7. Un orden de trabajo seguro, con gates verificables después de cada paso.
8. Una lista final de must-fix, should-fix y defer.
9. Los criterios exactos de salida para declarar MVP-12 terminado.
10. Un plan de fallback para la demo.

Priorizá, en este orden:

1. confiabilidad de la demo;
2. honestidad de las métricas y del diagnóstico;
3. menor riesgo técnico;
4. menor cantidad de cambios;
5. claridad del valor de negocio;
6. calidad visual.

No propongas nuevas features, una reescritura, frameworks adicionales ni cambios de arquitectura salvo que sean indispensables para cumplir la prueba del jurado.

---

# 1. Contexto del producto

Estamos construyendo una torre de control de pagos que debería ejecutar:

```text
transaction stream
→ seasonal baseline
→ anomaly detector
→ Incident
→ deterministic RCA
→ evidence
→ LLM narration/recommendation
→ merchant dashboard
```

El LLM no debe inventar el diagnóstico. Python produce la evidencia y el LLM solamente explica y recomienda.

El trial by fire exige que un juez pueda configurar un incidente no ensayado. `InjectionConfig` sólo puede llegar al simulador; detector, RCA y agente deben inferir el problema desde las transacciones.

## Restricciones del MVP

- FastAPI + Streamlit + Python.
- Mantener MOCK MODE.
- Sin LangChain, LangGraph, CrewAI, Redis, Docker, auth o base de datos nueva.
- Sin remediación automática.
- Sin features post-MVP.
- Evitar cambios de schemas compartidos.
- Evitar refactors no relacionados.
- Priorizar el happy path más pequeño que demuestre valor.

---

# 2. Veredicto preliminar del audit

## MOSTLY READY, WITH SPECIFIC BLOCKERS

El backend determinístico tiene un happy path real y recuperable. No es una maqueta completa.

Sin embargo, el producto todavía no está listo para que un juez lo opere libremente porque:

- seis escenarios obligatorios del harness fallan;
- el frontend mezcla incidentes reales con métricas hardcodeadas o artificiales;
- el comando documentado de Streamlit falla;
- no existe un reset real;
- `insufficient_evidence` puede mostrarse como una causa probable;
- el harness sobreestima la exactitud de RCA;
- algunos slices que la UI permite configurar nunca generan un `Incident`.

MVP-12 es realizable desde este estado, pero ya no es solamente “correr tests y pulir”. Algunos defectos deben volver a sus componentes propietarios.

---

# 3. Estado del repositorio

- Branch actual: `mvp-issue-12`.
- La branch apunta al mismo commit que `main`: `7b803e4`.
- Worktree limpio al finalizar el audit.
- No existen commits específicos de MVP-12 todavía.
- El historial local muestra los PRs de componentes integrados hasta el PR #25.
- No se pudo confirmar el estado open/closed de los issues en GitHub porque `gh` no está instalado y la página de issues no estaba disponible externamente.

---

# 4. Estado por MVP issue

| Issue | Estado | Evidencia |
|---|---|---|
| MVP-00 Contracts | PASS | Schemas Pydantic, validaciones, wrappers API y aislamiento del injector implementados. |
| MVP-01 Historical data | PASS | Dataset anual completo, válido y reproducible. |
| MVP-02 Simulator/injector | PASS standalone | Batches de cinco minutos, filtros genéricos, inyecciones simultáneas y expiración. |
| MVP-03 Evaluation harness | PARTIAL | Ejecuta 30 escenarios y genera reportes, pero seis casos fallan y las métricas de RCA son permisivas. |
| MVP-04 Baseline | PARTIAL | Implementación seasonal train-only correcta, pero un bucket ruidoso causa un falso positivo. |
| MVP-05 Detector/impact | PARTIAL | Detecta incidentes amplios; no detecta slices angostos y tiene un falso positivo normal. |
| MVP-06 Simultaneous/prioritization | PARTIAL | Existe el módulo de prioridad, pero no está conectado al runtime; escenario 25 falla. |
| MVP-07 RCA | PARTIAL | RCA determinístico real e integrado, pero demasiados casos terminan en abstención. |
| MVP-08 LLM/agent | PARTIAL | Narración Control Tower integrada y mock funcional; OpenAI real no tiene fallback seguro. |
| MVP-09 Dashboard | PARTIAL | Selector y consumo de incidentes reales; monitoring, trends y providers siguen siendo mocks. |
| MVP-10 Incident/injector UI | PARTIAL | Inyección amplia funciona; reset y presentación de abstención son incorrectos. |
| MVP-11 E2E integration | PARTIAL | Happy path backend completo; falta reset, prioridad real, live monitoring y startup confiable. |
| MVP-12 Hardening | PLACEHOLDER | Todavía no tiene implementación ni artefactos finales. |

---

# 5. Estado por componente

| Componente | Estado | Evaluación actual |
|---|---|---|
| Historical data | PASS | Completo, válido y reproducible. |
| Live simulator | PASS | Generación e inyección real funcionan. |
| Baseline | PARTIAL | No incorpora suficientemente la incertidumbre del baseline estimado. |
| Detector | PARTIAL | Recall 80%; false-positive rate 14.3%. |
| Simultaneous incidents | PARTIAL | Escenarios 22–24 pasan; 25 falla. |
| RCA | PARTIAL | Buen engine aislado; confirmación integrada insuficiente. |
| LLM/agent | PARTIAL | Mock funciona; camino real y fallback incompletos. |
| Evaluation harness | PARTIAL | Ejecuta de manera determinística, pero algunas métricas no representan el resultado real. |
| Runtime integration | PARTIAL | Happy path amplio funciona; no existe lifecycle/reset y se evita IncidentEngine. |
| Frontend | FAIL | Startup documentado falla y la telemetría live no es real. |
| Judge injector | PARTIAL | Funciona con degradaciones amplias; falla con intersecciones angostas. |
| Mock fallback | PASS | Happy path backend probado con `MOCK_MODE=true`. |
| README/startup | FAIL | README sigue describiendo el starter genérico y el comando de frontend falla. |
| Secrets/config | PARTIAL | No se encontraron secretos; existen variables de entorno inconsistentes. |

---

# 6. Dataset histórico verificado

Archivo actual:

```text
data/historical_transactions_2025_seed42.csv
```

Resultados de inspección:

```text
Rows: 550,909
Size: aproximadamente 61 MB
Train: 176,695
Validation: 183,823
Test: 190,391
```

Cobertura validada:

- Merchants: Rappi, Carrefour, Despegar.
- Countries: Mexico, Brazil, Colombia.
- Providers: Stripe, Adyen, dLocal.
- Methods: CARD, PIX, PSE, OXXO.
- 12 issuing banks.
- Decline codes: 05, 51, 54, 57, 61, 91, 96.
- Sin métodos inválidos por país.
- Sin bancos inválidos por país.
- Sin combinaciones status/decline code inválidas.
- Sin montos no positivos.
- Spot-check del primer bloque horario coincide exactamente con el generator actual usando seed 42.

Approval rate por split:

```text
train:      91.80%
validation: 91.58%
test:       91.40%
```

## Riesgo de alineación histórica/live

Sí están alineados:

- approval model contextual;
- volumen relativo por merchant/country/hora;
- pesos de provider;
- pesos de payment method;
- pesos de issuing bank.

No están completamente alineados:

- histórico usa perfiles de monto por merchant y país;
- live usa una única distribución lognormal genérica;
- histórico usa pesos de decline code según payment method;
- live elige decline codes naturales de manera uniforme.

Esto puede distorsionar impacto monetario, prioridad y evidencia de decline codes.

---

# 7. Resultado completo de pytest

Comando:

```bash
.venv/bin/python -m pytest -q
```

Resultado:

```text
71 passed, 1 warning in 3.19s
```

Warning:

- deprecación Starlette/httpx en `TestClient`.

Limitación importante de la suite:

- `/health` es el único endpoint directamente probado;
- no hay tests E2E de `/injections`;
- no hay tests E2E de `/monitor/tick`;
- no hay tests de `/merchants/{merchant}/incidents`;
- no hay tests de reset;
- no hay tests del recorrido real de Streamlit;
- no hay prueba de fallback de OpenAI durante una inyección.

Por lo tanto, `71 passed` no significa que la demo esté lista.

---

# 8. Resultado actual del evaluation harness

El harness se ejecutó dos veces. Métricas y resultados fueron idénticos, por lo que es determinístico.

```text
Required scenarios evaluated: 29
Passed: 23/29
Skipped: scenario 29
Detection recall: 80.0%
False-positive rate: 14.3%
Root-cause accuracy reportada: 75.0%
Multi-incident separation accuracy: 75.0%
Abstention accuracy: 100.0%
Mean detection latency: 10 minutos
Estimated-loss error: unavailable
```

## Escenarios que fallan

| # | Escenario | Resultado real |
|---:|---|---|
| 17 | dLocal × Itaú × Brazil | No se genera Incident. |
| 18 | Stripe × PSE × Colombia | No se genera Incident. |
| 19 | Adyen × BBVA × Mexico | No se genera Incident. |
| 25 | Critical + mild incident | Se detecta sólo uno de los dos incidentes. |
| 28 | Natural time-of-day drop | Falso positivo en la cuarta ventana. |
| 30 | Random unseen injected slice | No se genera Incident. |

## Problema con root-cause accuracy

El harness reúne todos los `EvidenceItem` observados y considera acertada una causa aunque el diagnóstico tenga:

```text
diagnosis_status = insufficient_evidence
```

Ejemplos que el harness marca PASS aunque RCA se abstiene:

- scenario 8;
- scenario 12;
- scenario 13;
- scenario 14;
- scenario 15;
- una de las causas en scenario 22;
- una de las causas en scenario 24.

Si se exige que las causas esperadas pertenezcan a un diagnóstico `confirmed`, pasan solamente:

```text
7, 9, 10, 11, 16, 20, 21, 23
```

Resultado estricto:

```text
8/20 positive root-cause scenarios = 40%
```

Por lo tanto, el 75% actual no es seguro para usar en el pitch.

## Otras limitaciones del harness

- No ejecuta narración LLM.
- No ejecuta FastAPI.
- No ejecuta Streamlit.
- No prueba restart/reset del runtime de demo.
- No prueba fallback si OpenAI falla.
- No calcula estimated-loss error.
- No valida realmente el orden entregado por `IncidentEngine`.

---

# 9. Happy path backend que sí funciona hoy

Se verificó manualmente este recorrido con `MOCK_MODE=true`:

1. FastAPI carga el CSV histórico.
2. Construye `SeasonalBaseline` y `RootCauseAnalyzer`.
3. `POST /injections` entrega `InjectionConfig` sólo al simulator.
4. `LiveControlTower.inject()` avanza inmediatamente dos ventanas.
5. Simulator genera `TransactionBatch` sin metadata de inyección.
6. Detector evalúa merchant × country y aplica persistencia de dos ventanas.
7. Si dispara, crea `Incident`.
8. Runtime entrega las últimas dos ventanas a RCA.
9. RCA produce `Diagnosis` y `EvidenceItem`.
10. Mock/OpenAI produce explicación y recomendación sin cambiar los hechos.
11. El incidente diagnosticado queda en memoria.
12. `GET /merchants/{merchant}/incidents` devuelve el resultado filtrado.

Caso manual validado:

```text
merchant: Rappi
country: Brazil
provider: Stripe
target approval rate: 20%
decline code: 91
```

Resultado:

- Incident real.
- Diagnosis confirmed.
- Provider Stripe detectado.
- Decline code 91 detectado.
- Otro merchant no recibió el incidente.

## Aislamiento trial-by-fire

Esta parte está bien implementada:

- `TransactionBatch` no tiene campo de injection.
- Pydantic prohíbe campos adicionales.
- Detector sólo recibe `DetectionRequest(batch=...)`.
- RCA no importa `InjectionConfig`.
- El prompt del agent contiene Diagnosis/Evidence, no transacciones ni configuración.

---

# 10. Problema de slices angostos

El detector agrupa exclusivamente por:

```text
merchant × country
```

Una intersección angosta puede colapsar internamente sin reducir al menos ocho puntos porcentuales el approval rate del parent.

Ejemplos medidos:

## Scenario 17 — dLocal × Itaú × Brazil

```text
Parent volume: 206
Injected slice volume: 15–18
Parent drops: 7.72pp y 3.35pp
Threshold: 8pp durante dos ventanas
Resultado: no Incident
```

## Scenario 18 — Stripe × PSE × Colombia

```text
Parent volume: 123
Injected slice volume: 10–16
Parent drops: 10.67pp y 5.80pp
Resultado: no persistencia, no Incident
```

## Scenario 19 — Adyen × BBVA × Mexico

```text
Parent volume: 75
Injected slice volume: 8–12
Parent drops: 9.11pp y 2.44pp
Resultado: no persistencia, no Incident
```

## Scenario 30 — Random unseen slice

Configuración elegida por seed:

```text
Despegar × Brazil × dLocal × CARD × Itaú
```

```text
Parent volume: 83
Injected slice volume: 4–5 por ventana
Parent drops: 1.07pp y 3.48pp
Resultado: no Incident
```

Además, el slice sólo suma nueve transacciones en dos ventanas, por debajo del soporte mínimo habitual de RCA.

## Decisión pendiente

Hay que decidir explícitamente entre:

### Opción A — Ampliar detector

Detectar degradaciones genéricas en slices soportados y luego emitir un Incident merchant-country para que RCA redescubra la causa.

Riesgos:

- más complejidad;
- mayor riesgo de falsos positivos;
- posible ambigüedad en las métricas del Incident;
- puede requerir coordinación de contratos.

### Opción B — Limitar el contrato de la demo

Declarar como trial-by-fire soportado:

- merchant-wide;
- provider;
- payment method;
- issuing bank;
- decline code;
- sólo intersecciones con volumen suficiente.

La UI y scenario 30 no deberían ofrecer o exigir combinaciones que estadísticamente no pueden detectarse.

Ventajas:

- menor riesgo;
- no cambia arquitectura;
- alinea promesa y capacidad real.

Riesgo:

- puede ser percibido como una limitación si el challenge exige cualquier combinación arbitraria.

---

# 11. Falso positivo de tráfico normal

Scenario 28, `Natural time-of-day drop`, genera un Incident falso en la cuarta ventana.

Detalle del caso que dispara:

```text
merchant: Rappi
country: Mexico
time: 03:00 UTC
baseline expected approval: 96.49%
window 3 actual: 88.24% — drop 8.26pp
window 4 actual: 87.58% — drop 8.91pp
```

La generación live está operando normalmente. El problema es que el bucket histórico tiene poco soporte y un approval rate empírico demasiado alto.

El z-score actual incorpora:

```text
baseline Bernoulli variance / live volume
```

pero trata el approval rate estimado del baseline como si no tuviera incertidumbre propia.

Posibles soluciones a evaluar:

- mayor soporte mínimo del baseline;
- smoothing/shrinkage hacia un parent estable;
- incluir incertidumbre de la estimación histórica;
- recalibrar thresholds usando validation;
- nunca hardcodear una excepción para scenario 28.

Owner recomendado: MVP-04/MVP-05, no una excepción ad hoc en MVP-12.

---

# 12. Simultaneous incidents y prioridad

Resultados:

- Scenario 22: PASS, dos incidents.
- Scenario 23: PASS, dos incidents.
- Scenario 24: PASS, dos incidents.
- Scenario 25: FAIL, sólo aparece el incidente crítico.

El incidente mild OXXO está demasiado diluido a nivel parent para alcanzar el detector actual.

Además:

- `IncidentEngine` existe;
- tiene tests de deduplicación y prioridad;
- ordena por severity → estimated loss → anomaly score → drop;
- pero no es llamado por `EvaluationRuntime`;
- tampoco es llamado por `LiveControlTower`;
- el dashboard ordena por estimated loss y anomaly score, ignorando severity.

Por lo tanto, la priorización implementada existe como módulo aislado, no como comportamiento end-to-end.

Dos fallas independientes dentro del mismo merchant-country tampoco pueden separarse como dos incidents simultáneos porque el detector produce un único agregado parent.

---

# 13. RCA y abstención

Fortalezas:

- RCA es determinístico.
- Analiza provider, method, bank, decline code e intersecciones.
- Usa historia Jan–Apr.
- Usa hasta dos ventanas live.
- Calcula sample size, z-score, explained-loss share y confidence.
- Tiene unit tests fuertes.
- No depende del injection config.

Problemas integrados:

- varios casos simples encuentran el valor esperado en evidence pero terminan en `insufficient_evidence`;
- RCA sólo puede ejecutarse si detector primero emite Incident;
- narrow slices no llegan a RCA;
- la UI muestra evidence candidata como causa aunque RCA se haya abstenido.

La abstención backend es correcta; el uso que hacen harness y UI de esa abstención es incorrecto.

---

# 14. LLM/agent

Existen dos caminos distintos:

## Camino Control Tower

`backend/ai/diagnosis.py`

- recibe `Diagnosis` determinístico;
- sólo genera `explanation` y `recommended_action`;
- preserva evidence, confidence, dimensions y status;
- usa structured output;
- mock mode funciona;
- insufficient evidence nunca llama OpenAI.

## Camino legacy

`backend/agent.py`, `backend/tools.py` y `/analyze`

- siguen siendo el starter genérico de REC-001/REC-002/REC-003;
- no forman parte del Control Tower real;
- README todavía documenta este camino.

## Riesgo de OpenAI real

Si OpenAI falla durante una inyección:

1. simulator ya avanzó;
2. detector ya actualizó su contador;
3. Incident puede haber sido emitido;
4. narration lanza una excepción;
5. el endpoint no la captura;
6. el incidente no se almacena;
7. al reintentar, el contador puede estar por encima de la ventana exacta de emisión.

Esto puede romper el happy path y dejar estado inconsistente.

Decisión necesaria:

- usar MOCK MODE como demo principal; o
- implementar fallback automático y state-safe antes de usar OpenAI real.

---

# 15. Frontend y judge flow

## Startup blocker

El comando documentado:

```bash
streamlit run frontend/app.py
```

abre una página de error:

```text
ModuleNotFoundError: No module named 'backend'
```

El audit pudo continuar usando temporalmente:

```bash
PYTHONPATH=. streamlit run frontend/app.py
```

El README no documenta esto ni corrige el import path.

## Qué consume datos reales

- `POST /injections`.
- `GET /merchants/{merchant}/incidents`.
- Incident.
- Diagnosis.
- Evidence.
- Expected/actual conversion del país afectado.
- Affected volume y estimated loss del incidente.

## Qué sigue siendo placeholder o artificial

- estado normal de cada país;
- country totals;
- provider health;
- trends;
- total transactions;
- overall approval;
- sample incidents usados cuando backend no responde;
- movimiento “live” de KPIs.

El frontend nunca llama:

```text
POST /monitor/tick
```

Cada dos segundos hace:

```text
approval = weighted approval + hard-coded jitter
transactions = initial total + tick × 37
```

El chart se vuelve a dibujar, pero con los mismos valores.

Prueba observada:

```text
KPI before: 77.8%, 41,269 transactions
KPI after:  78.0%, 41,343 transactions
Chart before: Mexico 67.4 / Brazil 71.2 / Colombia 90.6
Chart after:  exactamente igual
```

Los logs de FastAPI confirmaron que durante esos refreshes no hubo `/monitor/tick`.

## Contradicción visible antes de inyectar

El backend devolvía cero incidents, pero la UI mostraba simultáneamente:

```text
No active incidents
Brazil Critical
Brazil approval 71.2% vs expected 93.1%
```

Esto proviene del payload hardcodeado de Rappi.

## Insufficient evidence mal presentado

La inyección default del popover produjo:

```text
merchant: Rappi
country: Mexico
provider: Adyen
target: 30%
diagnosis_status: insufficient_evidence
confidence: 64%
```

El backend explicó correctamente que no podía aislar una causa.

La UI, sin embargo, mostró:

```text
Probable root cause
Provider: Adyen
Method: CARD
Intersection: Adyen × CARD
Issuing bank: BBVA México
...
```

Esto convierte evidence candidata en una causa presentada visualmente y viola el requerimiento de no fabricar diagnósticos.

## Reset falso

- No existe endpoint backend de reset.
- `Clear local notice` sólo borra un valor de `st.session_state`.
- El reset de Judge Lab también sólo borra estado local.
- No cancela injections.
- No limpia detector counters.
- No elimina recent batches.
- No resuelve incidents.
- Los incidents quedan `active` incluso después de que expire la inyección y vuelva tráfico normal.

---

# 16. Money impact

Implementación actual:

```text
expected_approved_amount
= total_attempted_amount × expected_approval_rate

estimated_loss
= max(0, expected_approved_amount - actual_approved_amount)

estimated_loss_per_hour
= estimated_loss × 60 / window_minutes
```

Fortalezas:

- no puede devolver pérdida negativa;
- schema exige valores no negativos;
- unit test verifica el cálculo básico;
- los incidents actuales no contienen valores imposibles.

Limitaciones:

- el reporte no incluye ground truth loss;
- `estimated_loss_error` es `None`;
- la distribución live de montos no coincide con la histórica;
- la prioridad de Despegar/Rappi/Carrefour puede verse distorsionada.

Estado de acceptance F: funcional, pero todavía no evaluado de forma completa.

---

# 17. Restart y stale state

## EvaluationRuntime

`reset(scenario)` crea simulator y detector nuevos y limpia recent batches. El harness empieza cada escenario en limpio.

## LiveControlTower

No expone reset.

Estado actual persistido en memoria:

- simulator;
- active injections;
- detector consecutive counters;
- recent batches;
- diagnosed incidents.

`Incident.status` nunca cambia a `resolved`.

Prueba manual:

- se inyectó un incidente;
- se dejó expirar la inyección;
- se avanzó una ventana normal;
- el incidente siguió activo;
- `POST /monitor/reset` devolvió 404.

Acceptance G: FAIL para la demo live.

---

# 18. Mock/fallback y configuración

## Correcto

- Sin API key, settings activa mock automáticamente.
- `MOCK_MODE=true` fuerza el mock.
- Narración mock devuelve el mismo schema.
- Happy path broad fue probado end-to-end en mock.
- `.env` está ignorado.
- No se encontraron API keys o tokens trackeados.

## Incorrecto o incompleto

- `.env.example` define `BACKEND_URL`.
- Frontend usa `CONTROL_TOWER_API_URL`.
- `.env.example` define `BACKEND_REQUEST_TIMEOUT_SECONDS`.
- Frontend hardcodea timeouts de 10 y 30 segundos.
- Si backend no responde, frontend usa silenciosamente payloads hardcodeados que parecen reales.
- Si OpenAI falla con real mode, no existe fallback automático seguro.

---

# 19. README y decision log

README todavía dice:

- “generic practice starter”;
- que el challenge no fue revelado;
- que el flujo principal es `/analyze`;
- que el usuario debe usar REC-001/REC-002/REC-003;
- que existen solamente los archivos del starter;
- que todavía hay que cambiar schemas, tools, agent y frontend después del reveal.

No documenta:

- Control Tower;
- historical dataset;
- evaluation command;
- judge injector;
- monitor tick;
- merchant incidents;
- known-good injection;
- reset/fallback real;
- `PYTHONPATH` necesario para arrancar la UI actual.

`DECISIONS.md` también tiene problemas:

- IDs DEC-024/026/027/028/029/030 duplicados;
- dice que el Judge Lab contiene reset controls que no resetean backend;
- DEC-028 prohíbe fabricar métricas live, pero el frontend las fabrica;
- algunas decisiones describen una integración más completa que el runtime actual.

---

# 20. Clasificación completa de problemas

## BLOCKERS

### 1. Frontend no arranca con el comando documentado

Owner: MVP-09/MVP-11.

### 2. Monitoring live mezcla real y fake

Owner: MVP-09/MVP-11.

### 3. Insufficient evidence se muestra como probable root cause

Owner: MVP-10/MVP-11.

### 4. Narrow y unseen slices no detectan

Owner: MVP-05; scope del escenario en MVP-03.

### 5. Natural time-of-day produce falso positivo

Owner: MVP-04/MVP-05.

### 6. Simultaneous critical + mild pierde un incidente

Owner: MVP-05/MVP-06.

### 7. IncidentEngine no está integrado

Owner: MVP-06/MVP-11.

### 8. Reset/lifecycle inexistente

Owner: MVP-02/MVP-10/MVP-11.

### 9. Métricas de evaluación no son seguras para el pitch

Owner: MVP-03/MVP-12.

## IMPORTANT

### 1. Amount y decline-code distributions no están alineadas entre history y live

Owner: MVP-01/MVP-02.

### 2. OpenAI real puede romper el estado de una inyección

Owner: MVP-08/MVP-11.

### 3. Harness no prueba LLM, API, UI, restart ni fallback

Owner: MVP-03/MVP-12.

### 4. Variables de entorno inconsistentes

Owner: MVP-09/MVP-11.

### 5. README y docs están desactualizados

Owner: MVP-11/MVP-12.

### 6. No hay integration tests del judge journey

Owner: MVP-12.

### 7. Decision IDs duplicados y decisiones contradictorias

Owner: whole team/MVP-12 documentation.

### 8. Logos dependen de assets externos

Owner: MVP-09; riesgo cosmético/de red.

## NON-BLOCKING

- Scenario 29/incident memory es opcional y post-MVP.
- No auth es aceptable.
- No database es aceptable.
- No automatic remediation es correcto.
- No external context es correcto.
- No Slack/WhatsApp es correcto.
- Warnings de Streamlit y Starlette no rompen la demo actual.
- `/analyze` legacy es confuso, pero no bloquea si no se usa.

---

# 21. Acceptance targets A–J

| Target | Estado actual | Evidencia |
|---|---|---|
| A. Normal traffic | PARTIAL/FAIL | Scenarios 1–6 pasan, pero scenario 28 produce falso positivo. |
| B. One clear incident | PARTIAL | Broad supported incident funciona; varios casos terminan en insufficient evidence. |
| C. Two simultaneous incidents | PARTIAL | 22–24 pasan; 25 falla; prioridad real no integrada. |
| D. Ambiguous case | Backend PASS / UI FAIL | Scenario 27 se abstiene; UI puede mostrar evidence como causa. |
| E. Unseen judge-like incident | FAIL | Scenario 30 no produce Incident. |
| F. Money impact | PARTIAL | Fórmula segura; falta ground truth y error metric. |
| G. Restart/reset | FAIL live | Harness resetea; demo live no. |
| H. Mock/fallback | PASS mock / PARTIAL fallback | Mock funciona; fallback automático de OpenAI no. |
| I. Injection isolation | PASS | Config no llega a detector, RCA o agent. |
| J. UI/demo flow | FAIL | Injection broad puede aparecer, pero monitoring no es real, reset falla y startup documentado falla. |

---

# 22. Plan mínimo propuesto por el audit

Este plan todavía requiere decisión del equipo. No se implementó nada.

## Orden 1 — Hacer confiable el gate

- Cambiar harness para que una causa sólo cuente como correcta si Diagnosis es `confirmed`.
- Asociar causas esperadas con incidents concretos.
- Verificar el orden retornado de prioridad.
- Separar métricas de detection, RCA y abstention.
- Agregar ground truth loss si se va a publicar esa métrica.

Owner original: MVP-03.

MVP-12: usa el gate corregido y guarda resultados finales.

## Orden 2 — Resolver alcance de slices

Decidir oficialmente:

- detector genérico de slices soportados; o
- judge injector restringido a slices detectables.

No ajustar tests para que pasen sin documentar esta decisión.

Owners: MVP-05 + MVP-03 + whole team.

## Orden 3 — Corregir false positive

- Reproducir scenario 28.
- Corregir baseline uncertainty o smoothing.
- Validar contra todos los normal cases y nuevas seeds.

Owners: MVP-04/MVP-05.

## Orden 4 — Simultaneous y prioridad

- Hacer que el mild incident de scenario 25 sea estadísticamente soportado o mejorar detection.
- Conectar `IncidentEngine` en evaluation y live runtime.
- Hacer que dashboard respete el orden real.

Owners: MVP-05/MVP-06/MVP-11.

## Orden 5 — Reset real

Reset debe limpiar:

- simulator;
- active injections;
- detector counters;
- recent batches;
- incident store.

Agregar endpoint, UI action y tests de rerun.

Owners: MVP-02/MVP-10/MVP-11.

## Orden 6 — UI con fuente real

- Arreglar startup/import path.
- Consumir backend ticks/snapshots.
- Eliminar jitter y counters fabricados.
- Mostrar datos normales reales.
- Mostrar provider health real o quitarlo de la promesa.
- Renderizar `insufficient_evidence` explícitamente.
- No mostrar candidate evidence como probable cause.
- Evitar fallback silencioso a datos que parecen reales.

Owners: MVP-09/MVP-10/MVP-11.

## Orden 7 — LLM seguro

- Elegir mock como demo principal o agregar fallback automático.
- No permitir que narration failure pierda un Incident.
- Probar schema y error handling.

Owners: MVP-08/MVP-11.

## Orden 8 — Trial-by-fire final

- Full pytest.
- Full evaluation repetida.
- Nuevas seeds no presentes en tests esperados.
- Broad single incident.
- Simultaneous incidents.
- Ambiguous case.
- Money sanity.
- Reset y rerun.
- Mock fallback.
- UI launch desde cero.
- Ensayo de demo sin intervención de developer.
- Guardar metrics finales para pitch.

Owner: MVP-12.

---

# 23. Preguntas estratégicas que el equipo debe decidir

## Pregunta 1

¿El judge injector promete cualquier combinación arbitraria de provider × method × bank, incluso con 4–10 transacciones por ventana?

Si la respuesta es sí, el detector actual necesita ampliar su unidad de detección.

Si la respuesta es no, UI, README y evaluation deben definir claramente “supported slice”.

## Pregunta 2

¿La demo debe usar OpenAI real?

Opción más segura actual:

```text
MOCK_MODE=true
```

El valor AI sigue siendo defendible porque:

- evidence y RCA son reales;
- mock produce el mismo contract;
- el LLM real sólo redacta;
- se puede mostrar un run real separado después de implementar fallback.

## Pregunta 3

¿Se acepta mostrar únicamente incidents reales y mantener monitoring estático?

Actualmente no debería aceptarse como “live”, porque el UI dice que actualiza cada dos segundos y fabrica valores.

Opciones honestas:

- integrar ticks reales; o
- quitar la animación y etiquetar un snapshot como tal.

## Pregunta 4

¿Scenario 25 debe representar un mild incident detectable por el detector parent actual?

El target OXXO actual puede ser demasiado leve para producir el drop parent mínimo. Se debe ajustar el escenario o ampliar detection, no hardcodear una excepción.

## Pregunta 5

¿Se puede declarar RCA correcto cuando Diagnosis se abstiene pero el valor esperado aparece entre candidatos?

Recomendación del audit: no. Eso contradice `insufficient_evidence` y puede inducir a error en la UI y en el pitch.

---

# 24. Criterio de salida recomendado para MVP-12

MVP-12 no debería cerrarse hasta cumplir todo lo siguiente:

- [ ] El comando documentado inicia backend y frontend desde un clone limpio.
- [ ] Full pytest pasa.
- [ ] Todos los escenarios críticos acordados pasan con un harness semánticamente correcto.
- [ ] Cero falsos positivos en escenarios normales acordados y nuevas seeds de smoke test.
- [ ] Un broad unseen incident produce Incident + Diagnosis correcta.
- [ ] El alcance de narrow slices está implementado o explícitamente limitado.
- [ ] Dos incidentes soportados se detectan y ordenan correctamente.
- [ ] Ambiguous evidence se muestra como `insufficient_evidence` también en la UI.
- [ ] Money impact nunca es negativo y su fórmula se verifica E2E.
- [ ] Reset limpia todo el estado y permite repetir la misma demo.
- [ ] MOCK MODE funciona desde startup hasta UI.
- [ ] Si se usa OpenAI real, un fallo cae de forma segura a mock o preserva el Incident.
- [ ] InjectionConfig no aparece en detector, RCA, agent inputs o evaluation observations.
- [ ] Charts y KPIs llamados “live” provienen del backend.
- [ ] La inyección del juez no requiere intervención manual posterior.
- [ ] README incluye known-good input, startup, fallback y reset.
- [ ] Las métricas finales quedan guardadas para el pitch.

---

# 25. Resultado esperado de ChatGPT

Respondé usando esta estructura:

## Veredicto

`GO`, `GO WITH CONDITIONS` o `NO-GO`, con una explicación corta.

## Estrategia elegida

Elegí una sola estrategia principal. No presentes tres alternativas equivalentes sin recomendar una.

## Decisiones

Para cada pregunta estratégica, indicá la decisión recomendada y por qué.

## Must-fix antes de demo

Lista ordenada y acotada.

## Should-fix si queda tiempo

Lista ordenada.

## Defer/post-MVP

Lista explícita.

## Issue ownership

Tabla con problema, issue owner y motivo.

## Orden de implementación

Pasos secuenciales con un gate verificable al final de cada uno.

## Definition of Done de MVP-12

Checklist final medible.

## Demo plan

Happy path principal, input conocido, unseen input, fallback y reset.

## Riesgo residual aceptado

Qué limitaciones seguirán existiendo y cómo comunicarlas honestamente al jurado.

