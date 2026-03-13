import streamlit as st
import google.generativeai as genai
from PyPDF2 import PdfReader
import datetime
import json
import os

try:
    CLAVE_ACCESO_PILOTO = st.secrets["CLAVE_ACCESO_PILOTO"]
    GOOGLE_API_KEY = st.secrets["GOOGLE_API_KEY"]
    CLAVE_ADMIN_SECRETA = st.secrets["CLAVE_ADMIN_SECRETA"] 
except KeyError:
    st.error("Faltan las claves de API. Configura los 'secrets' de Streamlit.")
    st.stop()

genai.configure(api_key=GOOGLE_API_KEY)
modelo = genai.GenerativeModel('models/gemini-2.5-flash')


def guardar_log_interaccion(pregunta, respuesta):
    """Guarda el historial en formato JSON. 
    Para la Fase 2 en producción, conectaremos esto a una base Serverless."""
    log = {
        "fecha_hora": datetime.datetime.now().isoformat(),
        "input_usuario": pregunta,
        "output_ia": respuesta
    }
    
    archivo_logs = "historial_piloto.json"
    logs_existentes = []
    
    if os.path.exists(archivo_logs):
        with open(archivo_logs, "r", encoding="utf-8") as f:
            try:
                logs_existentes = json.load(f)
            except json.JSONDecodeError:
                logs_existentes = []
            
    logs_existentes.append(log)
    
    with open(archivo_logs, "w", encoding="utf-8") as f:
        json.dump(logs_existentes, f, indent=4, ensure_ascii=False)

@st.cache_data
def cargar_base_conocimiento():
    texto = ""
    nombre_pdf = "guia_dental.pdf" 
    try:
        lector = PdfReader(nombre_pdf)
        for pagina in lector.pages:
            texto += pagina.extract_text() + "\n"
        return texto
    except FileNotFoundError:
        return "ADVERTENCIA: No se encontró el archivo guia_dental.pdf. El chatbot responderá con conocimiento general."

def verificar_acceso():
    if "autenticado" not in st.session_state:
        st.session_state.autenticado = False

    if not st.session_state.autenticado:
        st.title("🦷 Asistente Odonto IA - Fase Piloto")
        st.info("Acceso restringido a 40 usuarios autorizados. Por protocolo de privacidad, no ingrese datos reales de pacientes.")
        
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
    st.title("🦷 Chatbot Odonto 2026")
    st.caption("Conectado a Google Gemini y alimentado por guías clínicas PDF.")

    # Cargar el PDF en la memoria RAM (caché)
    contexto_clinico = cargar_base_conocimiento()

    # Inicializar historial visual de la sesión actual
    if "mensajes_chat" not in st.session_state:
        st.session_state.mensajes_chat = []

    # Dibujar mensajes anteriores en la pantalla
    for msj in st.session_state.mensajes_chat:
        with st.chat_message(msj["rol"]):
            st.markdown(msj["contenido"])

    # Capturar lo que escribe el usuario
    pregunta_usuario = st.chat_input("Ej: ¿Cómo hago una tesina?")

    if pregunta_usuario:
     
        with st.chat_message("user"):
            st.markdown(pregunta_usuario)
        st.session_state.mensajes_chat.append({"rol": "user", "contenido": pregunta_usuario})

        prompt_final = f"""
        Eres un especialista odontológico experto. Responde la siguiente duda usando ÚNICAMENTE 
        la información de esta guía clínica. Si no está en el texto, indícalo claramente y no inventes tratamientos.
        
        --- GUÍA CLÍNICA ---
        {contexto_clinico[:40000]} 
        
        --- DUDA DEL USUARIO ---
        {pregunta_usuario}
        """

        with st.chat_message("assistant"):
            try:
                respuesta_ia = modelo.generate_content(prompt_final).text
                st.markdown(respuesta_ia)
                st.session_state.mensajes_chat.append({"rol": "assistant", "contenido": respuesta_ia})
                
                guardar_log_interaccion(pregunta_usuario, respuesta_ia)
            except Exception as e:
                st.error(f"Error de conexión con la IA: {e}")


    st.sidebar.title("⚙️ Panel del Investigador")
    st.sidebar.caption("Área restringida.")
    
    clave_admin = st.sidebar.text_input("Clave Admin:", type="password")
    
    if clave_admin == CLAVE_ADMIN_SECRETA:  
        st.sidebar.success("Acceso concedido.")
        if os.path.exists("historial_piloto.json"):
            with open("historial_piloto.json", "r", encoding="utf-8") as f:
                st.sidebar.download_button(
                    label="📥 Descargar Historial (JSON)",
                    data=f,
                    file_name=f"historial_odontologia_{datetime.date.today()}.json",
                    mime="application/json"
                )
        else:
            st.sidebar.warning("Aún no hay conversaciones guardadas hoy.")


