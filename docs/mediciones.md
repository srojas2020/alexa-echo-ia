# Mediciones de latencia

Todas las mediciones se hicieron desde una conexión doméstica en Argentina, con las API keys del
free tier de cada proveedor, en septiembre de 2026.

**La restricción que define todo:** Alexa corta la respuesta a los ~8 segundos con
`SKILL_RESPONSE_TIMEOUT_EXCEPTION`. Las *progressive responses* **no extienden** ese límite — la
documentación de Amazon es explícita: todo el procesamiento debe caber en esos 8 segundos.

Presupuesto de trabajo adoptado: **6 segundos**, dejando margen para la ida y vuelta con Amazon.

---

## 1 · Comparativa inicial de modelos de Gemini

| Modelo | Promedio | Peor | Fallos | Veredicto |
|---|---|---|---|---|
| `gemini-3.5-flash-lite` | 7,68 s | **17,11 s** | 0 | Riesgoso |
| `gemini-3.5-flash` | 4,62 s | 4,62 s | 3 timeouts | Riesgoso |
| `gemini-3.7-flash` | 5,77 s | 5,77 s | 3 timeouts | Riesgoso |

Las respuestas que sí volvieron de `flash` y `3.7-flash` llegaron **truncadas en 1 y 4 palabras**.

---

## 2 · El razonamiento, y una sorpresa

Los modelos de razonamiento piensan antes de responder, y **ese pensamiento consume el mismo
presupuesto de `max_tokens` que la respuesta**. Con 200 tokens, el razonamiento se los lleva enteros
y devuelve una frase cortada. Medido: `gemini-3.5-flash` gastó **768 tokens pensando** una respuesta
de 40 palabras.

Sintaxis correcta, hallada probando —las fuentes discrepaban entre sí:

| Sintaxis | Resultado |
|---|---|
| `generationConfig.thinkingConfig.thinkingLevel` | ✅ Válida |
| `generationConfig.thinkingLevel` (plano) | ❌ HTTP 400 — *"Unknown name"* |
| `thinkingConfig.thinkingBudget: 0` | ✅ En `flash` · ❌ HTTP 400 en `flash-lite` |

**La sorpresa:** en `flash-lite` el razonamiento **ya viene desactivado**. Configurarlo lo empeora —
`minimal` → 13,99 s, `low` → timeout. Su baseline sin tocar nada es 1,6 s. Por eso `thinkingBudget: 0`
devuelve 400: no hay nada que desactivar.

---

## 3 · Distribución a ritmo de stress (48 llamadas)

| Configuración | Mediana | p90 | Peor | Riesgo de corte |
|---|---|---|---|---|
| `maxOutputTokens=200` | 2,06 s | 6,49 s | 16,75 s | **25 %** |
| `maxOutputTokens=100` | 1,74 s | 16,09 s | 17,47 s | **42 %** |

Bajar los tokens **empeoró** el resultado. Eso llevó a una hipótesis: que las llamadas consecutivas
estuvieran saturando el límite de solicitudes por minuto y se estuviera midiendo el propio
throttling en lugar de la experiencia de uso.

---

## 4 · Ritmo real de conversación — la medición que decide

**La hipótesis del throttling era incorrecta.** Se remidió a 5 preguntas por minuto —un tercio del
límite— con 12 segundos de pausa entre cada una, simulando el tiempo que Alexa tarda en leer la
respuesta en voz alta:

```
mediana (p50)  :  2,16 s
p90            : 15,83 s
peor           : 19,55 s
fallos         : 2 timeouts de 25 s sobre 14 llamadas
>>> RIESGO DE CORTE: 36 %
```

**A un tercio del límite de solicitudes, el riesgo subió.** No era throttling.

---

## 5 · Descarte de la red

| Métrica | Mínimo | Mediana | Máximo |
|---|---|---|---|
| TCP connect | 18 ms | **29 ms** | 274 ms |
| TLS handshake | 73 ms | **78 ms** | 148 ms |

El enlace es estable y rápido. **Una conexión que se establece en 100 ms no explica una respuesta de
20 segundos.** La varianza la produce el servicio, no el transporte.

**Conclusión por descarte:** la causa es la prioridad de cola del free tier. Es coherente con que el
servicio sea gratuito, y no se corrige desde el código.

---

## 6 · Groq, medido con la misma vara

Mismas preguntas, mismo ritmo, mismo presupuesto:

| Proveedor | Mediana | Peor | Fallos | Riesgo |
|---|---|---|---|---|
| Gemini free `flash-lite` | 2,16 s | **19,55 s** | 2 | **36 %** |
| Groq `openai/gpt-oss-20b` | 0,40 s | 0,46 s | 0 | **0 %** |
| **Groq `openai/gpt-oss-120b`** | **0,55 s** | **0,70 s** | 0 | **0 %** |

**El peor caso pasó de 19,55 s a 0,70 s: veintiocho veces mejor, y once veces por debajo del
presupuesto.** Cero cortes en doce llamadas.

### Por qué el 120b y no el 20b, siendo el 20b más rápido

Con el peor caso once veces por debajo del presupuesto, **la velocidad deja de ser un criterio de
decisión**. Los 0,15 segundos de diferencia son imperceptibles en una interfaz de voz. Gana la
capacidad: el 120b da mejores respuestas y su peor caso sigue ocho veces por debajo del límite.

Optimizar milisegundos que nadie va a notar, a costa de calidad, es optimizar la métrica equivocada.

---

## 7 · Configuración final de la llamada

Los cuatro parámetros salieron de medición directa. Tres son contraintuitivos y **cada uno rompía la
skill de una forma distinta y silenciosa**:

| Parámetro | Valor | Qué pasa si falta |
|---|---|---|
| `max_tokens` | **1000** | Con 200, el razonamiento consume el presupuesto: `content` vuelve **vacío** con `finish_reason: length`. HTTP 200, sin error. Dejó 4 de 6 respuestas mudas |
| `reasoning_effort` | **`"low"`** | Sin esto gasta 323 tokens en vez de 75 y tarda 0,67 s en vez de 0,44 s. Solo acepta `low`/`medium`/`high` — `"none"` da HTTP 400 |
| `reasoning_format` | **`"hidden"`** | Devuelve un campo `reasoning` que no se usa |
| `User-Agent` | **propio** | Sin él, **Cloudflare devuelve 403 `error code: 1010`**. No es un error del proveedor y el mensaje no lo dice |

También se descartaron `qwen3.6-27b` —emite bloques `<think>` dentro del texto— y
`groq/compound-mini`, que rechaza `reasoning_effort`.

---

## 8 · Validación de la conversación

Cuatro turnos encadenados contra la función real del Lambda, no una copia:

| # | Pregunta | Qué verifica |
|---|---|---|
| 1 | ¿Cuánto mide el Aconcagua? | Respuesta simple |
| 2 | ¿Y cuál es el segundo más alto de América? | Continuidad de tema |
| 3 | De los dos que nombraste, ¿cuál es más difícil de escalar? | **Memoria de ambos turnos previos** |
| 4 | ¿En qué país queda ese último? | **Resolución de referencia anafórica** |

Los cuatro correctos. Peor tiempo: 0,67 s.

---

## Por qué valió la pena medir antes de desplegar

Sin estas mediciones, el síntoma en producción habría sido *"a veces funciona y a veces se queda
muda"* — el peor tipo de error para diagnosticar, con el agravante de que cada intento de corrección
implica editar y redesplegar el Lambda.

Las mediciones costaron unos veinte minutos y produjeron un número accionable.
