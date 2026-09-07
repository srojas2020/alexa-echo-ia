# Alexa IA — Conversación con un LLM en un Echo Dot de 2016

Skill personalizada de Alexa que convierte un **Echo Dot de segunda generación** —un dispositivo que
Amazon excluyó de Alexa+, su asistente con IA generativa— en un asistente conversacional con memoria
de contexto.

**Costo de operación: USD 0/mes.** Sin cuenta de AWS, sin servidor propio, sin túneles, sin
certificados y sin dejar una PC encendida.

```
Echo Dot 2  →  Nube de Alexa  →  Lambda (Alexa-hosted, gratis)  →  Groq  →  respuesta hablada
```

---

## Por qué este repositorio puede interesar

No es un "hola mundo" de Alexa. Es el registro de un problema de ingeniería con una restricción dura
—**Alexa corta la respuesta a los 8 segundos**— resuelto midiendo en lugar de suponiendo.

El proveedor de IA elegido en el papel resultó inservible al medirlo, y hay **siete trampas
silenciosas** documentadas: fallos que devuelven HTTP 200, errores atribuibles al proveedor
equivocado y reglas que cambian según el idioma. Cada una está en [`docs/decisiones.md`](docs/decisiones.md)
con su síntoma, su causa y su verificación.

---

## El hallazgo principal: la cuota no es el problema, la latencia sí

La primera elección fue el free tier de Google Gemini. Sobre el papel era ideal: 1.500 solicitudes
por día, muy por encima del uso doméstico. **Se eligió por cuota, sin medir tiempo de respuesta.**

Al medirlo a ritmo real de conversación —una pregunta cada 12 segundos, un tercio del límite de
solicitudes:

| Proveedor | Mediana | p90 | Peor caso | Riesgo de corte |
|---|---|---|---|---|
| Gemini free `flash-lite` | 2,16 s | 15,83 s | **19,55 s** | **36 %** ❌ |
| Groq `openai/gpt-oss-20b` | 0,40 s | — | 0,46 s | **0 %** ✅ |
| **Groq `openai/gpt-oss-120b`** | **0,55 s** | — | **0,70 s** | **0 %** ✅ |

**Una de cada tres respuestas se habría cortado.** La mediana de Gemini era excelente; la cola, fatal.

### El diagnóstico, por descarte

| Hipótesis | Verificación | Resultado |
|---|---|---|
| ¿El modelo? | Se probaron los tres candidatos | No — el mejor fallaba igual |
| ¿El razonamiento del modelo? | Medido: 768 tokens gastados en pensar | Contribuía, pero no era la causa |
| ¿El límite de solicitudes? | Se remidió a un tercio del ritmo | **No — el riesgo subió.** Hipótesis refutada |
| ¿La red? | TCP 29 ms · TLS 78 ms de mediana | No — un enlace de 100 ms no explica 20 s |

Queda la **prioridad de cola del free tier**: coherente con que el servicio sea gratuito, y no
corregible desde el código.

**La conclusión que vale más allá de este proyecto:** un free tier se evalúa por su distribución de
latencia, no por su cuota. Y se decide por el **percentil 90**, no por la mediana — en una interfaz
de voz, el peor caso es el que arruina la experiencia.

---

## Las trampas silenciosas

Ninguna de estas produce un error legible. Todas devuelven éxito aparente o culpan al componente
equivocado.

| # | Síntoma | Causa real |
|---|---|---|
| 1 | `403 error code: 1010` | **Cloudflare**, no la API: bloquea el `User-Agent` por defecto de `urllib` |
| 2 | Respuesta vacía con **HTTP 200** | El razonamiento del modelo consume `max_tokens` y deja `content` vacío con `finish_reason: length` |
| 3 | *"El nombre de invocación debe tener al menos 2 palabras"* | **En español**, Alexa exige 2+ palabras. En inglés, no |
| 4 | *"Hubo un problema con la respuesta de la Skill"* | `ElicitSlotDirective` sin `updated_intent`: en un `LaunchRequest` no hay intent del que deducir el slot |
| 5 | La pregunta cae en *"no te entendí"* | **`AMAZON.FallbackIntent` es incompatible** con la elicitación de un slot `AMAZON.SearchQuery` |
| 6 | `SyntaxError` en un archivo que compila bien | **Lambda no recicla los contenedores calientes al desplegar.** Conviven dos versiones unos minutos |
| 7 | Hay que decir *"pregunta X"* antes de cada frase | `AMAZON.SearchQuery` exige frase portadora — **salvo en los *slot samples***. Ver abajo |

### La trampa 7 define la experiencia de uso

