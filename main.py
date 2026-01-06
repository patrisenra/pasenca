from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from typing import Dict, Any
import re
import time

app = FastAPI()

# IMPORTANTÍSIMO: este token tiene que coincidir con el que pongamos en Meta cuando toque.
VERIFY_TOKEN = "pasenca_verify_2026"

# ----------------------------
# Memoria simple (temporal)
# ----------------------------
# Guardamos el estado por "user_id" (en WhatsApp será el número). De momento lo simulamos.
SESSIONS: Dict[str, Dict[str, Any]] = {}
LEADS: list[dict[str, Any]] = []  # aquí guardaremos leads para estadísticas (luego lo conectamos a Sheets/Walcu)


# ----------------------------
# Textos del bot (Pasenca)
# ----------------------------
WELCOME_MSG = (
    "👋 Hola, soy Pasenca, el asistente automático de Senrasport.\n\n"
    "Te ayudo con:\n"
    "1️⃣ Cita taller / ITV\n"
    "2️⃣ Información sobre coches en venta\n"
    "3️⃣ Horarios y ubicación\n"
    "4️⃣ Hablar con una persona\n\n"
    "Responde con 1, 2, 3 o 4 (o escríbeme lo que necesitas)."
)

HUMANO_MSG = (
    "Perfecto 👍 Te atiende un compañero en cuanto esté disponible.\n"
    "Si quieres, dime en una frase qué necesitas y así te damos prioridad."
)

INFO_MSG = (
    "📍 Senrasport\n"
    "- Ubicación: (pendiente de poner enlace Google Maps)\n"
    "- Horario: (pendiente)\n"
    "- Teléfono: (pendiente)\n\n"
    "¿Te ayudo con *taller/ITV* o *coches*?"
)

NO_ENTIENDO = (
    "Perdona 🙏 ¿Es para *taller/ITV*, *coches* o *otra consulta*?\n"
    "Responde: taller / coches / otra"
)

TALLER_PRESUPUESTO = (
    "Para darte un presupuesto exacto, lo mejor es que te atienda un compañero 👍\n"
    "Te paso con una persona ahora mismo."
)

# Taller (cita)
TALLER_1 = "Perfecto 👍 Para pedir cita, dime por favor:\n¿la matrícula del vehículo?"
TALLER_2 = "Gracias.\n¿Te vendría mejor por la *mañana* o por la *tarde*? (mañana / tarde / me da igual)"
TALLER_3 = "Genial.\n¿Para qué día aproximadamente la necesitas? (esta semana, la semana que viene, un día concreto…)"
TALLER_URG = "Antes de continuar, dime por favor:\n¿Es una *urgencia*? (sí / no)"
TALLER_4 = "Perfecto. Para confirmarte la cita, dime un *nombre* y un *teléfono* de contacto.\n(Si es el mismo desde el que escribes, pon: el mismo)"
TALLER_CONFIRM = (
    "✅ Listo, gracias.\n"
    "Hemos recibido tu solicitud de *cita de taller* con estos datos:\n\n"
    "- Matrícula: {matricula}\n"
    "- Preferencia: {pref}\n"
    "- Día aproximado: {dia}\n"
    "- Urgente: {urgente}\n\n"
    "Un compañero de Senrasport te contactará para confirmar disponibilidad."
)

# Coches (coche visto / disponibilidad + estadística)
COCHE_1 = "Claro 👍 Para ayudarte mejor:\n¿De qué coche se trata? (marca, modelo o enlace/foto si lo tienes)"
COCHE_2 = (
    "Gracias.\n"
    "👉 ¿Dónde viste el coche anunciado?\n"
    "- Instagram\n- Facebook\n- Web\n- Concesionario\n- Recomendación\n- Otro"
)
COCHE_3 = (
    "Perfecto. Y para conocernos mejor:\n"
    "👉 ¿Cómo llegaste a Senrasport?\n"
    "- Redes sociales\n- Google\n- Recomendación\n- Cliente habitual\n- Otro"
)
COCHE_4 = "Genial 👍 Voy a comprobar la disponibilidad y un asesor te da toda la información por aquí."


# ----------------------------
# Utilidades
# ----------------------------
def _get_session(user_id: str) -> Dict[str, Any]:
    if user_id not in SESSIONS:
        SESSIONS[user_id] = {"state": "START", "data": {}, "updated_at": time.time()}
    return SESSIONS[user_id]


