import whisper
from googletrans import Translator
import os
from typing import List, Dict
from pydub import AudioSegment
import logging
import torch
import tempfile
import shutil
import numpy as np
import queue
import threading
import time
import pyaudio
import ffmpeg

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_ffmpeg():
    """Verifica si ffmpeg está instalado y accesible."""
    try:
        logger.info("Verificando instalación de ffmpeg...")
        # Verificar que ffmpeg está en el PATH
        import subprocess
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        logger.info(f"ffmpeg version output: {result.stdout[:100]}...")  # Mostrar primeros 100 caracteres
        
        # Configurar pydub
        logger.info("Configurando pydub con ffmpeg...")
        AudioSegment.converter = "ffmpeg"
        AudioSegment.ffmpeg = "ffmpeg"
        AudioSegment.ffprobe = "ffprobe"
        
        # Intentar una operación simple para verificar
        logger.info("Intentando operación de prueba con ffmpeg...")
        test_file = "test.wav"
        # Crear un archivo de audio de prueba
        audio = AudioSegment.silent(duration=1000)  # 1 segundo de silencio
        audio.export(test_file, format="wav")
        logger.info(f"Archivo de prueba creado: {test_file}")
        
        # Intentar leer el archivo
        test_audio = AudioSegment.from_file(test_file, format="wav")
        logger.info("Operación de prueba exitosa")
        
        # Limpiar el archivo de prueba
        if os.path.exists(test_file):
            os.remove(test_file)
            logger.info("Archivo de prueba eliminado")
        
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

class RealTimeTranscriptionManager:
    def __init__(self, source_lang: str, target_lang: str):
        try:
            logger.info("Inicializando modelo Whisper para transcripción en tiempo real...")
            self.model = whisper.load_model("base")
            self.translator = Translator()
            self.source_lang = source_lang
            self.target_lang = target_lang
            self.audio_queue = queue.Queue()
            self.subtitle_queue = queue.Queue()
            self.is_running = False
            self.processing_thread = None
            
            # Verificar ffmpeg con más detalle
            logger.info("Verificando configuración de ffmpeg...")
            if not check_ffmpeg():
                logger.error("ffmpeg no está configurado correctamente")
                raise RuntimeError("ffmpeg no está configurado correctamente")
            
            logger.info("Inicialización completada correctamente")
            
        except Exception as e:
            logger.error(f"Error al inicializar el modelo: {e}")
            raise
    
    def start_processing(self, stream_url: str = None):
        """Inicia el procesamiento en tiempo real del streaming."""
        try:
            logger.info("Iniciando procesamiento de streaming...")
            self.is_running = True
            
            # Iniciar el thread de procesamiento
            logger.info("Iniciando thread de procesamiento...")
            self.processing_thread = threading.Thread(target=self._process_stream, args=(stream_url,))
            self.processing_thread.daemon = True
            self.processing_thread.start()
            logger.info("Procesamiento iniciado correctamente")
            
        except Exception as e:
            logger.error(f"Error al iniciar el procesamiento: {e}")
            raise
    
    def stop_processing(self):
        """Detiene el procesamiento en tiempo real."""
        try:
            logger.info("Deteniendo procesamiento...")
            self.is_running = False
            
            if self.processing_thread:
                logger.info("Esperando a que termine el thread de procesamiento...")
                self.processing_thread.join()
            
            logger.info("Procesamiento detenido correctamente")
            
        except Exception as e:
            logger.error(f"Error al detener el procesamiento: {e}")
            raise
    
    def _process_stream(self, stream_url: str = None):
        """Procesa el streaming en tiempo real."""
        logger.info("Iniciando procesamiento de streaming...")
        try:
            import ffmpeg
            
            # Configurar la entrada de ffmpeg
            if stream_url:
                # Si se proporciona una URL de streaming
                input_stream = ffmpeg.input(stream_url)
            else:
                # Capturar el audio del sistema usando el dispositivo correcto
                device_name = "Varios micrófonos (Intel® Smart Sound Technology for Digital Microphones)"
                logger.info(f"Usando dispositivo de audio: {device_name}")
                
                # Configurar la entrada de audio
                input_stream = ffmpeg.input(
                    f'audio="{device_name}"',
                    f='dshow',
                    sample_rate=16000,
                    channels=1,
                    audio_buffer_size=50  # Añadir buffer de audio
                )
            
            # Configurar la salida de audio
            stream = (
                input_stream
                .output('pipe:', format='f32le', acodec='pcm_f32le', ac=1, ar='16k')
                .run_async(pipe_stdout=True)
            )
            
            # Tamaño del buffer en bytes (1 segundo de audio)
            buffer_size = 16000 * 4  # 16kHz * 4 bytes (float32)
            audio_buffer = []
            buffer_duration = 3.0  # Duración del buffer en segundos
            
            while self.is_running:
                try:
                    # Leer audio del stream
                    in_bytes = stream.stdout.read(buffer_size)
                    if not in_bytes:
                        break
                        
                    # Convertir bytes a numpy array
                    audio_data = np.frombuffer(in_bytes, dtype=np.float32)
                    audio_buffer.append(audio_data)
                    
                    # Calcular la duración actual del buffer
                    current_duration = len(audio_buffer) * len(audio_data) / 16000
                    
                    if current_duration >= buffer_duration:
                        # Concatenar todos los fragmentos de audio
                        full_audio = np.concatenate(audio_buffer)
                        
                        # Procesar el audio
                        options = {
                            "language": self.source_lang if self.source_lang != "auto" else None,
                            "task": "transcribe",
                            "fp16": torch.cuda.is_available()
                        }
                        
                        result = self.model.transcribe(full_audio, **options)
                        if result["text"].strip():
                            logger.info(f"Transcripción completada: {result['text']}")
                            
                            # Procesar cada segmento
                            for segment in result["segments"]:
                                # Traducir el texto
                                translation = self.translator.translate(
                                    segment["text"].strip(),
                                    dest=self.target_lang
                                )
                                
                                # Añadir a la cola de subtítulos
                                self.subtitle_queue.put({
                                    "text": segment["text"].strip(),
                                    "translation": translation.text,
                                    "start": segment["start"],
                                    "end": segment["end"]
                                })
                                logger.info(f"Traducción completada: {translation.text}")
                        
                        # Limpiar el buffer
                        audio_buffer = []
                
                except Exception as e:
                    logger.error(f"Error en el procesamiento de audio: {e}")
                    time.sleep(0.1)
            
            # Cerrar el stream
            stream.stdout.close()
            stream.wait()
            
        except Exception as e:
            logger.error(f"Error en el procesamiento del streaming: {e}")
            raise
    
    def get_subtitles(self) -> List[Dict]:
        """Obtiene los subtítulos generados hasta el momento."""
        subtitles = []
        while not self.subtitle_queue.empty():
            subtitles.append(self.subtitle_queue.get())
        return subtitles

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