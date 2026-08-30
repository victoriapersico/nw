# Tutorial — Yuno API Manager

Yuno API Manager es la vista para el equipo técnico/operativo de Yuno. No es el
dashboard del merchant: monitorea si la integración de API con NextWave está sana.

```text
Yuno API Manager                     Control Tower
-----------------                    -------------
salud de webhooks                    caída de approval
firma y validación                   impacto económico
latencia e idempotencia              RCA y recomendación
alerta a Yuno Operations             alerta al merchant
```

## 1. Abrir la aplicación

Primero confirmá que estás en la branch que contiene Yuno:

```powershell
cd C:\Users\gonza\Desktop\nw
git switch post-mvp-yuno-demo
.\.venv\Scripts\Activate.ps1
```

En una terminal iniciá la API:

```powershell
python -m uvicorn backend.main:app --reload
```

Esperá que el arranque termine. El backend carga el histórico local antes de aceptar
requests.

En otra terminal abrí Yuno API Manager:

```powershell
cd C:\Users\gonza\Desktop\nw
.\.venv\Scripts\Activate.ps1
python -m streamlit run frontend/yuno_demo.py
```

Abrí la URL indicada por Streamlit, normalmente:

```text
http://localhost:8501
```

Para comenzar una presentación desde cero, reiniciá FastAPI. La telemetría sandbox vive
en memoria y se limpia cuando se reinicia ese proceso.

## 2. Qué ves al entrar

Al principio el estado debería ser `Idle`. Significa que todavía no entró tráfico sandbox.

Para no empezar la demo con el panel vacío, presioná `Load healthy sandbox baseline`.
Carga 12 requests aceptados y 2 reintentos idempotentes, todos sintéticos y locales. El
estado pasa a `Healthy`; después podés usar `Invalid amount` para mostrar cómo cambia
ante una falla técnica real del flujo sandbox.

Las métricas son:

| Métrica | Significado |
| --- | --- |
| Requests | Cantidad de webhooks que recibió la API en esta sesión. |
| Success rate | Porcentaje de requests aceptados y normalizados. |
| P95 latency | Latencia alta representativa: 95% de los requests tardó ese tiempo o menos. |
| Trusted API errors | Requests con firma válida pero datos inválidos. |

Estados:

| Estado | Significado |
| --- | --- |
| Idle | No hay requests todavía. |
| Healthy | Los requests observados fueron aceptados. |
| Attention | Hay errores técnicos firmados que requieren revisión. |
| Degraded | El error rate técnico superó 10% en esta sesión sandbox. |

## 3. Recorrido de demo recomendado

### Paso A — Tráfico saludable

Presioná `Valid payment`.

Esperá ver:

```text
Webhook accepted
Signature: verified
Result: payment normalized
```

Luego, en `API health`:

- Requests aumenta.
- Success rate aumenta.
- Estado pasa a `Healthy`.

Qué decir:

> Yuno puede observar en tiempo real si los eventos llegan firmados, son aceptados y se
> normalizan al contrato de NextWave.

### Paso B — Error de integración confiable

Presioná `Invalid amount`.

Esperá ver:

```text
Signature: verified
Result: safely rejected
Error code: invalid_amount
```

Luego señalá:

- baja el success rate;
- aumenta `Trusted API errors`;
- estado cambia a `Attention` o `Degraded`;
- aparece una entrada en `API alerts`;
- aparece una entrada en `Notification emails`;
- aparece la request en `Request telemetry`.

Qué decir:

> La firma era válida, por eso sabemos que el evento viene de un origen confiable. Pero
> el monto era incorrecto; detenemos el dato antes de que afecte métricas del merchant y
> avisamos a Yuno Operations.

### Paso C — Idempotencia

Presioná nuevamente `Invalid amount`.

Esperá ver:

```text
Duplicate protection: this retry did not create another notification.
```

Qué decir:

> Si Yuno reintenta el mismo webhook, lo registramos como duplicate y no mandamos otro
> email ni creamos otra alerta. Evitamos ruido operativo.

### Paso D — Seguridad

Presioná `Invalid signature`.

Esperá:

```text
HTTP status: 401
Signature: rejected
```

Qué decir:

> Una firma inválida no se procesa. No confiamos en el payload ni generamos una alerta
> basada en tráfico potencialmente malicioso.

## 4. Otros escenarios disponibles

| Botón | Código que se espera |
| --- | --- |
| Malformed transaction | `transaction_validation_failed` |
| Invalid amount | `invalid_amount` |
| Merchant mismatch | `merchant_mapping_failed` |
| Invalid payment method | `invalid_payment_method_country` |
| Unsupported schema | `unsupported_webhook_schema` |
| Invalid signature | `401` y `invalid_signature` |

## 5. Qué hace cada pestaña

### API alerts

Muestra errores técnicos de requests firmados: código de error, campo afectado, evento y
resumen. Es la bandeja de incidentes de integración de Yuno.

### Notification emails

Muestra el email sandbox renderizado. No se manda una casilla real durante el hackathon;
en producción se conectaría al proveedor o canal operativo aprobado por Yuno.

### Request telemetry

Muestra los últimos requests de API y su resultado:

- `ACCEPTED`: evento válido.
- `REJECTED`: evento firmado pero inválido.
- `DUPLICATE`: reintento idempotente.
- `UNAUTHORIZED`: firma inválida.

### Activity log

Es el registro auditado de movimientos de la sesión sandbox. Cada entrada conserva hora,
`source_event_id`, cuenta (cuando el origen fue confiable), resultado, latencia y código
de error. El botón `Download audit log (JSON)` permite descargarlo para revisión o para
mostrarlo en una demo.

### API contract

Muestra la URL de Swagger:

```text
http://127.0.0.1:8000/docs
```

Usala solo si una persona técnica quiere inspeccionar contratos y endpoints.

## 6. Límite consciente del sandbox

Los datos y webhooks son sintéticos, reproducibles y locales. El API Manager demuestra
la lógica de verificación, validación, observabilidad, alertas e idempotencia. Antes de
producción faltaría conectar el formato real aprobado por Yuno, credenciales, HTTPS
público, persistencia, delivery real de emails/webhooks y métricas de infraestructura.
