"""
La medición honesta: ritmo de conversación real, no de stress test.

Los tests anteriores dispararon decenas de llamadas lo más rápido posible y
dieron 25-42% de riesgo de corte. Pero el free tier ronda las 15 req/min: esos
tests estaban midiendo su propio throttling, no la experiencia de uso.

En una conversación real hay una pausa obligatoria entre preguntas: Alexa lee la
respuesta en voz alta (varios segundos) y recién ahí la persona vuelve a hablar.
Eso baja el ritmo a 3-5 preguntas por minuto.

Este script simula ese ritmo. Es el número que decide si el proyecto sirve.

Uso:  GEMINI_API_KEY=... python test_ritmo_real.py
"""

import json
import os
import statistics
import time
import urllib.request

API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODELO = "gemini-3.5-flash-lite"

# Pausa entre preguntas: lo que tarda Alexa en leer la respuesta en voz alta
# (~40 palabras a ritmo de habla) más el tiempo de pensar la siguiente.
PAUSA = 12.0
LLAMADAS = 14
PRESUPUESTO = 6.0

SYSTEM = (
    "Sos un asistente por voz en un parlante Alexa. Español rioplatense. "
    "Respondé en 40 palabras o menos. Empezá por la respuesta, sin preámbulos. "
    "Nada de markdown, listas ni emojis."
)

PREGUNTAS = [
    "¿Cuánto mide el Aconcagua?",
    "Explicame en criollo qué es un agujero negro.",
    "¿Por qué el cielo es azul?",
    "Contame un dato curioso sobre los volcanes.",
    "¿Cuántos días tiene febrero en año bisiesto?",
    "¿Quién escribió Rayuela?",
    "¿Cómo se hace un buen asado?",
    "¿Qué diferencia hay entre corriente alterna y continua?",
    "¿Cuál es la capital de Australia?",
    "Recomendame una película de ciencia ficción.",
    "¿Cuánto tarda la luz del sol en llegar a la Tierra?",
    "¿Qué es la inteligencia artificial generativa?",
    "¿Cuándo se inventó la imprenta?",
    "Dame una idea para la cena.",
]


def consultar(pregunta):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{MODELO}:generateContent"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": pregunta}]}],
        "generationConfig": {"temperature": 0.7, "maxOutputTokens": 200},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=25) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)[:60]
    seg = time.perf_counter() - t0
    try:
        return cuerpo["candidates"][0]["content"]["parts"][0]["text"].strip(), seg, ""
    except (KeyError, IndexError):
        return None, seg, "respuesta sin texto"


def main():
    if not API_KEY:
        print("FALTA GEMINI_API_KEY")
        return

    ritmo = 60.0 / PAUSA
    print(f"Modelo: {MODELO}")
    print(f"Ritmo simulado: 1 pregunta cada {PAUSA:.0f}s  (~{ritmo:.1f} por minuto)")
    print(f"{LLAMADAS} llamadas. Presupuesto: {PRESUPUESTO}s")
    print(f"Duracion estimada: ~{LLAMADAS * PAUSA / 60:.0f} minutos\n")

    tiempos, fallos = [], 0
    for i in range(LLAMADAS):
        pregunta = PREGUNTAS[i % len(PREGUNTAS)]
        texto, seg, err = consultar(pregunta)
        if texto is None:
            fallos += 1
            print(f"[{i+1:2}/{LLAMADAS}] {seg:6.2f}s  FALLO  {err}")
        else:
            tiempos.append(seg)
            marca = "ok   " if seg <= PRESUPUESTO else "LENTO"
            print(f"[{i+1:2}/{LLAMADAS}] {seg:6.2f}s  {marca}  {texto[:70]}")
        if i < LLAMADAS - 1:
            time.sleep(PAUSA)

    print("\n" + "=" * 64)
    if not tiempos:
        print("Sin muestras validas.")
        return
    t = sorted(tiempos)
    idx90 = min(int(len(t) * 0.9), len(t) - 1)
    sobre = sum(1 for x in t if x > PRESUPUESTO)
    riesgo = (sobre + fallos) / LLAMADAS * 100
    print(f"  muestras validas : {len(t)}/{LLAMADAS}   fallos: {fallos}")
    print(f"  mejor            : {t[0]:6.2f}s")
    print(f"  mediana (p50)    : {statistics.median(t):6.2f}s")
    print(f"  p90              : {t[idx90]:6.2f}s")
    print(f"  PEOR             : {t[-1]:6.2f}s")
    print(f"  >>> RIESGO DE CORTE: {riesgo:.0f}%")
    print("=" * 64)
    if riesgo == 0:
        print("\nVEREDICTO: sirve. Al ritmo real no hay cortes.")
    elif riesgo <= 10:
        print("\nVEREDICTO: aceptable, pero conviene una defensa para el caso lento.")
    else:
        print("\nVEREDICTO: no alcanza. Hace falta cambiar de proveedor o de diseno.")


if __name__ == "__main__":
    main()
