import streamlit as st
import os
from transcription import TranscriptionManager
import tempfile
from pathlib import Path
import logging
import shutil
import base64

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

def create_subtitle_html(segments, source_lang, target_lang, video_path):
    """Crea el HTML para mostrar los subtítulos superpuestos."""
    # Leer el video como base64
    with open(video_path, "rb") as video_file:
        video_data = base64.b64encode(video_file.read()).decode()
    
    subtitle_html = f"""
    <style>
    .video-container {{
        position: relative;
        width: 100%;
        max-width: 800px;
        margin: 0 auto;
    }}
    .subtitle-container {{
        position: absolute;
        bottom: 20%;
        left: 0;
        right: 0;
        text-align: center;
        z-index: 1000;
    }}
    .subtitle {{
        background-color: rgba(0, 0, 0, 0.7);
        color: white;
        padding: 10px;
        border-radius: 5px;
        margin: 5px 0;
        font-size: 1.2em;
        display: inline-block;
        max-width: 80%;
    }}
    .original {{
        font-weight: bold;
    }}
    .translation {{
        font-style: italic;
    }}
    </style>
    <div class="video-container">
        <video id="videoPlayer" controls style="width: 100%;">
            <source src="data:video/mp4;base64,{video_data}" type="video/mp4">
        </video>
        <div class="subtitle-container">
    """
    
    for segment in segments:
        subtitle_html += f"""
            <div class="subtitle" data-start="{segment['start']}" data-end="{segment['end']}">
                <div class="original">{segment['text']}</div>
                <div class="translation">{segment['translation']}</div>
            </div>
        """
    
    subtitle_html += """
        </div>
    </div>
    <script>
    const video = document.getElementById('videoPlayer');
    const subtitles = document.querySelectorAll('.subtitle');
    
    function updateSubtitles() {
        const currentTime = video.currentTime;
        subtitles.forEach(subtitle => {
            const start = parseFloat(subtitle.dataset.start);
            const end = parseFloat(subtitle.dataset.end);
            if (currentTime >= start && currentTime <= end) {
                subtitle.style.display = 'inline-block';
            } else {
                subtitle.style.display = 'none';
            }
        });
    }
    
    video.addEventListener('timeupdate', updateSubtitles);
    </script>
    """
    return subtitle_html

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
                        
                        # Crear y mostrar el HTML con los subtítulos
                        subtitle_html = create_subtitle_html(segments, source_language, target_language, video_path)
                        st.components.v1.html(subtitle_html, height=600)
                        
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