def _set_state(user_id: str, state: str) -> None:
    sess = _get_session(user_id)
    sess["state"] = state
    sess["updated_at"] = time.time()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


def _is_yes(text: str) -> bool:
    t = _normalize(text)
    return t in ("si", "sí", "s", "yes")


def _is_no(text: str) -> bool:
    t = _normalize(text)
    return t in ("no", "n")


def detect_intent(text: str) -> str:
    t = _normalize(text)

    # humano
    if any(k in t for k in ["persona", "humano", "asesor", "llamar", "llámame", "urgente"]):
        return "HUMANO"

    # presupuesto / precio (taller)
    if any(k in t for k in ["presupuesto", "precio", "cuánto cuesta", "cuanto cuesta", "cuanto vale", "coste"]):
        return "PRESUPUESTO"

    # info
    if any(k in t for k in ["horario", "dirección", "direccion", "ubicación", "ubicacion", "donde estais", "teléfono", "telefono", "contacto"]):
        return "INFO"

    # taller (cita)
    if any(k in t for k in ["cita", "revisión", "revision", "cambio de aceite", "aceite", "itv", "pre-itv", "avería", "averia", "ruido", "frenos", "mantenimiento"]):
        return "TALLER"

    # coches
    if any(k in t for k in ["coche", "coches", "anuncio", "vi un coche", "más información", "mas informacion", "disponible", "instagram", "facebook", "web"]):
        return "COCHES"

    # números del menú
    if t in ("1", "2", "3", "4"):
        return {"1": "TALLER", "2": "COCHES", "3": "INFO", "4": "HUMANO"}[t]

    return "UNKNOWN"


# ----------------------------
# Motor del bot (por estados)
# ----------------------------
def bot_reply(user_id: str, text: str) -> str:
    sess = _get_session(user_id)
    state = sess["state"]
    data = sess["data"]
    t = _normalize(text)

    # Si el usuario pide humano en cualquier momento:
    if detect_intent(t) == "HUMANO":
        _set_state(user_id, "HUMANO")
        return HUMANO_MSG

    # Si pide presupuesto/precio -> humano
    if detect_intent(t) == "PRESUPUESTO":
        _set_state(user_id, "HUMANO")
        return TALLER_PRESUPUESTO

    # Estado START (decidir ruta)
    if state == "START":
        intent = detect_intent(t)
        if intent == "TALLER":
            _set_state(user_id, "TALLER_MATRICULA")
            return TALLER_1
        if intent == "COCHES":
            _set_state(user_id, "COCHE_IDENTIFICAR")
            return COCHE_1
        if intent == "INFO":
            return INFO_MSG
        if intent == "UNKNOWN":
            return WELCOME_MSG  # si no entiende, vuelve a menú

        return WELCOME_MSG

    # ---------- TALLER FLOW ----------
    if state == "TALLER_MATRICULA":
        if len(t) < 5:
            return "¿Me pasas la matrícula, por favor? (ej: 1234ABC)"
        data["matricula"] = text.strip().upper()
        _set_state(user_id, "TALLER_HORARIO")
        return TALLER_2

    if state == "TALLER_HORARIO":
        if "mañ" in t or "man" in t:
            data["pref"] = "mañana"
        elif "tard" in t:
            data["pref"] = "tarde"
        elif "igual" in t or "da igual" in t:
            data["pref"] = "me da igual"
        else:
            return "Solo para organizar: ¿*mañana* o *tarde*? (o *me da igual*)"
        _set_state(user_id, "TALLER_DIA")
        return TALLER_3

    if state == "TALLER_DIA":
        if len(t) < 3:
            return "¿Para qué día aproximadamente? (ej: esta semana / viernes / la semana que viene)"
        data["dia"] = text.strip()
        _set_state(user_id, "TALLER_URGENTE")
        return TALLER_URG

    if state == "TALLER_URGENTE":
        if _is_yes(t):
            data["urgente"] = "sí"
        elif _is_no(t):
            data["urgente"] = "no"
        else:
            return "¿Es una urgencia? Responde *sí* o *no*."
        _set_state(user_id, "TALLER_CONTACTO")
        return TALLER_4

    if state == "TALLER_CONTACTO":
        # Aceptamos "Nombre, teléfono" o "el mismo"
        if len(t) < 2:
            return "Dime por favor *nombre* y *teléfono* (o escribe: *el mismo*)."
        if "el mismo" in t or "mismo" == t:
            data["contacto"] = "mismo número"
        else:
            data["contacto"] = text.strip()

        # Guardar lead de taller
        LEADS.append({
            "tipo": "taller",
            "user_id": user_id,
            "matricula": data.get("matricula"),
            "pref": data.get("pref"),
            "dia": data.get("dia"),
            "urgente": data.get("urgente"),
            "contacto": data.get("contacto"),
            "timestamp": time.time(),
        })

        _set_state(user_id, "END")
        return TALLER_CONFIRM.format(
            matricula=data.get("matricula", "-"),
            pref=data.get("pref", "-"),
            dia=data.get("dia", "-"),
            urgente=data.get("urgente", "-"),
        )

    # ---------- COCHES FLOW ----------
    if state == "COCHE_IDENTIFICAR":
        if len(t) < 3:
            return "¿De qué coche se trata? (marca/modelo o enlace/foto)"
        data["coche_interes"] = text.strip()
        _set_state(user_id, "COCHE_ORIGEN_ANUNCIO")
        return COCHE_2

    if state == "COCHE_ORIGEN_ANUNCIO":
        data["origen_anuncio"] = text.strip()
        _set_state(user_id, "COCHE_ORIGEN_CLIENTE")
        return COCHE_3

    if state == "COCHE_ORIGEN_CLIENTE":
        data["origen_cliente"] = text.strip()

        # Guardar lead de coche
        LEADS.append({
            "tipo": "coche",
            "user_id": user_id,
            "coche_interes": data.get("coche_interes"),
            "origen_anuncio": data.get("origen_anuncio"),
            "origen_cliente": data.get("origen_cliente"),
            "timestamp": time.time(),
        })

        _set_state(user_id, "HUMANO")  # en coches pasamos a humano tras capturar datos
        return COCHE_4 + "\n\n" + HUMANO_MSG

    # INFO
    if state == "INFO_FLOW":
        return INFO_MSG

    # HUMANO
    if state == "HUMANO":
        return "👍 Entendido. Te atiende un compañero."

    # END
    if state == "END":
        # si vuelve a escribir, reabrimos
        _set_state(user_id, "START")
        return WELCOME_MSG

    # fallback
    _set_state(user_id, "START")
    return NO_ENTIENDO


