# MVP-01 — Dataset histórico reproducible

El histórico base se guarda en `data/historical_transactions_2025_seed42.csv`.
Fue generado con `seed=42`; no contiene incidentes inyectados y es la fuente para
entrenar y validar el baseline estacional.

Cada ejecución contiene transacciones validadas contra `Transaction` y las columnas
derivadas `hour_of_week` y `split`:

```text
Jan–Apr   train
May–Aug   validation
Sep–Dec   test
```

## Regenerar exactamente el archivo

Desde la raíz del repositorio, con las dependencias de `requirements.txt`
instaladas:

```powershell
& 'C:\Users\sofia\AppData\Local\Programs\Python\Python311\python.exe' -c "from backend.data_generator import generate_one_year, persist_historical_dataset; frame = generate_one_year(seed=42, year=2025); print(persist_historical_dataset(frame, 'data/historical_transactions_2025_seed42.csv'))"
```

Para explorar un intervalo corto durante desarrollo, usar
`generate_historical_transactions(seed=..., start=..., end=...)`. Los límites deben
estar alineados a una hora UTC exacta.

El stream live no debe copiar este volumen directamente: MVP-02 reutiliza la misma
estacionalidad y tasas esperadas, pero aumenta los intentos por ventana simulada de
cinco minutos para cumplir el mínimo de 50 transacciones del detector.
