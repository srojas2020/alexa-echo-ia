# Decisiones de diseño

Cada decisión con su motivo, sus alternativas y —cuando corresponde— qué la superó. Las decisiones
superadas se conservan: el registro de por qué algo dejó de valer suele ser más útil que la
decisión vigente.

---

## D-01 — La skill corre en Alexa-hosted, no en un servidor propio

**Aceptada.** Elimina el túnel, los certificados SSL y la dependencia de tener una máquina
encendida. La skill vive en la nube de Amazon y funciona 24/7, gratis.

*Alternativas consideradas:* servidor local + ngrok · servidor local + Cloudflare Tunnel · Lambda en
cuenta de AWS propia.

---

## D-02 — La conversación usa elicitación de slot, no frases portadoras

**Aceptada.** `AMAZON.SearchQuery` es el único slot que captura frases libres, pero la consola
rechaza un utterance que sea solo `{query}`: exige una frase portadora. Eso obligaría a decir
*"pregunta X"* en cada turno.

La documentación de Amazon exime de esa regla a los **slot samples**. Devolviendo un
`ElicitSlotDirective` después de cada respuesta, la conversación queda permanentemente en
elicitación y el usuario habla natural.

**Efecto:** se dice la frase de invocación una sola vez y después se conversa sin fórmulas.

---

## D-03 — La llamada HTTP se hace con `urllib`, no con un SDK

**Aceptada.** Cero dependencias. En Alexa-hosted, cada paquete agregado a `requirements.txt` es un
build que puede fallar y dejar la skill muerta sin un error legible.

---

## D-04 — Ninguna suscripción de consumidor sirve como backend

**Aceptada.** Se evaluó usar una suscripción ya paga en lugar de una API. **Las tres opciones lo
prohíben o no lo habilitan**, según su propia documentación:

| Suscripción | Qué dice la fuente oficial |
|---|---|
| Claude Pro/Max | El OAuth es *"exclusively (…) to support ordinary use of Claude Code"*; quien construye servicios *"should use API key authentication"* |
| ChatGPT Plus | Los términos prohíben usar los servicios *"automatically or programmatically"* |
| Google AI Pro/Ultra | *"Google AI plan benefits for developer usage apply only within the Google AI Studio web interface. Direct use of the Gemini API (…) is billed and managed separately"* |

**Sobre OAuth:** no existe una ruta que permita a una suscripción de consumidor llamar a la API. La
suscripción sube los límites **dentro de la interfaz web**, no los de la API.

**Efecto:** la API key de un free tier es el camino, y sigue costando USD 0.

---

## D-05 — ~~El proveedor es el free tier de Gemini~~ · **Superada por D-08**

**Motivo original:** costo cero, sin tarjeta, 1.500 solicitudes diarias — de sobra para uso
doméstico.

**Por qué cayó:** se decidió sobre límites de **cuota** sin medir **latencia**. Al medirla, el free
tier resultó tener 36 % de riesgo de corte por prioridad de cola.

> **La cuota nunca fue el problema; el tiempo de respuesta sí.**

---

## D-06 — El locale determina qué componentes existen

**Aceptada.** Los slots e intents integrados de Alexa **no existen en todos los idiomas**. Antes de
fijar el locale se verificó en la documentación oficial que los dos componentes del diseño
existieran en él.

**Por qué se verificó:** si `AMAZON.SearchQuery` no hubiera estado disponible, no era un ajuste —se
caía el diseño entero de la conversación (D-02) y había que rehacerlo.

---

## D-07 — El nombre de invocación necesita dos palabras en español

**Aceptada.** La consola rechaza un nombre de una sola palabra con *"El nombre de invocación debe
tener al menos 2 palabras"*.

**Error de origen:** el nombre inicial se tomó de un repositorio de referencia que trabaja en locales
en inglés, donde la regla es distinta, y **se dio por válido sin verificarlo para el locale real**.

*Restricciones:* dos palabras o más · minúsculas · **no puede contener "Alexa"** · los nombres de
marca requieren prueba de derechos.