# ----------------------------
# Webhook Meta (verificación)
# ----------------------------
@app.get("/webhook", response_class=PlainTextResponse)
async def verify_webhook(request: Request):
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN and challenge:
        return challenge

    return PlainTextResponse("Verification failed", status_code=403)


# ----------------------------
# Webhook Meta (mensajes)
# ----------------------------
@app.post("/webhook")
async def receive_webhook(request: Request):
    """
    Aún no estamos conectados a WhatsApp Cloud API (no hay SIM/token),
    pero dejamos el cerebro listo.
    """
    payload = await request.json()

    # Intentamos extraer texto si viene algo parecido a WhatsApp Cloud API
    # Si no, lo dejamos sin romper.
    user_id = "demo_user"
    text = ""

    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if messages:
            msg = messages[0]
            user_id = msg.get("from", "demo_user")
            text = (msg.get("text", {}) or {}).get("body", "") or ""
    except Exception:
        pass

    if text:
        reply = bot_reply(user_id=user_id, text=text)
        # Aún no enviamos a WhatsApp (falta token), pero devolvemos la respuesta para debugging.
        return {"status": "ok", "simulated_reply": reply}

    return {"status": "ok"}


# ----------------------------
# Endpoint de simulación (para probar sin WhatsApp)
# ----------------------------
@app.post("/simulate")
async def simulate(request: Request):
    """
    Para probar el bot sin WhatsApp:
    POST /simulate  {"user_id":"pablo","text":"quiero cita"}
    """
    body = await request.json()
    user_id = (body.get("user_id") or "demo_user").strip()
    text = (body.get("text") or "").strip()
    reply = bot_reply(user_id=user_id, text=text)
    return {"reply": reply, "state": _get_session(user_id)["state"], "data": _get_session(user_id)["data"]}


@app.get("/")
async def health():
    return {"status": "running", "bot": "pasenca"}
