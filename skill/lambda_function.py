"""
Skill de Alexa — asistente conversacional con Groq.

Corre en Alexa-hosted (Python). Sin dependencias externas: usa urllib de la
stdlib, así el build del Lambda no puede fallar por un paquete.

Por qué Groq y no Gemini: se midieron los dos al mismo ritmo y con las mismas
preguntas. Gemini free tier daba 36 % de riesgo de corte (peor caso 19,55 s);
Groq dio 0 % (peor caso 0,70 s). Detalle en docs/mediciones.md.

Alexa corta a los ~8 segundos. El peor caso medido está once veces por debajo
del presupuesto, pero el timeout defensivo va igual: ningún servicio garantiza
responder siempre.
"""

import json
import logging
import os
import urllib.error
import urllib.request

from ask_sdk_core.dispatch_components import (
    AbstractExceptionHandler,
    AbstractRequestHandler,
)
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.utils import get_slot_value, is_intent_name, is_request_type
from ask_sdk_model import Intent
from ask_sdk_model.dialog import ElicitSlotDirective

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --------------------------------------------------------------------------
# Configuración
# --------------------------------------------------------------------------

# Pegar la API key de console.groq.com acá, en la consola de Alexa.
# NUNCA commitear la key real a Git — este archivo del vault lleva el placeholder.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "PEGAR_API_KEY_ACA")

# Medidos los dos con 0 % de riesgo. El 120b es más capaz y su peor caso (0,70 s)
# sigue estando ocho veces por debajo del presupuesto. Si algún día apura el
# tiempo, cambiar a openai/gpt-oss-20b (peor caso 0,46 s).
GROQ_MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

# Timeout propio, por debajo del corte de Alexa (~8 s). Generoso contra un peor
# caso medido de 0,70 s: si se llega acá, algo está roto, no lento.
HTTP_TIMEOUT = 5.0

# Cuántos turnos de ida y vuelta se recuerdan dentro de la sesión.
MAX_TURNOS = 10

SYSTEM_INSTRUCTION = (
    "Sos un asistente por voz que responde a través de un parlante Alexa, en "
    "español rioplatense (vos, no tú). "
    "Reglas que no se rompen: "
    "1) Respondé en 50 palabras o menos. Es voz: nadie escucha párrafos largos. "
    "2) Empezá por la respuesta. Sin preámbulos ni 'buena pregunta'. "
    "3) Nada de markdown, viñetas, asteriscos ni emojis: todo se va a leer en voz alta. "
    "4) Números y unidades en palabras cuando sea más natural escucharlos. "
    "5) Si no sabés algo, decilo en una frase en vez de inventar. "
    "6) Si la pregunta es ambigua, respondé lo más probable y ofrecé precisar."
)

REPROMPT = "¿Algo más?"
ERROR_MSG = "Se me complicó conectarme. ¿Probamos de nuevo?"


# --------------------------------------------------------------------------
# Groq
# --------------------------------------------------------------------------