`AMAZON.SearchQuery` es el único slot que captura una frase libre, pero la consola rechaza un
utterance que sea solo `{query}`: exige una frase portadora. Eso obligaría a decir *"pregunta cuánto
mide el Aconcagua"* en cada turno.

La documentación de Amazon tiene una excepción textual: *"you can omit the carrier phrase in **slot
samples**"*. Devolviendo un `ElicitSlotDirective` después de cada respuesta, la conversación queda
permanentemente en elicitación del slot y el usuario habla natural.

**Resultado:** se dice la frase de invocación una sola vez y después se conversa sin fórmulas.

---

## Arquitectura

```
Echo Dot 2
    │  "Alexa, abre mi asistente"
    ▼
Nube de Alexa            transcribe la voz
    │  PreguntaIntent · slot AMAZON.SearchQuery
    ▼
Lambda (Alexa-hosted)    Python, hospedado por Amazon, gratis
    │  HTTPS con urllib — sin dependencias externas
    ▼
Groq · openai/gpt-oss-120b
    │
    ▼
respuesta hablada ≤ 50 palabras
```

**Decisiones de diseño y su porqué:**

- **Alexa-hosted** en vez de servidor propio: elimina el túnel, los certificados y la dependencia de
  una máquina encendida.
- **`urllib` en vez de un SDK**: cero dependencias. En Alexa-hosted, cada paquete agregado es un
  build que puede fallar y dejar la skill muerta sin error legible.
- **Timeout propio de 5 s**: por debajo del corte de Alexa, para alcanzar a responder algo.
- **Sin cascada de proveedores**: se había diseñado una carrera entre dos proveedores para
  compensar el 36 % de fallos. Con 0,70 s de peor caso dejó de justificarse. **El problema de
  latencia se resolvió eligiendo bien, no compensando con código.**

---

## Estructura

```
skill/
  lambda_function.py       La skill. Se pega en la consola de Alexa
  interaction-model.json   Modelo de interacción (JSON Editor)
  requirements.txt         Sin dependencias añadidas, a propósito
tests/
  test_groq.py             Compara modelos: latencia y riesgo de corte
  test_ritmo_real.py       Mide a ritmo de conversación real, no de stress
  test_thinking.py         Encuentra la sintaxis correcta del razonamiento
  test_conversacion.py     Prueba la lógica real del Lambda sin Alexa
docs/
  instalacion.md           Paso a paso de despliegue, con las trampas señaladas
  mediciones.md            Los números completos y el diagnóstico por descarte
  decisiones.md            Cada decisión con su motivo y qué la superó
```

---

## Instalación

Guía completa en [`docs/instalacion.md`](docs/instalacion.md). Resumen:

1. API key gratuita en [console.groq.com](https://console.groq.com) — sin tarjeta.
2. Crear una skill en la [consola de Alexa](https://developer.amazon.com/alexa/console/ask):
   tipo `Custom`, hosting **`Alexa-hosted (Python)`**, locale igual al del dispositivo.
3. Pegar `interaction-model.json` en el JSON Editor → Save → Build.
4. Pegar `lambda_function.py` en la pestaña Code, reemplazar `PEGAR_API_KEY_ACA` → Save → Deploy.
5. En la pestaña Test, pasar el selector a `Development`.

> **La cuenta de desarrollador de Amazon es gratuita.** Alexa-hosted corre sobre el free tier
> permanente de AWS Lambda —1 millón de solicitudes mensuales, sin vencimiento a los 12 meses.

---

## Probar sin desplegar

Los scripts de `tests/` corren contra la API real, sin Alexa de por medio:

```bash
export GROQ_API_KEY="gsk_..."

python tests/test_groq.py          # compara modelos y mide riesgo de corte
python tests/test_conversacion.py  # 4 turnos encadenados con referencias hacia atrás
```

`test_conversacion.py` importa la función real del Lambda —no una copia— y simula los stubs del SDK
de Alexa. Verifica lo que las mediciones de latencia no cubren: que el historial se arme bien y que
el modelo resuelva referencias al turno anterior.

---

## Limitaciones conocidas

- **El hardware es de 2016.** El micrófono y la transcripción son los de ese dispositivo; con
  términos técnicos y nombres propios en inglés, flaquea.
- **El verbo de invocación cambia el comportamiento.** *"abre"* arranca limpio; *"activa"* hace que
  Alexa reanude la sesión anterior y conserve el historial.
- **La memoria dura lo que la sesión.** Se guardan 10 turnos en `session_attributes`; al cerrar, se
  pierden. Persistirla requeriría DynamoDB o S3.
- **No usar con datos sensibles.** Las consultas viajan a un free tier de un tercero.

---

## Licencia

MIT — ver [`LICENSE`](LICENSE).
