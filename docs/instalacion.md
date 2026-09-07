# Guía de instalación

**Tiempo:** 25–35 minutos la primera vez. **Costo:** USD 0 — no se carga tarjeta en ningún paso.

Las trampas están señaladas con ⚠️ en el punto donde aparecen. Todas fueron encontradas
desplegando esto de verdad.

---

## Antes de empezar — dos confirmaciones

Cinco minutos que evitan el error más común: llegar al final y que la skill no aparezca, sin ningún
mensaje que lo explique.

### 1 · El idioma del dispositivo

> App Alexa → Más → Configuración → Configuración del dispositivo → *tu Echo* → Idioma

**Anotar el valor textual** (`Español (México)`, `Español (España)`, `English (US)`…). Ese es el
*Primary locale* de la skill, y **tiene que coincidir**: si no, la skill no responde en el
dispositivo.

⚠️ **Los componentes integrados no existen en todos los locales.** Antes de continuar, verificar en
la [referencia de tipos de slot](https://developer.amazon.com/en-US/docs/alexa/custom-skills/slot-type-reference.html)
que `AMAZON.SearchQuery` esté disponible en el tuyo. Si no lo está, este diseño no funciona ahí.

### 2 · Que las dos cuentas sean la misma

Una skill en modo Development solo aparece en dispositivos de **la misma cuenta de Amazon** que la
creó.

- **Cuenta del dispositivo:** app Alexa → Más → Configuración → Configuración de la cuenta
- **Cuenta de la consola:** [developer.amazon.com](https://developer.amazon.com/alexa/console/ask) →
  tus iniciales, arriba a la derecha → Settings → My Account

Tienen que ser idénticas.

---

## Paso 1 · API key de Groq

1. [console.groq.com](https://console.groq.com) → registrarse.
2. **API Keys** → **Create API Key**. Empieza con `gsk_`.

Free tier: 30 solicitudes por minuto, 14.400 por día. Sin tarjeta y sin vencimiento.

🔒 **La key no se commitea nunca.** `lambda_function.py` lleva el placeholder `PEGAR_API_KEY_ACA` y
así se queda en el repositorio.

---

## Paso 2 · Crear la skill

⚠️ **El botón "Create Skill" no existe hasta completar el registro de desarrollador.** Si es tu
primera vez, la consola te muestra un formulario de alta: es único y gratuito.

⚠️ En la pantalla siguiente, cuando pregunte si planeás monetizar apps, **responder que NO.** De lo
contrario pide datos bancarios y fiscales que no hacen falta para una skill privada.

⚠️ **No confundir con "Consola para desarrolladores de Alexa+".** Esa es para la Alexa con IA
generativa de Amazon, de la que los dispositivos antiguos están excluidos.

Una vez dentro de [la consola de Alexa](https://developer.amazon.com/alexa/console/ask):

| Campo | Valor |
|---|---|
| Skill name | El que quieras — es solo una etiqueta |
| **Primary locale** | **El que confirmaste del dispositivo** |
| Type of experience | `Other` |
| Model | `Custom` |
| **Hosting service** | **`Alexa-hosted (Python)`** ← la clave de que sea gratis |
| Template | `Start from Scratch` |

⚠️ **Verificar que quedó como Alexa-hosted.** Si al abrir la pestaña Code dice *"El editor de código
solo funciona con una skill alojada en Alexa"*, la opción no se aplicó. Se corrige con el botón
**"Convertir a la versión alojada por Alexa"**, que conserva el modelo de interacción intacto.

---

## Paso 3 · Cargar el modelo de interacción

⚠️ **Si la consola está en español, los botones están mal traducidos:**
*"Ahorrar"* = **Guardar** · *"Desarrollar habilidades"* = **Construir**.
Conviene pasarla a inglés desde el pie de página.

1. **Build** → **Interaction Model** → **JSON Editor**
2. Borrar todo y pegar [`skill/interaction-model.json`](../skill/interaction-model.json)
3. Cambiar `invocationName` por el que prefieras
4. **Save** → **Build**

⚠️ **En español, el nombre de invocación necesita dos palabras o más.** Con una sola, la consola
marca *"El nombre de invocación debe tener al menos 2 palabras"* y no compila. Tampoco puede
contener la palabra "Alexa".

### Verificar que quedó bien

El build no siempre avisa cuando termina. **Invocations → Skill Invocation Name** tiene que mostrar
el nombre que pusiste: esa es la prueba de que el JSON se aplicó.

---

## Paso 4 · Cargar el código

1. Pestaña **Code** → abrir `lambda_function.py`
2. Borrar todo y pegar [`skill/lambda_function.py`](../skill/lambda_function.py)
3. Reemplazar `PEGAR_API_KEY_ACA` por tu key, **dejando las comillas**
4. **No tocar `requirements.txt`** — un paquete agregado puede romper el build
5. **Save** → **Deploy**

⚠️ Después de pegar, verificar que **no haya indentación agregada** al principio de las líneas.
Algunos editores auto-indentan al pegar, y en Python eso rompe el módulo entero.

---

## Paso 5 · Probar

### En el simulador

1. Pestaña **Test**
2. Cambiar el selector de `Off` a **`Development`** ← sin esto la skill no existe para nadie
3. Escribir `abre <tu nombre de invocación>`

### En el dispositivo

> *"Alexa, abre &lt;tu nombre de invocación&gt;"*

Para cortar: *"para"* o *"cancela"*.

⚠️ **El verbo cambia el comportamiento:** *"abre"* arranca con la memoria en blanco; *"activa"* hace
que Alexa reanude la sesión anterior y conserve el historial.

---

## Si algo falla

| Síntoma | Causa más probable | Solución |
|---|---|---|
| Falla raro **justo después de un Deploy** | **Contenedores Lambda calientes con la versión vieja** | **Esperar 2 minutos y reintentar antes de tocar nada** |
| "No encontré una skill llamada…" | Cuentas distintas, o el selector sigue en `Off` | Revisar las dos cuentas y el Paso 5.2 |
| *"Hubo un problema con la respuesta de la Skill"* | Excepción en el Lambda | CloudWatch Logs → buscar `ERROR` o `Traceback` |
| Saluda pero la pregunta cae en "no te entendí" | `AMAZON.FallbackIntent` presente en el modelo | Quitarlo — es incompatible con la elicitación de `SearchQuery` |
| Responde *"Se me complicó conectarme"* | API key, o el modelo cambió de nombre | CloudWatch → buscar `Groq HTTP` o `Content vacío` |
| Se queda muda de a ratos | `max_tokens` bajo: el razonamiento consume el presupuesto | **No bajar `max_tokens` de 1000** |
| El editor de código carga en negro | Falta de memoria del navegador | Cerrar otras aplicaciones y recargar |
| El build falla | Se modificó `requirements.txt` | Dejarlo como estaba |

**Los logs son el lugar donde mirar:** pestaña Code → botón **CloudWatch Logs**. El código registra
el estado HTTP, el cuerpo de la respuesta y el `finish_reason` cuando el contenido llega vacío.

---

## Sobre los costos

**La cuenta de desarrollador de Amazon es gratuita y no tiene suscripción.**

Alexa-hosted corre sobre el free tier permanente de AWS Lambda: **1 millón de solicitudes por mes**,
que se renuevan y **no vencen a los 12 meses** (ese vencimiento aplica a otros servicios de AWS, no
a Lambda). Un uso doméstico está varios órdenes de magnitud por debajo.
