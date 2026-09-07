"""
Diagnóstico: encontrar la sintaxis correcta para bajar el thinking de Gemini 3.x.

La doc oficial y las fuentes secundarias discrepan en el nombre del parámetro
(`thinkingLevel` vs `thinkingBudget`, anidado o no). En vez de deducir, se
prueban las variantes y se mira cuál no devuelve 400.

Segunda cosa que mide: si `maxOutputTokens` alcanza. En los modelos 3.x el
razonamiento consume del mismo presupuesto, así que 200 tokens pueden irse
enteros en pensar y devolver una respuesta cortada a la mitad.

Uso:  GEMINI_API_KEY=... python test_thinking.py
"""

import json
import os
import time
import urllib.error
import urllib.request

API_KEY = os.environ.get("GEMINI_API_KEY", "")
PREGUNTA = "¿Por qué el cielo es azul?"
SYSTEM = (
    "Respondé en 50 palabras o menos, en español rioplatense. "
    "Empezá por la respuesta, sin preámbulos. Nada de markdown ni emojis."
)

# (etiqueta, generationConfig a probar)
VARIANTES = [
    ("baseline 200 tok", {"maxOutputTokens": 200}),
    ("baseline 800 tok", {"maxOutputTokens": 800}),
    (
        "thinkingConfig.thinkingLevel=low",
        {"maxOutputTokens": 800, "thinkingConfig": {"thinkingLevel": "low"}},
    ),
    (
        "thinkingConfig.thinkingLevel=minimal",
        {"maxOutputTokens": 800, "thinkingConfig": {"thinkingLevel": "minimal"}},
    ),
    (
        "thinkingConfig.thinkingBudget=0",
        {"maxOutputTokens": 800, "thinkingConfig": {"thinkingBudget": 0}},
    ),
    (
        "thinkingLevel plano=low",
        {"maxOutputTokens": 800, "thinkingLevel": "low"},
    ),
]

MODELOS = ["gemini-3.5-flash-lite", "gemini-3.5-flash"]


def probar(modelo, gen_config):
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        f"{modelo}:generateContent"
    )
    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": PREGUNTA}]}],
        "generationConfig": gen_config,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": API_KEY},
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            cuerpo = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", "replace")
        # El mensaje de error dice si el campo no existe o si el valor es invalido.
        try:
            msg = json.loads(msg)["error"]["message"][:150]
        except Exception:
            msg = msg[:150]
        return f"HTTP{e.code}", msg, time.perf_counter() - t0, None
    except Exception as e:
        return "TIMEOUT", str(e)[:80], time.perf_counter() - t0, None

    seg = time.perf_counter() - t0
    uso = cuerpo.get("usageMetadata", {})
    pensados = uso.get("thoughtsTokenCount", 0)
    try:
        texto = cuerpo["candidates"][0]["content"]["parts"][0]["text"].strip()
        return "OK", texto, seg, pensados
    except (KeyError, IndexError):
        fin = cuerpo.get("candidates", [{}])[0].get("finishReason", "?")
        return "VACIO", f"finishReason={fin}", seg, pensados


def main():
    if not API_KEY:
        print("FALTA GEMINI_API_KEY")
        return

    for modelo in MODELOS:
        print("=" * 74)
        print(modelo)
        print("=" * 74)
        for etiqueta, cfg in VARIANTES:
            estado, detalle, seg, pensados = probar(modelo, cfg)
            tok = f"pensó {pensados}tok" if pensados else ""
            print(f"\n[{estado:7}] {seg:5.2f}s  {etiqueta:38} {tok}")
            print(f"          {detalle[:150]}")
        print()


if __name__ == "__main__":
    main()
