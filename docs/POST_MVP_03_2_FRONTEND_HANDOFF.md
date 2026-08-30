# POST-MVP 03.2 — Frontend del workflow de routing simulado

## Objetivo

Agregar al dashboard de cliente una interfaz clara para que una persona de
Merchant Operations pueda revisar una recomendación de routing, aprobarla o
rechazarla y, si fue aprobada, ejecutar **únicamente una simulación local** del
cambio.

El frontend debe mostrar todo el ciclo de vida de la recomendación, sus métricas
y su auditoría sin dar a entender que se modificó tráfico real.

> Dependencia: el backend de POST-MVP 03.1 ya expone los contratos y endpoints
> necesarios. Esta issue es de frontend e integración; no hay que reimplementar
> la lógica de negocio en Streamlit.

## Estado actual de `main`

`main` ya contiene una integración visual de base en
`_render_routing_workflow()` y un cliente HTTP en
`frontend/remediation_client.py`. Por eso, si se trabaja desde el `main` actual,
esta tarea no debe crear un segundo workflow en paralelo: hay que revisar,
consolidar y completar el existente contra los criterios de este documento.

También existe un `render_remediation_panel()` anterior con el flujo de POST-01.
No se debe reactivar ni copiar: usa `/remediation/executions` y duplica llamadas
HTTP dentro de la vista. Al finalizar, debería quedar un único camino visual para
POST-MVP 03.2, apoyado en `frontend/remediation_client.py`.

## Valor para la demo

El flujo debe permitir contar esta historia de punta a punta:

```text
incidente detectado
→ recomendación basada en evidencia
→ revisión humana
→ aprobación explícita
→ aplicación simulada
→ métricas observadas
→ rollback o cierre manual
→ auditoría completa
```

## Alcance

Implementar o completar el panel de remediación dentro de la vista del cliente.

La persona usuaria debe poder:

- entender qué cambio se recomienda y por qué;
- ver proveedor destino, porcentaje de tráfico, recuperación estimada,
  aprobación esperada y confianza;
- aprobar o rechazar la recomendación;
- revocar una aprobación antes de activar la simulación;
- iniciar la aplicación simulada;
- ver las métricas `before`, `expected` y `observed`;
- revertir el cambio simulado o completar la revisión;
- consultar el historial de eventos de auditoría;
- entender en todo momento que no se contactó a ningún proveedor y no se cambió
  routing real.

## Fuera de alcance

- Routing real o integración con proveedores de pago.
- Credenciales, API keys o secretos de proveedores.
- Aprobación automática por un agente.
- Cambios en detector, RCA, recomendaciones o políticas.
- Persistencia propia del frontend.
- Rehacer el dashboard completo o cambiar el diseño general.
- Usar `POST /remediation/executions`: es un endpoint de compatibilidad de
  POST-01. El workflow de esta issue usa `/remediation/changes`.

## Archivos principales

- `frontend/pages/0_Client.py`: render del panel y acciones de la persona
  operadora.
- `frontend/remediation_client.py`: cliente HTTP y manejo común de errores.
- Tests de frontend nuevos o existentes, sólo si hacen falta para cubrir lógica
  extraída y determinista.

Evitar cambios en `backend/` salvo que se descubra un contrato realmente roto.
En ese caso, documentar el problema antes de modificarlo.

## Fuente de datos

La recomendación llega dentro del incidente mostrado por el dashboard como
`routing_recommendation`.

Campos que necesita la presentación:

- `recommendation_id`;
- `merchant`;
- `status`;
- `target_provider`;
- `traffic_cap`;
- `expected_recovery_per_hour`;
- `confidence`;
- `rationale`;
- `rollback_reference`;
- `abstention_reason` cuando no hay recomendación.

No inventar métricas ni mostrar datos hardcodeados como si fueran una respuesta
real. Si el backend no está disponible, mostrar un error explícito y conservar
la última pantalla estable sólo si está claramente marcada como desactualizada.

## Endpoints disponibles

Usar `CONTROL_TOWER_API_URL`; el valor local por defecto es
`http://127.0.0.1:8000`.

| Acción | Método y path | Resultado esperado |
|---|---|---|
| Consultar estado | `GET /remediation/workflows/{recommendation_id}` | Estado actual del workflow |
| Aprobar o rechazar | `POST /remediation/approvals` | Decisión humana vinculada a la recomendación |
| Revocar aprobación | `POST /remediation/approvals/{decision_id}/revoke` | Aprobación revocada antes de activar |
| Aplicar simulación | `POST /remediation/changes` | Cambio local con estado `simulated_active` |
| Consultar simulación | `GET /remediation/changes/{change_id}` | Métricas y ventanas observadas |
| Revertir simulación | `POST /remediation/changes/{change_id}/rollback` | Estado `rolled_back` |
| Completar revisión | `POST /remediation/changes/{change_id}/complete` | Estado `completed` |
| Ver auditoría | `GET /remediation/audit?recommendation_id=...` | Eventos del workflow |

