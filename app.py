import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import datetime
import json
import firebase_admin
from firebase_admin import credentials, firestore
import hashlib
from docx import Document as DocxDocument
import io

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
# 3. FUNCIONES DE AUTENTICACIÓN
# ==========================================

def hashear(texto: str) -> str:
    """Devuelve SHA-256 de un texto."""
    return hashlib.sha256(texto.strip().encode()).hexdigest()

def generar_user_id(nombre: str, password: str) -> str:
    """ID único basado en nombre + contraseña.
    Dos alumnos con el mismo nombre pero distinta contraseña obtienen IDs distintos."""
    return hashlib.sha256(f"{nombre.strip().lower()}:{password}".encode()).hexdigest()[:16]

def buscar_cuenta(nombre: str) -> dict | None:
    """Busca si ya existe una cuenta registrada con ese nombre en Firebase."""
    try:
        docs = (
            db.collection("usuarios_paperminds")
            .where("nombre_normalizado", "==", nombre.strip().lower())
            .limit(1)
            .stream()
        )
        for doc in docs:
            return doc.to_dict()
        return None
    except Exception as e:
        print(f"Error al buscar cuenta: {e}")
        return None

def registrar_cuenta(nombre: str, password: str, user_id: str):
    """Crea una nueva cuenta en la colección usuarios_paperminds."""
    try:
        db.collection("usuarios_paperminds").document(user_id).set({
            "nombre_display": nombre.strip(),
            "nombre_normalizado": nombre.strip().lower(),
            "password_hash": hashear(password),
            "user_id": user_id,
            "fecha_registro": datetime.datetime.now().isoformat()
        })
    except Exception as e:
        print(f"Error al registrar cuenta: {e}")

# ==========================================
# 4. FUNCIONES DE SOPORTE
# ==========================================

