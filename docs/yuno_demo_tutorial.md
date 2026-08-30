# Tutorial de demo: NextWave x Yuno

Este tutorial permite demostrar la integración de sandbox de NextWave con Yuno sin
enviar pagos ni emails reales. La consola presenta escenarios ya preparados y la API
mantiene el detalle técnico disponible para quien quiera revisarlo.

## Qué demuestra el producto

Hay dos flujos deliberadamente separados:

```text
Webhook Yuno firmado pero incorrecto
  -> error de integración
  -> alerta para Yuno Operations
  -> email sandbox

Transacciones válidas con caída de aprobación
  -> Control Tower detecta anomalía
  -> RCA y recomendación
  -> alerta para el merchant afectado
```

Una caída de aprobación de un merchant no se presenta como fallo de Yuno sin evidencia
independiente. Una firma inválida tampoco genera email: el sistema no confía en su
origen.

## Antes de la demo

Abrí PowerShell en la carpeta del repositorio:

```powershell
cd C:\Users\gonza\Desktop\nw
.\.venv\Scripts\Activate.ps1
```

Si PowerShell bloquea la activación del entorno virtual, ejecutá una vez:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

Después repetí la activación.

## Terminal 1: iniciar la API

Ejecutá:

```powershell
python -m uvicorn backend.main:app --reload
```

No cierres esta terminal. Cuando veas una línea parecida a la siguiente, la API está
lista:

```text
Uvicorn running on http://127.0.0.1:8000
```

## Terminal 2: abrir la demo guiada

Abrí otra terminal, repetí el `cd` y la activación del entorno, y ejecutá:

```powershell
python -m scripts.yuno_demo
```

Vas a ver un menú. Durante la presentación solo se ingresan números de opciones; no
hace falta editar código ni escribir JSON.

## Guion recomendado: 4 minutos

### 1. Contexto — 20 segundos

Decí:

> NextWave se integra con el flujo de pagos de Yuno. Distinguimos problemas técnicos
> de integración de los incidentes de performance que afectan a un merchant. Eso evita
> alertar a la persona equivocada y acelera la respuesta operativa.

### 2. Evento correcto — opción `1` — 30 segundos

Elegí `1. Send a valid payment webhook`.

Resultado esperado:

```text
Signature: verified
Result: accepted and normalized for payment monitoring.
Notification: no Yuno system alert is needed.
```

Decí:

> El evento es firmado, se valida y se normaliza. Desde aquí puede alimentar el
> monitoreo de aprobaciones del merchant.

### 3. Error confiable de integración — opción `3` — 50 segundos

Elegí `3. Send an invalid transaction amount`.

Resultado esperado:

```text
Signature: verified
Result: safely rejected before it enters payment monitoring.
Error code: invalid_amount
Notification: Yuno Operations email created in the sandbox outbox.
```

Decí:

> La firma es válida, por eso confiamos en el origen. Pero el importe es inválido:
> detenemos el evento antes de contaminar los datos de monitoreo, devolvemos un código
> estructurado y generamos una alerta para Operations de Yuno.

### 4. Mostrar notificación — opción `9` — 30 segundos

Elegí `9. View sandbox notification emails`.

Mostrá el destinatario sandbox, el asunto y el campo afectado.

Decí:

> En producción este mismo mensaje se entrega con el proveedor de email o webhook
> operativo aprobado por Yuno. En la demo usamos un outbox local para no requerir
> credenciales ni enviar información de pagos a terceros.

### 5. Idempotencia — repetí opción `3` — 30 segundos

Elegí nuevamente `3`.

Resultado esperado:

```text
Duplicate protection: this retry did not create another notification.
```

Decí:

> Los proveedores reintentan webhooks. Nuestro idempotency key evita correos duplicados
> y ruido para el equipo operativo.

### 6. Seguridad — opción `7` — 30 segundos

Elegí `7. Send an invalid signature (security check)`.

Resultado esperado:

```text
HTTP status: 401
Signature: rejected
Notification: not sent, because the origin is not trusted.
```

Decí:

> Si no podemos verificar el origen, no procesamos el payload ni generamos una alerta
> que podría ser causada por un atacante.

### 7. Cierre — 20 segundos

Decí:

> Una vez que los eventos válidos ingresan, Control Tower analiza las transacciones,
> detecta caídas reales de aprobación y explica evidencia y recomendaciones para el
> merchant. La integración técnica y el monitoreo de performance son flujos distintos,
> conectados pero seguros.

## Escenarios adicionales

| Opción | Caso | Código esperado |
| --- | --- | --- |
| `2` | Código de decline con formato inválido | `transaction_validation_failed` |
| `4` | Cuenta Yuno y merchant no coinciden | `merchant_mapping_failed` |
| `5` | Método de pago incompatible con país | `invalid_payment_method_country` |
| `6` | Esquema/version de webhook no soportado | `unsupported_webhook_schema` |
| `8` | Ver alertas técnicas acumuladas | No envía un evento nuevo |

## Para profundizar técnicamente

Abrí en el navegador:

```text
http://127.0.0.1:8000/docs
```

Ahí Yuno puede revisar los contratos de la API sandbox y probar los endpoints. No es
necesario mostrar esta pantalla en el relato principal; sirve para preguntas técnicas.

## Problemas comunes

### `Could not reach the local API`

La API no está iniciada. Volvé a la primera terminal y confirmá que Uvicorn siga activo.

### El caso aparece como duplicado desde el primer intento

La API conserva el estado en memoria mientras está encendida. Reiniciá Uvicorn con
`Ctrl+C` y volvé a iniciarlo para comenzar una demo limpia.

### `No module named pytest`

No afecta la demo. Para ejecutar tests, activá primero el entorno virtual con
`.\.venv\Scripts\Activate.ps1`.

## Límite consciente del demo

El email es simulado e inspeccionable por API; no se manda a una casilla real. Antes de
producción se reemplaza por el canal aprobado por Yuno, con secretos de entorno,
persistencia, reintentos, métricas de entrega y un endpoint HTTPS público.
