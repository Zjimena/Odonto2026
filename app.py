import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import datetime
import json
import firebase_admin
from firebase_admin import credentials, firestore
import hashlib

st.set_page_config(page_title="PaperMinds IA", page_icon="🦷", layout="centered")

st.markdown("""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Inter:wght@400;600&display=swap');
    
    .main-title {
        font-family: 'Playfair Display', serif;
        font-size: 3.2rem;
        color: #00D1FF;
        text-align: center;
        margin-bottom: 0px;
        padding-top: 0px;
    }
    
    .subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1.1rem;
        text-align: center;
        opacity: 0.8;
        margin-bottom: 35px;
    }

    .stChatMessage {
        border-radius: 15px;
        margin-bottom: 10px;
    }
    
    button[kind="primary"] {
        background-color: #00D1FF !important;
        border: none !important;
        color: white !important;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. SECCIÓN DE SEGURIDAD (CONEXIONES)
# ==========================================

try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    FIREBASE_CREDENTIALS = st.secrets["FIREBASE_CREDENTIALS"]
except KeyError:
    st.error("Faltan las claves de API en los 'secrets' de Streamlit.")
    st.stop()

if not firebase_admin._apps:
    try:
        cred_dict = json.loads(FIREBASE_CREDENTIALS)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Error crítico al conectar con Firebase: {e}")
        st.stop()
    
db = firestore.client()

genai.configure(api_key=GOOGLE_API_KEY)
modelo = genai.GenerativeModel('gemini-3-flash-preview')

# ==========================================
# 3. FUNCIONES DE SOPORTE
# ==========================================

def generar_user_id(nombre_usuario: str) -> str:
    """Genera un ID único y anónimo basado en el nombre del usuario."""
    return hashlib.sha256(nombre_usuario.strip().lower().encode()).hexdigest()[:16]

def cargar_historial_usuario(user_id: str) -> list:
    """Carga el historial de conversaciones previas del usuario desde Firebase."""
    try:
        docs = (
            db.collection("chats_paperminds")
            .where("user_id", "==", user_id)
            .order_by("fecha_hora")
            .limit(20)  # Últimas 20 interacciones para no saturar el contexto
            .stream()
        )
        historial = []
        for doc in docs:
            data = doc.to_dict()
            historial.append({"role": "user",      "contenido": data.get("input_usuario", "")})
            historial.append({"role": "assistant", "contenido": data.get("output_ia", "")})
        return historial
    except Exception as e:
        print(f"Error al cargar historial de Firebase: {e}")
        return []

def guardar_log_interaccion(user_id: str, nombre_usuario: str, pregunta: str, respuesta: str):
    """Guarda el historial de chat directamente en Google Firebase Cloud."""
    log = {
        "fecha_hora": datetime.datetime.now().isoformat(),
        "user_id": user_id,
        "nombre_usuario": nombre_usuario,
        "input_usuario": pregunta,
        "output_ia": respuesta,
        "proyecto": "PaperMinds PILOTO"
    }
    try:
        db.collection("chats_paperminds").add(log)
    except Exception as e:
        print(f"Error al guardar log en Firebase: {e}")

def contar_interacciones_previas(user_id: str) -> int:
    """Cuenta cuántas veces el usuario ha interactuado previamente."""
    try:
        docs = (
            db.collection("chats_paperminds")
            .where("user_id", "==", user_id)
            .stream()
        )
        return sum(1 for _ in docs)
    except Exception:
        return 0

@st.cache_data
def cargar_base_conocimiento():
    """Carga y extrae texto del PDF adjunto."""
    texto = ""
    nombre_pdf = "Guia_dental.pdf"
    try:
        lector = PdfReader(nombre_pdf)
        for pagina in lector.pages:
            texto += pagina.extract_text() + "\n"
        return texto
    except FileNotFoundError:
        st.error(f"No se encontró el archivo {nombre_pdf}. La IA no tendrá contexto.")
        return "ADVERTENCIA: No se encontró el archivo Guia_dental.pdf."
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return ""

def construir_historial_para_prompt(mensajes: list) -> str:
    """Convierte el historial de mensajes en texto para incluir en el prompt."""
    if not mensajes:
        return "Sin conversaciones previas en esta sesión."
    lineas = []
    for msj in mensajes[-10:]:  # Solo últimos 10 mensajes para no saturar
        rol = "Alumno" if msj["role"] == "user" else "PaperMinds"
        contenido = msj.get("contenido") or msj.get("content", "")
        lineas.append(f"{rol}: {contenido}")
    return "\n".join(lineas)

# ==========================================
# 4. INTERFAZ PRINCIPAL
# ==========================================

st.markdown('<h1 class="main-title">🦷 PaperMinds</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Asistente experto en metodología e investigación odontológica</p>', unsafe_allow_html=True)

st.info("⚠️ Por protocolo de privacidad, no ingrese datos reales ni nombres de pacientes.")

# --- IDENTIFICACIÓN DEL USUARIO ---
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.nombre_usuario = None
    st.session_state.es_usuario_recurrente = False
    st.session_state.mensajes_chat = []
    st.session_state.historial_cargado = False

# Formulario de identificación (solo se muestra si no hay usuario activo)
if st.session_state.user_id is None:
    with st.form("identificacion_usuario"):
        st.markdown("**¿Cómo te llamas?** (Solo tu nombre o apodo, sin apellidos)")
        nombre_input = st.text_input("Nombre o apodo:", placeholder="Ej: Carlos, Dra. López, Estudiante5...")
        submitted = st.form_submit_button("Entrar a PaperMinds")
        
        if submitted and nombre_input.strip():
            user_id = generar_user_id(nombre_input)
            interacciones_previas = contar_interacciones_previas(user_id)
            
            st.session_state.user_id = user_id
            st.session_state.nombre_usuario = nombre_input.strip()
            st.session_state.es_usuario_recurrente = interacciones_previas > 0
            st.session_state.interacciones_previas = interacciones_previas
            
            # Cargar historial previo desde Firebase
            if interacciones_previas > 0:
                historial_firebase = cargar_historial_usuario(user_id)
                st.session_state.mensajes_chat = historial_firebase
            
            st.session_state.historial_cargado = True
            st.rerun()
    st.stop()

# --- APP PRINCIPAL (usuario identificado) ---

# Mostrar bienvenida personalizada una sola vez
if st.session_state.get("mostrar_bienvenida", True):
    if st.session_state.es_usuario_recurrente:
        n = st.session_state.get("interacciones_previas", 0)
        st.success(f"👋 Bienvenido de vuelta, **{st.session_state.nombre_usuario}**. Tienes {n} consulta(s) previas. Tu historial ha sido cargado.")
    else:
        st.success(f"👋 Bienvenido a PaperMinds, **{st.session_state.nombre_usuario}**. ¿En qué puedo ayudarte hoy?")
    st.session_state.mostrar_bienvenida = False

# Cargar el PDF en memoria (una sola vez)
contexto_clinico = cargar_base_conocimiento()

# Mostrar historial de chat
for msj in st.session_state.mensajes_chat:
    avatar = "👨‍⚕️" if msj["role"] == "user" else "🤖"
    with st.chat_message(msj["role"], avatar=avatar):
        contenido = msj.get("contenido") or msj.get("content", "")
        st.markdown(contenido)

# Caja de entrada de texto
pregunta_usuario = st.chat_input("Ej: ¿Cómo estructurar un caso clínico?")

if pregunta_usuario:
    # 1. Mostrar y guardar pregunta del usuario
    with st.chat_message("user", avatar="👨‍⚕️"):
        st.markdown(pregunta_usuario)
    st.session_state.mensajes_chat.append({"role": "user", "contenido": pregunta_usuario})

    # 2. Construir historial para el prompt (contexto conversacional)
    historial_prompt = construir_historial_para_prompt(st.session_state.mensajes_chat[:-1])
    es_recurrente = st.session_state.es_usuario_recurrente
    nombre = st.session_state.nombre_usuario

    # 3. Construir el Prompt con historial y detección de usuario recurrente
    prompt_final = f"""
Eres 'PaperMinds', Asistente Especializado en Investigación Odontológica.

--- IDENTIDAD DEL USUARIO ---
Nombre: {nombre}
¿Usuario recurrente (ya ha usado PaperMinds antes)?: {"SÍ — NO lo saludes de nuevo, no uses frases de bienvenida" if es_recurrente else "NO — Es su primera sesión, pero sé breve"}

--- TONO Y ESTILO DE RESPUESTA (OBLIGATORIO) ---
- Sé DIRECTO y CONCISO. Elimina cualquier relleno o verborrea.
- Usa lenguaje profesional, clínico y preciso.
- NUNCA repitas lo que el alumno ya dijo antes de responder.
- NUNCA uses frases genéricas como "¡Claro!", "¡Por supuesto!", "¡Excelente pregunta!".
- Si el usuario es recurrente, omite cualquier saludo o introducción. Ve directo al punto.
- Cierra con UNA pregunta de seguimiento breve solo si aporta valor real.

--- REGLA CRÍTICA: MANEJO DE AMBIGÜEDAD (PRIORIDAD MÁXIMA) ---
ANTES de responder cualquier pregunta, analiza si el alumno especificó claramente el contexto.

SITUACIONES QUE REQUIEREN PREGUNTAR PRIMERO:
- Menciona "cartel" sin especificar el tipo → Pregunta: "¿Te refieres al cartel AMIC, Cancún o el cartel general?"
- Menciona "guía" o "formato" sin aclarar cuál → Pregunta por el tipo específico.
- La pregunta es aplicable a múltiples categorías del documento → Lista las opciones disponibles y pregunta cuál aplica.

REGLA: Si hay ambigüedad, DETENTE. Haz UNA sola pregunta de clarificación, breve y directa. NO asumas, NO respondas con la opción más común o popular. Espera la respuesta del alumno antes de continuar.

Excepción: Si el alumno ya aclaró el contexto en el historial de conversación, úsalo y no preguntes de nuevo.

--- MODOS DE OPERACIÓN (Elige el adecuado según la entrada) ---

🔴 MODO 1: CONSULTA PUNTUAL (Ej: ¿Qué es CARE?, ¿Qué ISO uso?, ¿Cuántas palabras permite X?)
- Aplica SOLO cuando el contexto es específico y claro.
- Formato: respuesta directa en máximo 4 viñetas + 1 oración de cierre explicando el 'por qué'.
- Sin introducciones, sin repetir la pregunta.

🔵 MODO 2: ORDENADOR DE CASOS (Ej: "Estructura estas notas", "Ordena este caso")
- Actúa como Editor Médico. Ignora la regla de brevedad.
- Redacta el texto completo usando los 13 ítems de la Guía CARE o SCARE según corresponda.
- Lenguaje clínico profesional, títulos claros.
- Marca con [FALTA INFORMACIÓN] cualquier dato vital omitido (anamnesis, evolución, etc.).

🟢 MODO 3: AUDITOR (Ej: "Revisa este título", "¿Cumple este resumen los requisitos?")
- Veredicto al inicio: ✅ CUMPLE o ❌ NO CUMPLE — sin excepción.
- Señala exactamente qué incumple y por qué, citando la regla correspondiente.
- Si no cumple: ofrece 2 versiones corregidas numeradas.

🟡 MODO 4: CITACIÓN (Ej: "Pasa esto a Vancouver", "Formatea esta referencia")
- Devuelve ÚNICAMENTE la referencia formateada. Cero explicaciones, cero comentarios.

🟠 MODO 5: COMPARADOR (Ej: "¿En qué se diferencia AMIC de Cancún?", "Compara los formatos")
- Usa una tabla comparativa cuando haya 2 o más elementos con atributos comparables.
- Columnas: categoría | opción A | opción B (| opción C si aplica).
- Una línea de conclusión al final indicando cuándo usar cada uno.

--- HISTORIAL DE CONVERSACIÓN (contexto de esta sesión) ---
{historial_prompt}

--- BIBLIOTECA DE CONSULTA ---
{contexto_clinico[:60000]}

--- NUEVA PREGUNTA DEL ALUMNO ---
{pregunta_usuario}
"""

    # 4. Generar respuesta de la IA
    with st.chat_message("assistant", avatar="🤖"):
        with st.spinner("Consultando la guía dental..."):
            try:
                safety_settings = {
                    "HATE": "BLOCK_NONE",
                    "HARASSMENT": "BLOCK_NONE",
                    "SEXUAL": "BLOCK_NONE",
                    "DANGEROUS": "BLOCK_NONE"
                }
                
                response = modelo.generate_content(prompt_final, safety_settings=safety_settings)
                respuesta_ia = response.text
                
                st.markdown(respuesta_ia)
                st.session_state.mensajes_chat.append({"role": "assistant", "contenido": respuesta_ia})
                
                # 5. Guardar log en Firebase con user_id
                guardar_log_interaccion(
                    st.session_state.user_id,
                    st.session_state.nombre_usuario,
                    pregunta_usuario,
                    respuesta_ia
                )
                
                # Marcar como usuario recurrente para la próxima pregunta en esta sesión
                st.session_state.es_usuario_recurrente = True
                
            except Exception as e:
                st.warning("⏳ Muchos estudiantes están consultando al mismo tiempo. Por favor, espera 20 segundos y vuelve a enviar tu pregunta.")
                
                # 4. Guardar log en Firebase (en segundo plano)
                guardar_log_interaccion(pregunta_usuario, respuesta_ia)
                
            except Exception as e:
                # Mensaje amable en caso de Error 429 (saturación por minuto)
                st.warning("⏳ Muchos estudiantes están consultando al mismo tiempo. Por favor, espera 20 segundos y vuelve a enviar tu pregunta.")
                # st.error(f"Detalle técnico del error: {e}") # Descomentar solo para mantenimiento