def cargar_historial_usuario(user_id: str) -> list:
    """Carga el historial de conversaciones previas del usuario desde Firebase."""
    try:
        docs = (
            db.collection("chats_paperminds")
            .where("user_id", "==", user_id)
            .order_by("fecha_hora")
            .limit(20)
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
    nombre_pdf = "Guia_dental.pdf"
    try:
        lector = PdfReader(nombre_pdf)
        return "\n".join(p.extract_text() or "" for p in lector.pages)
    except FileNotFoundError:
        st.error(f"No se encontró el archivo {nombre_pdf}. La IA no tendrá contexto.")
        return "ADVERTENCIA: No se encontró el archivo Guia_dental.pdf."
    except Exception as e:
        st.error(f"Error al leer el PDF: {e}")
        return ""

def extraer_texto_documento(archivo) -> str:
    """Extrae texto plano de un PDF o Word subido por el alumno."""
    nombre = archivo.name.lower()
    try:
        if nombre.endswith(".pdf"):
            lector = PdfReader(archivo)
            return "\n".join(p.extract_text() or "" for p in lector.pages).strip()
        elif nombre.endswith(".docx"):
            doc = DocxDocument(io.BytesIO(archivo.read()))
            return "\n".join(p.text for p in doc.paragraphs if p.text.strip()).strip()
        return ""
    except Exception as e:
        return f"[ERROR al leer el documento: {e}]"

def construir_historial_para_prompt(mensajes: list) -> str:
    """Convierte el historial de mensajes en texto para incluir en el prompt."""
    if not mensajes:
        return "Sin conversaciones previas en esta sesión."
    lineas = []
    for msj in mensajes[-10:]:
        rol = "Alumno" if msj["role"] == "user" else "PaperMinds"
        contenido = msj.get("contenido") or msj.get("content", "")
        lineas.append(f"{rol}: {contenido}")
    return "\n".join(lineas)

# ==========================================
# 5. INTERFAZ PRINCIPAL
# ==========================================

st.markdown('<h1 class="main-title">🦷 PaperMinds</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Asistente experto en metodología e investigación odontológica</p>', unsafe_allow_html=True)

st.info("⚠️ Por protocolo de privacidad, no ingrese datos reales ni nombres de pacientes.")

# --- INICIALIZAR SESSION STATE ---
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.nombre_usuario = None
    st.session_state.es_usuario_recurrente = False
    st.session_state.mensajes_chat = []
    st.session_state.historial_cargado = False
    st.session_state.documento_texto = ""
    st.session_state.documento_nombre = ""
    st.session_state.mostrar_bienvenida = True
    st.session_state.auth_error = ""

# ==========================================
# 6. PANTALLA DE ACCESO (LOGIN / REGISTRO)
# ==========================================

if st.session_state.user_id is None:

    st.markdown("### Accede a tu cuenta")
    tab_login, tab_registro = st.tabs(["🔑 Iniciar sesión", "✏️ Crear cuenta"])

    # --- TAB: INICIAR SESIÓN ---
    with tab_login:
        with st.form("form_login"):
            st.markdown("Ingresa el nombre y contraseña que registraste anteriormente.")
            nombre_login = st.text_input("Nombre o apodo", placeholder="Ej: Carlos")
            pass_login   = st.text_input("Contraseña", type="password")
            btn_login    = st.form_submit_button("Entrar")

        if btn_login:
            if not nombre_login.strip() or not pass_login:
                st.error("Completa ambos campos.")
            else:
                cuenta = buscar_cuenta(nombre_login)
                if cuenta is None:
                    st.error("No existe una cuenta con ese nombre. Usa la pestaña **Crear cuenta**.")
                elif cuenta["password_hash"] != hashear(pass_login):
                    st.error("Contraseña incorrecta. Intenta de nuevo.")
                else:
                    # Credenciales correctas → cargar sesión
                    user_id = cuenta["user_id"]
                    interacciones = contar_interacciones_previas(user_id)
                    st.session_state.user_id             = user_id
                    st.session_state.nombre_usuario      = cuenta["nombre_display"]
                    st.session_state.es_usuario_recurrente = interacciones > 0
                    st.session_state.interacciones_previas = interacciones
                    if interacciones > 0:
                        st.session_state.mensajes_chat = cargar_historial_usuario(user_id)
                    st.session_state.historial_cargado = True
                    st.rerun()

    # --- TAB: CREAR CUENTA ---
    with tab_registro:
        with st.form("form_registro"):
            st.markdown("Elige un nombre o apodo y una contraseña. **Guárdalos**, los necesitarás para volver a entrar.")
            nombre_reg  = st.text_input("Nombre o apodo", placeholder="Ej: Carlos, Dra. López")
            pass_reg    = st.text_input("Contraseña (mínimo 4 caracteres)", type="password")
            pass_reg2   = st.text_input("Confirma tu contraseña", type="password")
            btn_reg     = st.form_submit_button("Crear cuenta")

        if btn_reg:
            if not nombre_reg.strip() or not pass_reg:
                st.error("Completa todos los campos.")
            elif len(pass_reg) < 4:
                st.error("La contraseña debe tener al menos 4 caracteres.")
            elif pass_reg != pass_reg2:
                st.error("Las contraseñas no coinciden.")
            else:
                cuenta_existente = buscar_cuenta(nombre_reg)
                if cuenta_existente is not None:
                    st.error(f"El nombre **{nombre_reg.strip()}** ya está en uso. Elige otro o inicia sesión.")
                else:
                    # Nombre disponible → registrar y entrar
                    user_id = generar_user_id(nombre_reg, pass_reg)
                    registrar_cuenta(nombre_reg, pass_reg, user_id)
                    st.session_state.user_id               = user_id
                    st.session_state.nombre_usuario        = nombre_reg.strip()
                    st.session_state.es_usuario_recurrente = False
                    st.session_state.interacciones_previas = 0
                    st.session_state.historial_cargado     = True
                    st.rerun()

    st.stop()

# ==========================================
# 7. APP PRINCIPAL (usuario autenticado)
# ==========================================

with st.sidebar:
    st.markdown(f"### 👨‍⚕️ Perfil: {st.session_state.nombre_usuario}")
    st.caption("Conectado a la bóveda segura de PaperMinds")
    st.divider()
    
    st.markdown("### 🗂️ Mi Archivo de Consultas")
    st.caption("Revisa todo lo que has trabajado con la IA.")
    
    # Expander para ver el historial completo sin saturar la pantalla
    with st.expander("👀 Ver mi historial completo", expanded=False):
        if not st.session_state.mensajes_chat:
            st.info("Aún no tienes consultas registradas en la nube.")
        else:
            # Recorremos la memoria y la mostramos en formato texto resumido
            for msj in st.session_state.mensajes_chat:
                if msj["role"] == "user":
                    st.markdown(f"🗣️ **Tú:** _{msj.get('contenido', '')}_")
                else:
                    # Acortamos un poco la respuesta de la IA en la vista previa para no saturar
                    respuesta_corta = msj.get('contenido', '')[:150] + "..."
                    st.markdown(f"🤖 **PaperMinds:** {respuesta_corta}")
                    st.divider()
    
    st.divider()
    st.markdown("### 🔄 Control de Sesión")
    # El botón que comentamos antes: Limpia la pantalla para un paciente nuevo
    if st.button("Empezar un Nuevo Caso", use_container_width=True, type="primary"):
        st.session_state.mensajes_chat = []
        st.session_state.documento_texto = ""
        st.session_state.documento_nombre = ""
        st.rerun()
        
# Bienvenida personalizada (una sola vez por sesión)
if st.session_state.mostrar_bienvenida:
    if st.session_state.es_usuario_recurrente:
        n = st.session_state.get("interacciones_previas", 0)
        st.success(f"👋 Bienvenido de vuelta, **{st.session_state.nombre_usuario}**. Tienes {n} consulta(s) previas. Tu historial ha sido cargado.")
    else:
        st.success(f"👋 Cuenta creada. Bienvenido a PaperMinds, **{st.session_state.nombre_usuario}**.")
    st.session_state.mostrar_bienvenida = False

# Cargar el PDF base de conocimiento (una sola vez)
contexto_clinico = cargar_base_conocimiento()

# Mostrar historial de chat
for msj in st.session_state.mensajes_chat:
    avatar = "👨‍⚕️" if msj["role"] == "user" else "🤖"
    with st.chat_message(msj["role"], avatar=avatar):
        contenido = msj.get("contenido") or msj.get("content", "")
        st.markdown(contenido)

# --- SUBIDA DE DOCUMENTO DEL ALUMNO ---
with st.expander("📎 Adjuntar documento para revisión (PDF o Word)", expanded=False):
    st.caption("Sube tu caso clínico, cartel o resumen. Permanece activo durante toda la sesión.")
    archivo_subido = st.file_uploader(
        "Selecciona un archivo",
        type=["pdf", "docx"],
        label_visibility="collapsed",
        key="file_uploader"
    )
    if archivo_subido:
        if archivo_subido.name != st.session_state.documento_nombre:
            texto_extraido = extraer_texto_documento(archivo_subido)
            if texto_extraido.startswith("[ERROR"):
                st.warning(texto_extraido)
            else:
                st.session_state.documento_texto  = texto_extraido
                st.session_state.documento_nombre = archivo_subido.name

    if st.session_state.documento_nombre:
        palabras = len(st.session_state.documento_texto.split())
        col1, col2 = st.columns([4, 1])
        with col1:
            st.success(f"✅ Documento activo: **{st.session_state.documento_nombre}** — {palabras} palabras")
        with col2:
            if st.button("🗑️ Quitar", use_container_width=True):
                st.session_state.documento_texto  = ""
                st.session_state.documento_nombre = ""
                st.rerun()

pregunta_usuario = st.chat_input("Ej: Revisa mi caso clínico / ¿Cumple mi título para AMIC?")

if pregunta_usuario:
    tiene_doc    = bool(st.session_state.documento_texto)
    etiqueta_doc = f" [documento adjunto: {st.session_state.documento_nombre}]" if tiene_doc else ""

    with st.chat_message("user", avatar="👨‍⚕️"):
        st.markdown(pregunta_usuario + etiqueta_doc)
    st.session_state.mensajes_chat.append({"role": "user", "contenido": pregunta_usuario + etiqueta_doc})


    historial_prompt       = construir_historial_para_prompt(st.session_state.mensajes_chat[:-1])
    es_recurrente          = st.session_state.es_usuario_recurrente
    nombre                 = st.session_state.nombre_usuario
    texto_documento_alumno = st.session_state.documento_texto
    contexto_clinico       = cargar_base_conocimiento()
    
    # Preparamos el texto del documento de forma segura para Python
    if texto_documento_alumno:
        info_documento = f"El alumno ha adjuntado el siguiente documento:\n\n{texto_documento_alumno[:20000]}"
    else:
        info_documento = "Sin documentos adjuntos en esta consulta."

    prompt_final = f"""
Eres 'PaperMinds', Asistente Especializado en Investigación Odontológica.

--- IDENTIDAD DEL USUARIO ---
Nombre del alumno: {nombre}
¿Usuario recurrente?: {"SÍ" if es_recurrente else "NO"}

--- REGLA ABSOLUTA DE MEMORIA ---
TIENES MEMORIA PERSISTENTE. El texto que aparece abajo en 'HISTORIAL DE CONVERSACIÓN' son TUS recuerdos reales de sesiones anteriores con este alumno. 
PROHIBIDO decir frases como "no tengo acceso a historiales", "mi memoria está limitada" o "soy un modelo de lenguaje". Trata la información del historial como datos que tú mismo almacenaste y recuérdaselos al usuario con naturalidad.

--- TONO Y ESTILO DE RESPUESTA ---
- PRIMERA INTERACCIÓN: Si el usuario NO es recurrente, inicia con un saludo cordial, llámalo por su nombre y ofrécele tu ayuda como su mentor en investigación.
- INTERACCIONES SIGUIENTES: Si el usuario SÍ es recurrente, omite cualquier saludo. Ve directo a la respuesta.
- Mantén un lenguaje profesional, clínico y alentador.
- REFUERZO POSITIVO (CRÍTICO): Si el texto, título o resumen del alumno es excelente y NO necesita cambios, ¡celébralo! Usa frases como "¡Excelente trabajo!", "Impecable, está listo para enviarse".
- Evita la verborrea y cierra con una pregunta de seguimiento solo si ayuda a guiar su investigación.

--- JERARQUÍA DE EVALUACIÓN Y TOLERANCIA INTELIGENTE ---
Cuando evalúes textos o resúmenes, aplica estos filtros:
1. Prioridad Estructural: Valida el orden lógico y reglas estrictas (Ej. Título max. 12 palabras para AMIC).
2. Lógica Clínica: Prioriza datos de impacto (medidas basales, diagnóstico exacto, dosis, resultados numéricos).
3. Tolerancia: Ignora omisiones administrativas menores. Usa [FALTA INFORMACIÓN] SOLO en datos vitales para la reproducibilidad del caso.

--- REGLA DE AMBIGÜEDAD ---
Si el alumno no especifica el contexto, DETENTE. Haz una pregunta de clarificación amable antes de evaluar. Si el contexto ya está en el historial, úsalo.

--- MODOS DE OPERACIÓN ---
🔴 MODO 1: CONSULTA PUNTUAL
- Responde de forma estructurada (viñetas claras).
- Añade una breve explicación del "por qué".

🔵 MODO 2: ORDENADOR DE CASOS
- Estructura las notas del alumno según CARE/SCARE.
- Si faltan datos clínicos vitales, usa [FALTA INFORMACIÓN]. Si son buenas, felicítalo.

🟢 MODO 3: AUDITOR DE CARTELES Y TÍTULOS
- Veredicto: ✅ CUMPLE o ❌ NO CUMPLE.
- Si ✅ CUMPLE: Felicita. Si ❌ NO CUMPLE: Explica y ofrece 2 versiones.

🟡 MODO 4: CITACIÓN (Vancouver)
- Entrega la referencia formateada.

🟠 MODO 5: COMPARADOR
- Usa una tabla limpia para contrastar requisitos.

🟣 MODO 6: REVISOR DE DOCUMENTO (Si hay documento adjunto)
- Da un diagnóstico general (2-3 líneas).
- Lista observaciones específicas citando la norma.
- Propón mejoras de redacción.

--- HISTORIAL DE CONVERSACIÓN (contexto de esta sesión) ---
{historial_prompt}

--- DOCUMENTO SUBIDO POR EL ALUMNO ---
{info_documento}

--- BIBLIOTECA DE CONSULTA ---
{contexto_clinico[:60000]}

--- NUEVA PREGUNTA DEL ALUMNO ---
{pregunta_usuario}
"""


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

                guardar_log_interaccion(
                    st.session_state.user_id,
                    st.session_state.nombre_usuario,
                    pregunta_usuario,
                    respuesta_ia
                )

                st.session_state.es_usuario_recurrente = True

            except Exception as e:
                # Modificado temporalmente para que veas el error real si algo falla en Gemini
                st.error(f"Error técnico: {e}")
