import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import datetime
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y MARCA (CSS)
# ==========================================
st.set_page_config(page_title="PaperMinds IA", page_icon="🦷", layout="centered")

# Inyección de CSS para estilizar la app sin romper el modo oscuro/claro
st.markdown("""
    <style>
    /* Importar tipografías elegantes */
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Inter:wght@400;600&display=swap');
    
    /* Estilo del Título Principal */
    .main-title {
        font-family: 'Playfair+Display', serif;
        font-size: 3.2rem;
        color: #00D1FF; /* Azul cian brillante */
        text-align: center;
        margin-bottom: 0px;
        padding-top: 0px;
    }
    
    /* Estilo del Subtítulo */
    .subtitle {
        font-family: 'Inter', sans-serif;
        font-size: 1.1rem;
        text-align: center;
        opacity: 0.8;
        margin-bottom: 35px;
    }

    /* Estilo general del chat para redondear bordes */
    .stChatMessage {
        border-radius: 15px;
        margin-bottom: 10px;
    }
    
    /* Botón de envío personalizado (Azul dental) */
    button[kind="primary"] {
        background-color: #00D1FF !important;
        border: none !important;
        color: white !important;
    }

    /* Ocultar elementos innecesarios de Streamlit para mayor limpieza */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 2. SECCIÓN DE SEGURIDAD (CONEXIONES)
# ==========================================

# Cargar llaves secretas
try:
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    FIREBASE_CREDENTIALS = st.secrets["FIREBASE_CREDENTIALS"]
    # Las claves de acceso piloto y admin ya no se usan en la UI, 
    # pero las dejamos cargadas por si Firebase las necesita internamente.
except KeyError:
    st.error("Faltan las claves de API en los 'secrets' de Streamlit.")
    st.stop()

# Inicializar Firebase (Bases de datos)
if not firebase_admin._apps:
    try:
        cred_dict = json.loads(FIREBASE_CREDENTIALS)
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)
    except Exception as e:
        st.error(f"Error crítico al conectar con Firebase: {e}")
        st.stop()
    
db = firestore.client()

# Inicializar Google AI (Gemini)
genai.configure(api_key=GOOGLE_API_KEY)

# *** CAMBIO IMPORTANTE: Usamos el modelo de alta capacidad ***
# Este modelo acepta las 1,500 consultas diarias gracias a tu cuenta verificada.
modelo = genai.GenerativeModel('gemini-3-flash-preview')

# ==========================================
# 3. FUNCIONES DE SOPORTE
# ==========================================

def guardar_log_interaccion(pregunta, respuesta):
    """Guarda el historial de chat directamente en Google Firebase Cloud."""
    log = {
        "fecha_hora": datetime.datetime.now().isoformat(),
        "input_usuario": pregunta,
        "output_ia": respuesta,
        "proyecto": "PaperMinds PILOTO"
    }

    try: 
        db.collection("chats_paperminds").add(log)
    except Exception as e:
        # Error silencioso en UI para no interrumpir al usuario
        print(f"Error al guardar log en Firebase: {e}")

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

# *** MODIFICACIÓN: Se eliminó la función verificar_acceso() ***
# El acceso ahora es directo.

# ==========================================
# 4. INTERFAZ DE CHAT (DASHBOARD)
# ==========================================

# Encabezado estético con HTML/CSS
st.markdown('<h1 class="main-title">🦷 PaperMinds</h1>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Asistente experto en metodología e investigación odontológica</p>', unsafe_allow_html=True)

# Recordatorio de privacidad
st.info("⚠️ Por protocolo de privacidad, no ingrese datos reales ni nombres de pacientes.")

# Cargar el PDF en memoria (una sola vez)
contexto_clinico = cargar_base_conocimiento()

# Inicializar historial de chat en la sesión
if "mensajes_chat" not in st.session_state:
    st.session_state.mensajes_chat = []

# Mostrar el historial de chat con los NUEVOS ICONOS
for msj in st.session_state.mensajes_chat:
    avatar = "👨‍⚕️" if msj["role"] == "user" else "🤖"
    with st.chat_message(msj["role"], avatar=avatar):
        st.markdown(msj["role"] == "user" and msj.get("content") or msj.get("contenido") or msj.get("content", ""))

# Caja de entrada de texto (Input)
pregunta_usuario = st.chat_input("Ej: ¿Cómo estructurar un caso clínico?")

# Proceso de respuesta
if pregunta_usuario:
    # 1. Mostrar y guardar pregunta del usuario
    with st.chat_message("user", avatar="👨‍⚕️"):
        st.markdown(pregunta_usuario)
    st.session_state.mensajes_chat.append({"role": "user", "contenido": pregunta_usuario})

    # 2. Construir el Prompt (Instrucciones para la IA)
    # Limitamos el contexto del PDF para evitar saturar la memoria (primeros 60,000 caracteres)
    prompt_final = f"""
Eres 'PaperMinds', un asistente odontológico experto en metodología de la investigación. 
Tu objetivo es responder de forma DIRECTA, BREVE y CONCISA. No uses saludos largos ni introducciones innecesarias.

REGLAS ESTRICTAS DE RESPUESTA:
1. Responde ÚNICAMENTE usando la información de la guía clínica proporcionada abajo.
2. NO des detalles de formato (tamaños de letra, centímetros, colores, reglas de impresión, márgenes) A MENOS que el usuario te lo pregunte específicamente.
3. Si el usuario te da un texto para estructurar, devuélvele SOLO el texto estructurado, sin explicarle los pasos de cómo hacerlo.
4. Si la información no está en la guía, di exactamente: "No tengo información sobre eso en la guía actual de AMIC."

5. Mantén un tono profesional pero muy directo.

--- GUÍA CLÍNICA AMIC (CONTEXTO) ---
{contexto_clinico[:60000]} 

--- DUDA DEL USUARIO ---
{pregunta_usuario}
"""

    # 3. Generar respuesta de la IA
    with st.chat_message("assistant", avatar="🤖"):
        # Indicador de carga (Spinner)
        with st.spinner("Consultando la guía dental..."):
            try:
                # Configuración de seguridad para evitar bloqueos innecesarios en temas médicos
                safety_settings = {
                    "HATE": "BLOCK_NONE",
                    "HARASSMENT": "BLOCK_NONE",
                    "SEXUAL": "BLOCK_NONE",
                    "DANGEROUS": "BLOCK_NONE"
                }
                
                # Llamada a la API de Google
                response = modelo.generate_content(prompt_final, safety_settings=safety_settings)
                respuesta_ia = response.text
                
                # Mostrar respuesta y guardar en historial
                st.markdown(respuesta_ia)
                st.session_state.mensajes_chat.append({"role": "assistant", "contenido": respuesta_ia})
                
                # 4. Guardar log en Firebase (en segundo plano)
                guardar_log_interaccion(pregunta_usuario, respuesta_ia)
                
            except Exception as e:
                # Mensaje amable en caso de Error 429 (saturación por minuto)
                st.warning("⏳ Muchos estudiantes están consultando al mismo tiempo. Por favor, espera 20 segundos y vuelve a enviar tu pregunta.")
                # st.error(f"Detalle técnico del error: {e}") # Descomentar solo para mantenimiento