Los payloads deben construirse en `frontend/remediation_client.py`. Reutilizar
los helpers existentes si ya están disponibles; evitar llamadas `requests`
duplicadas dentro de la vista.

## Estados que debe renderizar la UI

### `pending_approval`

Mostrar:

- resumen de la recomendación;
- aviso visible de que requiere aprobación humana;
- botón primario **Approve recommendation**;
- botón secundario **Reject**.

### `approved`

Mostrar:

- confirmación de aprobación;
- botón primario **Simulate application**;
- botón secundario **Revoke approval**;
- aclaración de que la acción es local y simulada.

### `rejected`

Mostrar estado final y el motivo devuelto por `transition_reason`. No mostrar
acciones de aplicación.

### `expired`

Informar que la aprobación venció antes de la activación. No permitir aplicar
la recomendación vencida.

### `revoked`

Informar que la aprobación fue revocada. No mostrar acciones de aplicación.

### `simulated_active`

Consultar el cambio por `change_id` y mostrar:

- approval rate antes del cambio;
- approval rate esperado;
- approval rate observado en la última ventana;
- recuperación estimada por hora;
- error rate observado, si existe;
- proveedor destino y porcentaje de tráfico simulado;
- botón **Revert simulated change**;
- botón **Complete review**.

### `rolled_back`

Mostrar que la simulación fue revertida y el `rollback_reason`. No presentarlo
como rollback de producción.

### `completed`

Mostrar que la revisión fue completada y aclarar que ningún proveedor fue
contactado.

## Auditoría

Debajo del estado principal, agregar un expander con los eventos obtenidos desde
`GET /remediation/audit`.

Cada evento debe mostrar, como mínimo:

- tipo de evento;
- actor;
- detalle;
- fecha/hora, si está disponible.

La auditoría del backend es la fuente de verdad. `st.session_state` puede ayudar
con el estado visual, pero no debe reemplazar la consulta del workflow después
de cada acción.

## Reglas de UX y Streamlit

- Mantener la estética actual del dashboard; no hacer un rediseño general.
- Usar componentes nativos de Streamlit siempre que sea posible.
- Agrupar la recomendación y su workflow en un contenedor con borde.
- Usar hasta tres métricas en una fila para `before`, `expected` y `observed`.
- Usar claves estables en botones basadas en `recommendation_id` o `change_id`.
- Después de una acción exitosa, llamar `st.rerun()` para volver a consultar el
  estado real.
- Deshabilitar o no renderizar acciones inválidas para el estado actual.
- Mostrar errores del backend de forma visible y accionable, sin romper toda la
  página.
- Evitar doble submit mientras una operación está en curso.
- Usar `width="stretch"`; no agregar `use_container_width`, que está deprecado.
- Usar sentence casing y textos que distingan **recommendation**, **approval** y
  **simulation** de una ejecución real.

## Happy path esperado

1. Levantar backend y frontend.
2. Generar un incidente desde Judge Lab.
3. Abrir el incidente en el dashboard del merchant correcto.
4. Ver una recomendación en estado `pending_approval`.
5. Aprobarla.
6. Ver estado `approved`.
7. Presionar **Simulate application**.
8. Ver estado `simulated_active` y las métricas before/expected/observed.
9. Completar la revisión o revertir la simulación.
10. Confirmar el estado final y los eventos en el audit log.

También se deben verificar los caminos de rechazo y revocación.

## Cómo probarlo localmente

Terminal 1:

```bash
source .venv/bin/activate
uvicorn backend.main:app --reload --port 8000
```

Terminal 2:

```bash
source .venv/bin/activate
streamlit run frontend/app.py
```

Demo conocida:

- Merchant: `Rappi`
- Country: `Brazil`
- Provider: `Stripe`
- Target approval rate: `20%`
- Duration: `6` windows

Después de implementar:

```bash
python -m pytest -q
```

## Definition of Done

- [ ] El panel aparece sólo para el incidente y merchant correctos.
- [ ] Una recomendación muestra destino, tráfico, beneficio esperado, confianza
      y rationale.
- [ ] Los ocho estados del workflow se representan correctamente.
- [ ] Aprobar, rechazar, revocar, aplicar, revertir y completar llaman al endpoint
      correspondiente.
- [ ] Cada acción refresca el estado desde el backend.
- [ ] La simulación activa muestra métricas before/expected/observed.
- [ ] El audit log se puede inspeccionar desde la UI.
- [ ] Los errores de red o validación se muestran sin crashear el dashboard.
- [ ] No se fabrican métricas ni estados en el frontend.
- [ ] Ningún texto o botón sugiere que se modificó routing real.
- [ ] No se agregan credenciales ni llamadas a proveedores.
- [ ] El flujo funciona con `MOCK_MODE=true`.
- [ ] `python -m pytest -q` sigue pasando.

## Nota para quien implemente

La prioridad es que el flujo completo sea entendible y confiable durante la
demo. La lógica de autorización, elegibilidad, expiración y rollback pertenece
al backend. El frontend debe presentar ese estado y enviar intenciones humanas,
no volver a decidir las reglas.
