"""
Prueba la lógica de conversación del Lambda sin Alexa de por medio.

Importa la función real de lambda_function.py — no una copia — y simula tres
turnos encadenados. Valida lo único que las mediciones no cubrían: que el
historial se arme bien y que el modelo entienda referencias al turno anterior
("y eso por qué", "¿y en invierno?").

Uso:  GROQ_API_KEY=... python tests/test_conversacion.py
"""

import io
import os
import sys
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

if not os.environ.get("GROQ_API_KEY"):
    print("FALTA GROQ_API_KEY")
    sys.exit(1)

# ask_sdk no está instalado localmente: se stubean los imports que el Lambda hace
# al cargarse, para poder importar la lógica sin traer todo el SDK de Alexa.
import os  # noqa: E402
import types  # noqa: E402

# El Lambda vive en skill/; este test vive en tests/.
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "skill"))

for nombre in (
    "ask_sdk_core",
    "ask_sdk_core.dispatch_components",
    "ask_sdk_core.skill_builder",
    "ask_sdk_core.utils",
    "ask_sdk_model",
    "ask_sdk_model.dialog",
):
    mod = types.ModuleType(nombre)
    sys.modules.setdefault(nombre, mod)

sys.modules["ask_sdk_core.dispatch_components"].AbstractRequestHandler = object
sys.modules["ask_sdk_core.dispatch_components"].AbstractExceptionHandler = object
sys.modules["ask_sdk_core.skill_builder"].SkillBuilder = lambda: types.SimpleNamespace(
    add_request_handler=lambda *a: None,
    add_exception_handler=lambda *a: None,
    lambda_handler=lambda: None,
)
sys.modules["ask_sdk_core.utils"].get_slot_value = lambda *a, **k: None
sys.modules["ask_sdk_core.utils"].is_intent_name = lambda *a, **k: (lambda h: False)
sys.modules["ask_sdk_core.utils"].is_request_type = lambda *a, **k: (lambda h: False)
sys.modules["ask_sdk_model.dialog"].ElicitSlotDirective = object

import lambda_function as lf  # noqa: E402

TURNOS = [
    "¿Cuánto mide el Aconcagua?",
    "¿Y cuál es el segundo más alto de América?",
    "De los dos que nombraste, ¿cuál es más difícil de escalar?",
    "¿En qué país queda ese último?",
]


def main():
    print(f"Modelo: {lf.GROQ_MODEL}")
    print(f"Timeout: {lf.HTTP_TIMEOUT}s   Memoria: {lf.MAX_TURNOS} turnos\n")
    print("La prueba real son los turnos 3 y 4: obligan a recordar los anteriores.\n")

    historial = []
    tiempos = []

    for i, pregunta in enumerate(TURNOS, 1):
        historial.append({"role": "user", "content": pregunta})
        t0 = time.perf_counter()
        respuesta = lf._consultar_groq(historial)
        seg = time.perf_counter() - t0

        if respuesta is None:
            historial.pop()
            print(f"[{i}] FALLO tras {seg:.2f}s\n")
            continue

        historial.append({"role": "assistant", "content": respuesta})
        tiempos.append(seg)
        limpio = lf._limpiar_para_voz(respuesta)
        print(f"[{i}] ({seg:.2f}s)  VOS: {pregunta}")
        print(f"     ALEXA: {limpio}")
        print(f"     ({len(limpio.split())} palabras)\n")

    print("=" * 62)
    print(f"Turnos completados : {len(tiempos)}/{len(TURNOS)}")
    if tiempos:
        print(f"Peor tiempo        : {max(tiempos):.2f}s  (presupuesto {lf.HTTP_TIMEOUT}s)")
    print(f"Mensajes en historial: {len(historial)}")

    # El recorte tiene que dejar la alternancia intacta: primero un user.
    recortado = historial[-(lf.MAX_TURNOS * 2):]
    ok = recortado[0]["role"] == "user" if recortado else False
    print(f"Recorte de historial : {'OK' if ok else 'ROMPE LA ALTERNANCIA'}")
    print("=" * 62)
    print("\nLeer los turnos 3 y 4: si mencionan los cerros del turno 1 y 2,")
    print("la memoria de sesion funciona.")


if __name__ == "__main__":
    main()