def _consultar_groq(historial):
    """Manda el historial a Groq y devuelve el texto de la respuesta.

    `historial` es la lista de mensajes en formato OpenAI:
    [{"role": "user"|"assistant", "content": ...}].
    Devuelve None si falla, para que el handler responda algo amable.
    """
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "system", "content": SYSTEM_INSTRUCTION}] + historial,
        "temperature": 0.7,
        # 1000 y no 200: el razonamiento consume del mismo presupuesto. Con 200
        # la respuesta vuelve VACIA con finish_reason=length. Verificado midiendo.
        "max_tokens": 1000,
        # Baja el razonamiento al mínimo: 75 tokens en vez de 323, y 0,44 s en
        # vez de 0,67 s. Solo acepta low/medium/high — "none" da HTTP 400.
        "reasoning_effort": "low",
        # Saca el campo `reasoning` de la respuesta: no se usa.
        "reasoning_format": "hidden",
    }

    req = urllib.request.Request(
        GROQ_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {GROQ_API_KEY}",
            # Obligatorio. Sin User-Agent propio, Cloudflare devuelve 403
            # "error code: 1010" bloqueando el de urllib. Verificado.
            "User-Agent": "alexa-ia/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("Groq HTTP %s: %s", e.code, e.read().decode("utf-8", "replace"))
        return None
    except Exception:
        logger.exception("Falló la llamada a Groq")
        return None

    try:
        texto = cuerpo["choices"][0]["message"]["content"]
    except (KeyError, IndexError):
        logger.warning("Respuesta sin texto utilizable: %s", json.dumps(cuerpo)[:500])
        return None

    # Con max_tokens chico el content puede venir vacío aunque la request sea 200.
    if not texto or not texto.strip():
        motivo = cuerpo.get("choices", [{}])[0].get("finish_reason", "?")
        logger.warning("Content vacío, finish_reason=%s", motivo)
        return None

    return texto.strip()


def _elicit(handler_input, texto, reprompt=None):
    """Habla y deja el micrófono abierto esperando la próxima pregunta.

    `updated_intent` es obligatorio: sin él, Alexa no sabe a qué intent pertenece
    el slot `query` y responde "Hubo un problema con la respuesta de la Skill".
    Se nota sobre todo en LaunchRequest, donde no hay ningún intent activo.
    """
    return (
        handler_input.response_builder.speak(texto)
        .ask(reprompt or REPROMPT)
        .add_directive(
            ElicitSlotDirective(
                slot_to_elicit="query",
                updated_intent=Intent(name="PreguntaIntent", slots={}),
            )
        )
        .response
    )


def _limpiar_para_voz(texto):
    """Saca lo que no se puede leer en voz alta y escapa el XML del SSML."""
    for simbolo in ("**", "*", "#", "`", "_"):
        texto = texto.replace(simbolo, "")
    return texto.replace("&", " y ").replace("<", "").replace(">", "")


def _responder(handler_input, pregunta):
    """Núcleo compartido: consulta, guarda historial y vuelve a abrir el micrófono."""
    attrs = handler_input.attributes_manager.session_attributes
    historial = attrs.get("historial", [])

    historial.append({"role": "user", "content": pregunta})

    respuesta = _consultar_groq(historial)

    if respuesta is None:
        # No guardamos el turno fallido: dejaría el historial con un user suelto.
        historial.pop()
        salida = ERROR_MSG
    else:
        historial.append({"role": "assistant", "content": respuesta})
        salida = _limpiar_para_voz(respuesta)

    # Se recortan turnos completos (user + assistant) para no romper la alternancia.
    attrs["historial"] = historial[-(MAX_TURNOS * 2) :]
    handler_input.attributes_manager.session_attributes = attrs

    # ElicitSlot deja el micrófono abierto SIN exigir frase portadora: es lo que
    # permite seguir hablando natural en vez de decir "pregunta ..." cada vez.
    return _elicit(handler_input, salida)


# --------------------------------------------------------------------------
# Handlers
# --------------------------------------------------------------------------


class LaunchRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        return _elicit(
            handler_input, "Hola. ¿Qué querés saber?", "Contame qué necesitás."
        )


class PreguntaIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("PreguntaIntent")(handler_input)

    def handle(self, handler_input):
        pregunta = get_slot_value(handler_input, "query")
        if not pregunta:
            return _elicit(handler_input, "No te escuché. ¿Me repetís?")
        return _responder(handler_input, pregunta)


class CancelOrStopIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.CancelIntent")(handler_input) or is_intent_name(
            "AMAZON.StopIntent"
        )(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.speak("Listo. Hasta luego.").response


class HelpIntentHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        ayuda = (
            "Preguntame lo que quieras y te respondo. "
            "Para terminar, decí: para."
        )
        return _elicit(handler_input, ayuda)


class FallbackIntentHandler(AbstractRequestHandler):
    """Alexa no entendió. No hay texto para mandar al modelo: se pide repetir."""

    def can_handle(self, handler_input):
        return is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return _elicit(handler_input, "No te entendí. ¿Me lo repetís?")


class SessionEndedRequestHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAllExceptionHandler(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        logger.exception("Error no manejado: %s", exception)
        return (
            handler_input.response_builder.speak(ERROR_MSG).ask(REPROMPT).response
        )


sb = SkillBuilder()
sb.add_request_handler(LaunchRequestHandler())
sb.add_request_handler(PreguntaIntentHandler())
sb.add_request_handler(HelpIntentHandler())
sb.add_request_handler(CancelOrStopIntentHandler())
sb.add_request_handler(FallbackIntentHandler())
sb.add_request_handler(SessionEndedRequestHandler())
sb.add_exception_handler(CatchAllExceptionHandler())

lambda_handler = sb.lambda_handler()
