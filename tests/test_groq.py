"""
Mide Groq con la misma vara que se midió Gemini.

Gemini free tier dio 36 % de riesgo de corte por prioridad de cola. Groq corre
en hardware LPU pensado para latencia baja y consistente — que es exactamente
el problema. Esto lo comprueba en vez de suponerlo.

Primero lista los modelos disponibles en vivo (no de memoria) y recién después
mide los candidatos rápidos, al ritmo real de una conversación.

Uso:  GROQ_API_KEY=... python test_groq.py
"""

import io
import json
import os
import statistics
import sys
import time
import urllib.error
import urllib.request

# La consola de Windows es cp1252 y revienta con acentos y espacios finos.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

API_KEY = os.environ.get("GROQ_API_KEY", "")
BASE = "https://api.groq.com/openai/v1"

# Candidatos por velocidad declarada. Se filtran contra lo que exista de verdad.
CANDIDATOS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
]

PAUSA = 12.0
PRESUPUESTO = 6.0

SYSTEM = (
    "Sos un asistente por voz en un parlante Alexa. Español rioplatense (vos, no tú). "
    "Respondé en 40 palabras o menos. Empezá por la respuesta, sin preámbulos. "
    "Nada de markdown, listas ni emojis."
)

PREGUNTAS = [
    "¿Cuánto mide el Aconcagua?",
    "Explicame en criollo qué es un agujero negro.",
    "¿Por qué el cielo es azul?",
    "Contame un dato curioso sobre los volcanes.",
    "¿Quién escribió Rayuela?",
    "¿Qué diferencia hay entre corriente alterna y continua?",
]


def _req(url, data=None):
    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode("utf-8") if data else None,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
            # Sin esto, Cloudflare devuelve 403 "error code: 1010": bloquea el
            # User-Agent por defecto de urllib (Python-urllib/3.x). Verificado.
            "User-Agent": "alexa-ia/1.0",
        },
        method="POST" if data else "GET",
    )
    with urllib.request.urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode("utf-8"))


def listar_modelos():
    try:
        datos = _req(f"{BASE}/models")
    except urllib.error.HTTPError as e:
        print(f"No se pudo listar modelos: HTTP {e.code}")
        print(e.read().decode("utf-8", "replace")[:300])
        return []
    except Exception as e:
        print(f"No se pudo listar modelos: {e}")
        return []
    return sorted(m["id"] for m in datos.get("data", []))


def consultar(modelo, pregunta):
    payload = {
        "model": modelo,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": pregunta},
        ],
        "temperature": 0.7,
        # 1000 y no 200: el razonamiento consume del mismo presupuesto y con
        # 200 el content vuelve VACIO con finish_reason=length. Verificado.
        "max_tokens": 1000,
        # La palanca que baja el razonamiento al minimo: 75 tokens en vez de 323.
        # Solo acepta low / medium / high — "none" da HTTP 400.
        "reasoning_effort": "low",
        # Saca el campo `reasoning` de la respuesta: no se usa y ocupa.
        "reasoning_format": "hidden",
    }
    t0 = time.perf_counter()
    try:
        cuerpo = _req(f"{BASE}/chat/completions", payload)
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", "replace")[:120]
        return None, time.perf_counter() - t0, f"HTTP{e.code} {detalle}"
    except Exception as e:
        return None, time.perf_counter() - t0, str(e)[:60]
    seg = time.perf_counter() - t0
    try:
        return cuerpo["choices"][0]["message"]["content"].strip(), seg, ""
    except (KeyError, IndexError):
        return None, seg, "respuesta sin texto"


def medir(modelo):
    print(f"\n{'=' * 68}\n{modelo}\n{'=' * 68}")
    tiempos, fallos = [], 0
    for i, pregunta in enumerate(PREGUNTAS):
        texto, seg, err = consultar(modelo, pregunta)
        if texto is None:
            fallos += 1
            print(f"  [{i+1}/{len(PREGUNTAS)}] {seg:6.2f}s  FALLO  {err}")
        else:
            tiempos.append(seg)
            marca = "ok   " if seg <= PRESUPUESTO else "LENTO"
            print(f"  [{i+1}/{len(PREGUNTAS)}] {seg:6.2f}s  {marca}  {texto[:66]}")
        if i < len(PREGUNTAS) - 1:
            time.sleep(PAUSA)

    if not tiempos:
        print(f"  -> sin muestras validas ({fallos} fallos)")
        return modelo, None, None, 100.0

    t = sorted(tiempos)
    sobre = sum(1 for x in t if x > PRESUPUESTO)
    riesgo = (sobre + fallos) / len(PREGUNTAS) * 100
    print(f"\n  mediana {statistics.median(t):.2f}s | PEOR {t[-1]:.2f}s | "
          f"fallos {fallos} | RIESGO {riesgo:.0f}%")
    return modelo, statistics.median(t), t[-1], riesgo


def main():
    if not API_KEY:
        print("FALTA GROQ_API_KEY.")
        print("Sacala gratis en https://console.groq.com  (sin tarjeta)")
        return

    print("Modelos disponibles en tu cuenta:")
    disponibles = listar_modelos()
    if not disponibles:
        return
    for m in disponibles:
        marca = " <-- candidato" if m in CANDIDATOS else ""
        print(f"  {m}{marca}")

    a_medir = [m for m in CANDIDATOS if m in disponibles]
    if not a_medir:
        print("\nNinguno de los candidatos existe. Revisar la lista de arriba.")
        return

    print(f"\nMidiendo {len(a_medir)} modelo(s) a 1 pregunta cada {PAUSA:.0f}s")
    print(f"Presupuesto: {PRESUPUESTO}s\n")

    resultados = [medir(m) for m in a_medir]

    print(f"\n{'=' * 68}\nRESUMEN — Groq vs. Gemini free tier\n{'=' * 68}")
    print(f"{'modelo':<32}{'mediana':>10}{'peor':>10}{'riesgo':>10}")
    print(f"{'(Gemini free flash-lite)':<32}{'2.16s':>10}{'19.55s':>10}{'36%':>10}")
    print("-" * 68)
    for modelo, mediana, peor, riesgo in sorted(resultados, key=lambda r: r[3]):
        if mediana is None:
            print(f"{modelo:<32}{'-':>10}{'-':>10}{'NO SIRVE':>10}")
        else:
            print(f"{modelo:<32}{mediana:>9.2f}s{peor:>9.2f}s{riesgo:>9.0f}%")

    mejor = min(resultados, key=lambda r: r[3])
    print()
    if mejor[3] == 0:
        print(f"VEREDICTO: {mejor[0]} no tuvo un solo corte. Es el proveedor.")
    elif mejor[3] <= 10:
        print(f"VEREDICTO: {mejor[0]} es aceptable con la defensa de P-14 encima.")
    else:
        print("VEREDICTO: Groq tampoco alcanza. Toca proveedor pago.")


if __name__ == "__main__":
    main()
