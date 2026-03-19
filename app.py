kimport streamlit as st
import google.generativeai as genai
from google.generativeai.types import GenerationConfig
from PyPDF2 import PdfReader
import datetime
import json
import os
import firebase_admin
from firebase_admin import credentials, firestore

try:
    CLAVE_ACCESO_PILOTO = st.secrets["CLAVE_ACCESO_PILOTO"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    CLAVE_ADMIN_SECRETA = st.secrets["CLAVE_ADMIN_SECRETA"] 
    FIREBASE_CREDENTIALS = st.secrets["FIREBASE_CREDENTIALS"]
except KeyError:
    st.error("Faltan las claves de API. Configura los 'secrets' de Streamlit.")
    st.stop()

if not firebase_admin._apps:
    cred_dict = json.loads(FIREBASE_CREDENTIALS)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    
db = firestore.client()

genai.configure(api_key=GOOGLE_API_KEY)
modelo = genai.GenerativeModel(
    model_name='gemini-1.5-flash',
    generation_config={"tag": "v1"} 
)

def guardar_log_interaccion(pregunta, respuesta):
    """Guarda el historial directamente en Google Firebase. """
    log = {
        "fecha_hora": datetime.datetime.now().isoformat(),
        "input_usuario": pregunta,
        "output_ia": respuesta
    }

    try: 
        db.collection("chats_paperminds").add(log)
    except Exception as e:
        st.error(f"Error al guardar en la nube: {e}")

@st.cache_data
def cargar_base_conocimiento():
    texto = ""
    nombre_pdf = "Guia_dental.pdf" 
    try:
        lector = PdfReader(nombre_pdf)
        for pagina in lector.pages:
            texto += pagina.extract_text() + "\n"
        return texto
    except FileNotFoundError:
        return "ADVERTENCIA: No se encontró el archivo Guia_dental.pdf."
    
def verificar_acceso():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🦷 PaperMinds IA")
        st.info("Acceso restringido a usuarios autorizados. Por protocolo de privacidad, no ingrese datos reales de pacientes.")
        
        clave = st.text_input("Ingrese la clave maestra:", type="password")
        if st.button("Entrar"):
            if clave == CLAVE_ACCESO_PILOTO:
                st.session_state.autenticado = True
                st.rerun()
            else:
                st.error("Clave incorrecta.")
        return False
    return True

if verificar_acceso():
    st.title("🦷 PaperMinds IA")
    st.caption("Asistente experto en metodología e investigación odontológica.")

    contexto_clinico = cargar_base_conocimiento()

    if "mensajes_chat" not in st.session_state:
        st.session_state.mensajes_chat = []

    for msj in st.session_state.mensajes_chat:
        with st.chat_message(msj["rol"]):
            st.markdown(msj["contenido"])

    pregunta_usuario = st.chat_input("Ej: ¿Qué lleva un cartel de AMIC?")

    if pregunta_usuario:
     
        with st.chat_message("user"):
            st.markdown(pregunta_usuario)
        st.session_state.mensajes_chat.append({"rol": "user", "contenido": pregunta_usuario})

        prompt_final = f"""
        Eres 'PaperMinds', un asistente odontológico experto en metodología de la investigación. 
        Tu objetivo es responder de forma DIRECTA, BREVE y CONCISA. 
        
        REGLAS ESTRICTAS:
        1. Responde ÚNICAMENTE usando la información de la guía clínica proporcionada.
        2. NO des detalles de formato (tamaños de letra, centímetros, colores, reglas de impresión) A MENOS que el usuario te lo pregunte específicamente.
        3. Ve directo al grano. No uses saludos largos ni introducciones innecesarias.
        4. Si el usuario te da un texto para estructurar, devuélvele SOLO el texto estructurado, sin explicarle los pasos de cómo hacerlo.
        5. Si la información no está en la guía, di "No tengo información sobre eso en la guía actual."
        
        --- GUÍA CLÍNICA ---
        {contexto_clinico[:40000]} 
        
        --- DUDA DEL USUARIO ---
        {pregunta_usuario}
        """

        with st.chat_message("assistant"):
            try:
                respuesta_ia = modelo.generate_content(prompt_final, safety_settings={
    "HATE": "BLOCK_NONE",
    "HARASSMENT": "BLOCK_NONE",
    "SEXUAL": "BLOCK_NONE",
    "DANGEROUS": "BLOCK_NONE"
}).text
                st.markdown(respuesta_ia)
                st.session_state.mensajes_chat.append({"rol": "assistant", "contenido": respuesta_ia})
                
                guardar_log_interaccion(pregunta_usuario, respuesta_ia)
            except Exception as e:
                error_str = str(e)
                if "429" in error_str or "Quota" in error_str:
                    st.warning("⏳ Muchos estudiantes están consultando al mismo tiempo. Por favor, espera 20 segundos y vuelve a darle Enter a tu pregunta.")
                else:
                    st.error(f"Error de conexión con la IA: {e}")
            
