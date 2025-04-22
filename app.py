import streamlit as st
import os
from SubStudy.transcription import TranscriptionManager
import tempfile
from pathlib import Path
import logging
import shutil

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración de la página
st.set_page_config(
    page_title="SubStudy",
    page_icon="🎬",
    layout="wide"
)

def download_youtube_video(url: str) -> str:
    """Descarga un video de YouTube y retorna la ruta del archivo."""
    try:
        from pytube import YouTube
        yt = YouTube(url)
        video = yt.streams.filter(progressive=True, file_extension='mp4').first()
        temp_dir = tempfile.mkdtemp()
        video_path = video.download(output_path=temp_dir)
        logger.info(f"Video descargado exitosamente a: {video_path}")
        return video_path
    except Exception as e:
        logger.error(f"Error al descargar el video: {e}")
        st.error(f"Error al descargar el video: {e}")
        return None

def save_uploaded_file(uploaded_file):
    """Guarda un archivo subido en un directorio temporal."""
    try:
        # Crear un directorio temporal en la carpeta del usuario
        temp_dir = os.path.join(os.path.expanduser("~"), "AppData", "Local", "Temp", "substudy")
        os.makedirs(temp_dir, exist_ok=True)
        
        # Obtener el nombre del archivo
        file_name = uploaded_file.name
        # Crear la ruta completa del archivo
        file_path = os.path.join(temp_dir, file_name)
        
        # Guardar el archivo
        with open(file_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        logger.info(f"Archivo guardado en: {file_path}")
        logger.info(f"El archivo existe: {os.path.exists(file_path)}")
        logger.info(f"Tamaño del archivo: {os.path.getsize(file_path)} bytes")
        
        return file_path, temp_dir
    except Exception as e:
        logger.error(f"Error al guardar el archivo: {e}")
        return None, None

def main():
    st.title("SubStudy - Subtítulos Interactivos")
    st.write("""
    SubStudy es una aplicación que genera subtítulos automáticos y permite traducciones interactivas.
    """)
    
    try:
        # Sección para cargar video
        st.header("Cargar Video")
        
        # Opción para subir archivo o ingresar URL
        input_type = st.radio(
            "Selecciona el tipo de entrada:",
            ["Subir archivo", "URL de YouTube"]
        )
        
        video_path = None
        temp_dir = None
        
        if input_type == "Subir archivo":
            video_file = st.file_uploader("Sube un video", type=["mp4", "mov", "avi"])
            if video_file:
                video_path, temp_dir = save_uploaded_file(video_file)
                if video_path:
                    st.video(video_file)
        else:
            youtube_url = st.text_input("Ingresa la URL de YouTube")
            if youtube_url:
                with st.spinner("Descargando video de YouTube..."):
                    video_path = download_youtube_video(youtube_url)
                    if video_path:
                        st.video(video_path)
        
        if video_path:
            # Opciones de idioma
            st.header("Configuración de Idiomas")
            col1, col2 = st.columns(2)
            
            with col1:
                source_language = st.selectbox(
                    "Idioma del video",
                    ["es", "en", "fr", "de", "it", "pt", "auto"]
                )
            
            with col2:
                target_language = st.selectbox(
                    "Idioma de traducción",
                    ["es", "en", "fr", "de", "it", "pt"]
                )
            
            if st.button("Generar Subtítulos"):
                with st.spinner("Procesando video..."):
                    try:
                        # Inicializar el gestor de transcripción
                        logger.info("Inicializando TranscriptionManager...")
                        manager = TranscriptionManager()
                        
                        # Procesar el video
                        logger.info(f"Procesando video: {video_path}")
                        segments = manager.process_video(video_path, source_language, target_language)
                        
                        # Mostrar resultados
                        st.success("¡Subtítulos generados con éxito!")
                        
                        # Mostrar subtítulos interactivos
                        st.header("Subtítulos Interactivos")
                        
                        for segment in segments:
                            # Crear un contenedor para cada segmento
                            with st.container():
                                # Mostrar el texto original
                                st.write(f"**Original ({source_language}):** {segment['text']}")
                                
                                # Mostrar la traducción
                                st.write(f"**Traducción ({target_language}):** {segment['translation']}")
                                
                                # Mostrar el tiempo
                                start_time = segment['start']
                                end_time = segment['end']
                                st.write(f"Tiempo: {start_time:.2f}s - {end_time:.2f}s")
                                
                                st.divider()
                        
                    except Exception as e:
                        logger.error(f"Error al procesar el video: {e}")
                        st.error(f"Error al procesar el video: {str(e)}")
                    finally:
                        # Limpiar archivos temporales
                        if temp_dir and os.path.exists(temp_dir):
                            try:
                                shutil.rmtree(temp_dir)
                                logger.info("Archivos temporales eliminados correctamente")
                            except Exception as e:
                                logger.error(f"Error al limpiar archivos temporales: {e}")
    
    except Exception as e:
        logger.error(f"Error general en la aplicación: {e}")
        st.error(f"Ha ocurrido un error: {str(e)}")

if __name__ == "__main__":
    main() 