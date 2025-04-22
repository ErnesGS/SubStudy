import whisper
from googletrans import Translator
import os
from typing import List, Dict
from pydub import AudioSegment
import logging
import torch
import tempfile
import shutil

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_ffmpeg():
    """Verifica si ffmpeg está instalado y accesible."""
    try:
        AudioSegment.converter = "ffmpeg"
        AudioSegment.ffmpeg = "ffmpeg"
        AudioSegment.ffprobe = "ffprobe"
        # Intentar una operación simple para verificar
        AudioSegment.from_file("test.wav", format="wav")
        return True
    except Exception as e:
        logger.error(f"Error al verificar ffmpeg: {e}")
        logger.error("""
        ffmpeg no está instalado o no está en el PATH del sistema.
        Por favor, instala ffmpeg siguiendo estos pasos:
        1. Descarga ffmpeg de https://ffmpeg.org/download.html
           - Ve a la sección "Windows Builds"
           - Descarga el archivo "ffmpeg-release-essentials.zip"
        2. Extrae el archivo ZIP en una carpeta (por ejemplo, C:\\ffmpeg)
        3. Añade la ruta a la variable de entorno PATH del sistema:
           - Abre el Panel de Control
           - Sistema y Seguridad > Sistema
           - Configuración avanzada del sistema
           - Variables de entorno
           - En Variables del sistema, edita PATH
           - Añade la ruta a la carpeta de ffmpeg (por ejemplo, C:\\ffmpeg)
        4. Reinicia PowerShell o tu terminal
        """)
        return False

class TranscriptionManager:
    def __init__(self):
        try:
            logger.info("Inicializando modelo Whisper...")
            # Usar el modelo base que es más rápido y requiere menos recursos
            self.model = whisper.load_model("base")
            logger.info("Modelo Whisper inicializado correctamente")
            self.translator = Translator()
            
            # Verificar ffmpeg
            if not check_ffmpeg():
                logger.warning("ffmpeg no está instalado correctamente. Algunas funciones pueden no funcionar.")
        except Exception as e:
            logger.error(f"Error al inicializar el modelo: {e}")
            raise
    
    def transcribe_audio(self, audio_path: str, language: str) -> List[Dict]:
        """
        Transcribe el audio a texto usando Whisper.
        
        Args:
            audio_path: Ruta al archivo de audio
            language: Código de idioma del audio
            
        Returns:
            Lista de diccionarios con el texto y timestamps
        """
        try:
            logger.info(f"Intentando transcribir archivo: {audio_path}")
            logger.info(f"El archivo existe: {os.path.exists(audio_path)}")
            logger.info(f"Tamaño del archivo: {os.path.getsize(audio_path)} bytes")
            
            # Verificar que el archivo existe y no está vacío
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"El archivo {audio_path} no existe")
            if os.path.getsize(audio_path) == 0:
                raise ValueError(f"El archivo {audio_path} está vacío")
            
            # Configurar opciones de transcripción
            options = {
                "language": language if language != "auto" else None,
                "task": "transcribe",
                "fp16": torch.cuda.is_available()  # Usar precisión mixta si hay GPU
            }
            
            logger.info(f"Opciones de transcripción: {options}")
            result = self.model.transcribe(audio_path, **options)
            logger.info("Transcripción completada")
            
            # Convertir el resultado al formato esperado
            segments = []
            for segment in result["segments"]:
                segments.append({
                    "text": segment["text"].strip(),
                    "start": segment["start"],
                    "end": segment["end"]
                })
            
            return segments
        except Exception as e:
            logger.error(f"Error en la transcripción: {e}")
            raise
    
    def translate_text(self, text: str, target_lang: str) -> str:
        """
        Traduce el texto usando Google Translate.
        
        Args:
            text: Texto a traducir
            target_lang: Idioma objetivo
            
        Returns:
            Texto traducido
        """
        try:
            logger.info(f"Traduciendo texto a {target_lang}")
            translation = self.translator.translate(text, dest=target_lang)
            logger.info("Traducción completada")
            return translation.text
        except Exception as e:
            logger.error(f"Error en la traducción: {e}")
            return text  # Retorna el texto original si hay error
    
    def process_video(self, video_path: str, source_lang: str, target_lang: str) -> List[Dict]:
        """
        Procesa un video completo: extrae audio, transcribe y traduce.
        
        Args:
            video_path: Ruta al archivo de video
            source_lang: Idioma del video
            target_lang: Idioma objetivo para traducción
            
        Returns:
            Lista de segmentos con texto original y traducido
        """
        temp_dir = None
        audio_path = None
        
        try:
            logger.info(f"Procesando video: {video_path}")
            logger.info(f"El archivo existe: {os.path.exists(video_path)}")
            
            # Verificar que el archivo existe
            if not os.path.exists(video_path):
                raise FileNotFoundError(f"El archivo {video_path} no existe")
            
            # Crear un directorio temporal único
            temp_dir = tempfile.mkdtemp(prefix="substudy_")
            audio_path = os.path.join(temp_dir, "audio.wav")
            
            # Extraer audio del video
            logger.info("Extrayendo audio del video...")
            video = AudioSegment.from_file(video_path)
            video.export(audio_path, format="wav")
            logger.info(f"Audio extraído y guardado en: {audio_path}")
            
            # Verificar que el archivo de audio se creó correctamente
            if not os.path.exists(audio_path):
                raise FileNotFoundError(f"No se pudo crear el archivo de audio: {audio_path}")
            
            # Transcribir audio
            logger.info("Iniciando transcripción...")
            segments = self.transcribe_audio(audio_path, source_lang)
            
            # Traducir cada segmento
            logger.info("Iniciando traducción...")
            for segment in segments:
                segment["translation"] = self.translate_text(segment["text"], target_lang)
            
            return segments
            
        except Exception as e:
            logger.error(f"Error en el procesamiento del video: {e}")
            raise
        finally:
            # Limpiar archivos temporales
            if temp_dir and os.path.exists(temp_dir):
                try:
                    shutil.rmtree(temp_dir)
                    logger.info("Archivos temporales eliminados correctamente")
                except Exception as e:
                    logger.error(f"Error al limpiar archivos temporales: {e}") 