> Segunda vez en el proyecto que algo tomado de un ejemplo en inglés no aplica igual en español.
> **Lo que venga de un repositorio de referencia se verifica contra el locale real.**

---

## D-08 — El proveedor es Groq, modelo `openai/gpt-oss-120b`

**Aceptada.** Medido con la misma vara que Gemini: peor caso **0,70 s contra 19,55 s**, y **0 % de
riesgo de corte contra 36 %**. Números completos en [`mediciones.md`](mediciones.md).

**Por qué el 120b y no el 20b, más rápido:** con el peor caso once veces por debajo del presupuesto,
la velocidad deja de ser criterio. Gana la capacidad.

Sigue siendo gratis y sin tarjeta: 30 solicitudes por minuto, 14.400 por día.

---

## D-09 — La defensa contra latencia es un timeout, no una cascada

**Aceptada.** Con el proveedor anterior (36 % de fallos) se había planificado correr dos proveedores
en paralelo y tomar el primero que respondiera. Con 0,70 s de peor caso esa complejidad dejó de
justificarse.

**Queda:** timeout propio de 5 s y degradación con gracia — si no llega, la skill dice una frase
corta y mantiene la sesión abierta en vez de morirse.

> **El problema de latencia se resolvió eligiendo bien el proveedor, no compensándolo con código.**

---

## D-10 — `ElicitSlotDirective` siempre lleva `updated_intent`

**Aceptada.** Sin él, Alexa responde *"Hubo un problema con la respuesta de la Skill"*. Se manifiesta
primero en el `LaunchRequest`, donde no hay ningún intent activo del que Alexa pueda deducir a qué
intent pertenece el slot.

```python
ElicitSlotDirective(
    slot_to_elicit="query",
    updated_intent=Intent(name="PreguntaIntent", slots={}),
)
```

**Efecto:** toda elicitación pasa por un helper único — un solo lugar, cinco handlers. No se arma la
directiva a mano en ningún otro punto.

---

## D-11 — El modelo **no** lleva `AMAZON.FallbackIntent`

**Aceptada.** **`AMAZON.FallbackIntent` es incompatible con la elicitación de un slot
`AMAZON.SearchQuery`.** Con el Fallback presente, la pregunta del usuario no llega al slot: se
desvía al Fallback y el diálogo se pierde.

Confirmado en los foros de Amazon: *"the FallbackIntent is invoked and the dialog is lost"*.

**Qué se pierde:** el mensaje de "no te entendí". **Nada, en la práctica:** el diseño busca
justamente que *todo* lo dicho vaya al slot.

*Refuerzo:* `modelConfiguration.fallbackIntentSensitivity: LOW`, por si la plataforma reintrodujera
el modelo out-of-domain por su cuenta.

---

## D-12 — Después de un `Deploy`, esperar antes de diagnosticar

**Aceptada.** **AWS Lambda no recicla los contenedores calientes al desplegar.** Durante unos minutos
conviven la versión anterior y la nueva, y cada solicitud cae en una u otra. Eso produce fallos
intermitentes que parecen bugs del código y no lo son.

**Cómo se manifestó:** CloudWatch mostraba `Runtime.UserCodeSyntaxError` mientras el archivo local
compilaba sin errores. Sin tocar nada, la skill empezó a funcionar al reciclarse los contenedores.

**Efecto:** tras un deploy, si algo falla de forma rara, **esperar dos minutos y reintentar antes de
cambiar código**. Se estuvo a punto de reescribir código que ya estaba bien.

---

## Lo que estas decisiones tienen en común

Cinco de las doce corrigen una suposición que parecía razonable:

- La cuota parecía la métrica relevante — era la latencia (D-05).
- El límite de solicitudes parecía explicar la varianza — no era (mediciones §4).
- Un nombre de invocación válido en inglés parecía válido en español — no lo era (D-07).
- Un archivo que compila localmente parecía garantizar que el desplegado también — no (D-12).
- Un error de sintaxis parecía un bug del código — era infraestructura (D-12).

**El patrón:** cada suposición entró a la documentación con la misma cara que un hecho. El costo no
fue el error en sí, sino lo que se construyó encima antes de descubrirlo.
