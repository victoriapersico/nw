# MVP-03 — Evaluación sintética determinista

El harness valida el sistema completo, no lo reemplaza. Cada escenario contiene:

```text
seed + timestamp + volumen + estímulo para el simulador + resultado esperado
```

El runtime aplica `InjectionConfig` sólo al simulador, genera `TransactionBatch` y
llama al detector con `DetectionRequest(batch=...)`. El detector nunca recibe la
configuración de inyección. Después, el harness compara los `Incident` y
`Diagnosis` observados con las expectativas del escenario.

## Los 30 escenarios

El catálogo vive en `backend.evaluation.scenarios.SCENARIOS`. Incluye los treinta
casos del challenge: normales, variación de fin de semana, ruido de bajo volumen,
provider/método/banco/code, intersecciones, incidentes simultáneos, abstención,
repetición opcional y slice no visto. Las seeds son únicas y estables.

Los escenarios 22–25 usan varias `InjectionConfig`, una por país, conforme a
DEC-026. El escenario 29 se registra como `optional`: la memoria de incidentes es
post-MVP y no puede convertir una ejecución en failure.

## Cómo se ejecuta

Una vez que MVP-02 y MVP-05 entren a la rama, crear un adapter pequeño que cumpla
el protocolo `EvaluationRuntime` en `backend.evaluation.harness`. Debe exponer:

```text
reset(scenario)
apply_injection(config)
next_batch() -> TransactionBatch
detect(DetectionRequest) -> DetectionResponse
diagnose(Incident) -> Diagnosis
```

Después, una ejecución genera ambos artefactos:

```powershell
python -m backend.evaluation --runtime backend.integration.evaluation_runtime:build_runtime --output artifacts/evaluation
```

- `artifacts/evaluation/evaluation_results.json`: machine-readable.
- `artifacts/evaluation/evaluation_summary.md`: resumen legible y tabla pass/fail.

Mientras el runtime no esté mergeado se puede inspeccionar la especificación sin
simular nada:

```powershell
python -m backend.evaluation --list
```

## Métricas

El reporte calcula recall de detección, false-positive rate, exactitud de causa,
separación de incidentes, exactitud de abstención y latencia media. El error de
loss queda explícitamente como no disponible hasta que el runtime exponga la
pérdida sintética ground-truth; no se inventa una métrica para el pitch.
