# MVP-00: contrato y pipeline compartido

Este documento explica el acuerdo técnico que habilita a las cuatro integrantes a
trabajar en paralelo. MVP-00 no detecta incidentes, no genera el año histórico y
no muestra una UI final: define el lenguaje común que usan esas piezas.

La fuente de verdad es `backend.schemas`. Ningún equipo debe crear una variante de
estos nombres, valores o validaciones en su propio módulo.

## El pipeline completo

```text
                    ┌─────────────────────┐
                    │ Judge / testing UI  │
                    └──────────┬──────────┘
                               │ CreateInjectionRequest
                               ▼
                    ┌─────────────────────┐
                    │ Live simulator      │
                    │ - normal generator  │
                    │ - future injection  │
                    └──────────┬──────────┘
                               │ TransactionBatch
                               │ (transactions only)
                               ▼
                    ┌─────────────────────┐
                    │ Detector            │
                    │ - baseline compare  │
                    │ - creates Incident  │
                    └──────────┬──────────┘
                               │ Incident
                               ▼
                    ┌─────────────────────┐
                    │ RCA / evidence      │
                    │ - creates Evidence  │
                    │ - creates Diagnosis │
                    └──────────┬──────────┘
                               │ Diagnosis
                               ▼
                    ┌─────────────────────┐
                    │ Agent + dashboard   │
                    │ - explain/recommend │
                    └─────────────────────┘
```

La regla de aislamiento más importante es esta:

```text
InjectionConfig ──X──> Detector
```

El injector cambia sólo transacciones futuras. El detector recibe únicamente una
ventana de transacciones y debe inferir cualquier problema desde esos datos.

## Vocabulario congelado

| Concepto | Valores permitidos |
|---|---|
| Merchant | `Rappi`, `Carrefour`, `Despegar` |
| Country | `Mexico`, `Brazil`, `Colombia` |
| Provider | `Stripe`, `Adyen`, `dLocal` |
| Payment method | `CARD` en todos; `PIX` sólo Brazil; `PSE` sólo Colombia; `OXXO` sólo Mexico |
| Transaction status | `approved`, `declined` |
| Decline code | `05`, `51`, `54`, `57`, `61`, `91`, `96` |

Los bancos emisores también están congelados por país. Se consultan mediante
`COUNTRY_ISSUING_BANKS` en `backend.schemas`, nunca mediante una lista duplicada.

## Contratos y responsables

| Contrato | Produce | Consume | Para qué sirve |
|---|---|---|---|
| `Transaction` | Generador histórico y simulador live | Baseline, detector, RCA | Un intento de pago válido. |
| `TransactionBatch` | Simulador live | Detector | Una ventana simulada —normalmente cinco minutos— con transacciones. |
| `InjectionConfig` | UI de judge / harness | Simulador live | Indica qué slice futuro degradar. No sale del simulador. |
| `Incident` | Detector | RCA, dashboard | Resume una degradación detectada para merchant y país. |
| `EvidenceItem` | RCA | Diagnosis, agent | Compara una dimensión/slice contra su baseline. |
| `Diagnosis` | RCA, con redacción opcional del agent | Dashboard | Causa probable, evidencia, confianza y recomendación. |

Los wrappers de API acordados son:

- `CreateInjectionRequest` → `CreateInjectionResponse`
- `DetectionRequest` → `DetectionResponse`
- `DiagnosisResponse`

## Reglas que valida `Transaction`

Cada transacción se construye y valida con `Transaction.model_validate(...)`.
Eso impide que el dataset o stream produzcan combinaciones imposibles.

- Un `approved` tiene obligatoriamente `decline_code = null`.
- Un `declined` tiene obligatoriamente un decline code válido.
- El método debe ser válido para el país.
- El banco debe pertenecer al país.
- El importe es mayor que cero.
- El timestamp debe traer zona horaria.
- No se admiten campos inesperados (`extra="forbid"`).

Ejemplo válido:

```json
{
  "transaction_id": "txn-2026-01-15-000001",
  "merchant": "Rappi",
  "provider": "dLocal",
  "payment_method": "PIX",
  "country": "Brazil",
  "issuing_bank": "Itaú",
  "decline_code": null,
  "status": "approved",
  "amount": 42.5,
  "timestamp": "2026-01-15T20:05:00+00:00"
}
```

## Cómo trabaja cada integrante sin bloquear a las demás

### Data / Simulation

Implementa el histórico y el stream. Ambos producen `Transaction`; el stream
empaqueta sus resultados en `TransactionBatch`. Para inyectar, acepta
`InjectionConfig` y altera solamente las próximas transacciones que coincidan con
los filtros. Puede asignar el `decline_code` indicado a los rechazos que cause.

### Baseline / Detector

Entrena con las transacciones históricas y recibe `DetectionRequest`, que contiene
un `TransactionBatch`. Devuelve `DetectionResponse` con cero o más `Incident`.
No importa ni conoce `InjectionConfig`.

### RCA / Agent

Parte de un `Incident`, calcula comparaciones por provider, método, banco, decline
code e intersecciones, y las expresa como `EvidenceItem`. Produce un `Diagnosis`.
El agent puede volver la explicación entendible y recomendar una acción, pero no
inventa evidencia ni recalcula la estadística.

### API / Dashboard / QA

La API serializa los modelos Pydantic; la UI muestra datos filtrados por merchant.
QA y el harness reutilizan los mismos schemas para crear fixtures y comprobar que
los resultados tengan forma válida.

## Límites del MVP-00

MVP-00 no implementa todavía endpoints nuevos, el baseline, la detección, el RCA,
la memoria de incidentes ni el generador. Su objetivo es evitar que esas piezas se
acoplen mediante supuestos implícitos. Si una necesidad nueva requiere modificar un
campo o agregar un valor, primero se acuerda y se cambia aquí, en el contrato
compartido.

## Antes de empezar una issue

1. Importar el modelo y los catálogos desde `backend.schemas`.
2. No usar strings o enums alternativos para ninguna dimensión del dominio.
3. Validar los datos en el borde de cada módulo.
4. Mantener la configuración de inyección fuera de detector, RCA y agent.
5. Añadir una prueba o fixture que use los contratos reales.
