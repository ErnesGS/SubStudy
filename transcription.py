import vosk
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
import subprocess
import urllib.request
import zipfile
import json

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def download_model(model_dir: str = "models", language: str = "es") -> str:
    """Descarga el modelo de Vosk según el idioma especificado."""
    os.makedirs(model_dir, exist_ok=True)
    
    # Definir modelos disponibles
    models = {
        "es": {
            "name": "vosk-model-small-es-0.42",
            "url": "https://alphacephei.com/vosk/models/vosk-model-small-es-0.42.zip"
        },
        "en": {
            "name": "vosk-model-small-en-us-0.15",
            "url": "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
        }
    }
    
    # Seleccionar modelo según el idioma
    if language not in models:
        logger.warning(f"Idioma {language} no soportado, usando español por defecto")
        language = "es"
    
    model_info = models[language]
    model_name = model_info["name"]
    model_path = os.path.join(model_dir, model_name)
    
    if not os.path.exists(model_path):
        logger.info(f"Descargando modelo Vosk para {language}...")
        model_url = model_info["url"]
        zip_path = os.path.join(model_dir, "model.zip")
        
        try:
            # Descargar el modelo
            logger.info(f"Descargando modelo desde {model_url}")
            urllib.request.urlretrieve(model_url, zip_path)
            
            # Verificar que el archivo se descargó correctamente
            if not os.path.exists(zip_path):
                raise FileNotFoundError("El archivo del modelo no se descargó correctamente")
            
            # Extraer el modelo
            logger.info("Extrayendo modelo...")
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(model_dir)
            
            # Verificar que el modelo se extrajo correctamente
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"El modelo no se extrajo correctamente en {model_path}")
            
            # Limpiar el archivo zip
            os.remove(zip_path)
            logger.info(f"Modelo descargado y extraído correctamente en {model_path}")
            
            # Verificar la estructura del modelo
            required_files = ['am', 'conf', 'graph', 'ivector']
            for file in required_files:
                if not os.path.exists(os.path.join(model_path, file)):
                    raise FileNotFoundError(f"Falta el archivo/directorio requerido: {file}")
            
        except Exception as e:
            logger.error(f"Error al descargar o extraer el modelo: {e}")
            # Limpiar archivos parciales en caso de error
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if os.path.exists(model_path):
                shutil.rmtree(model_path)
            raise
    
    return model_path

def check_ffmpeg():
    """Verifica si ffmpeg está instalado y accesible en el PATH."""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            AudioSegment.converter = "ffmpeg"
            AudioSegment.ffmpeg = "ffmpeg"
            AudioSegment.ffprobe = "ffprobe"
            return True
        else:
            logger.error("ffmpeg no está disponible en el PATH del sistema.")
            return False
    except Exception as e:
        logger.error(f"ffmpeg no está instalado o no es accesible: {e}")
        return False

class RealTimeTranscriptionManager:
    def __init__(self, source_lang: str, target_lang: str):
        self.audio_interface = None
        try:
            logger.info("Inicializando RealTimeTranscriptionManager con PyAudio...")
            
            # Crear PyAudio Interface
            self.audio_interface = pyaudio.PyAudio()

            # Inicializar Vosk
            try:
                # Mapear códigos de idioma a códigos de modelo
                lang_map = {
                    "es": "es",
                    "en": "en",
                    "auto": "en"  # Por defecto usar inglés si es auto
                }
                model_lang = lang_map.get(source_lang, "en")
                
                model_path = download_model(language=model_lang)
                logger.info(f"Inicializando modelo Vosk desde {model_path} para idioma {model_lang}")
                self.model = vosk.Model(model_path)
                self.recognizer = vosk.KaldiRecognizer(self.model, 16000)
                logger.info("Modelo Vosk inicializado correctamente")
            except Exception as e:
                logger.error(f"Error al inicializar el modelo Vosk: {e}")
                raise
            
            self.translator = Translator()
            
            self.source_lang = source_lang
            self.target_lang = target_lang
            
            # Configuración de PyAudio
            self.CHUNK = 1024 * 4
            self.FORMAT = pyaudio.paInt16 
            self.CHANNELS = 1
            self.RATE = 16000
            self.RECORD_SECONDS = 2
            
            self.stream = None
            self.audio_queue = queue.Queue()
            self.subtitle_queue = queue.Queue()
            self.is_running = False
            self.audio_thread = None
            self.processing_thread = None
            
            logger.info("RealTimeTranscriptionManager inicializado correctamente")
            
        except Exception as e:
            logger.error(f"Error al inicializar RealTimeTranscriptionManager: {e}")
            if self.audio_interface:
                try:
                    self.audio_interface.terminate()
                    logger.info("Interfaz de PyAudio terminada debido a error de inicialización.")
                except Exception as term_error:
                    logger.error(f"Error al terminar PyAudio durante manejo de error inicial: {term_error}")
            raise

    def _process_audio(self):
        """Consume datos de la cola de audio, transcribe y traduce."""
        logger.info("Iniciando procesamiento de la cola de audio...")
        audio_buffer = []
        frames_to_process = int(self.RATE / self.CHUNK * 2)  # 0.5 segundos de buffer
        last_text = ""  # Para almacenar el último texto procesado
        
        while self.is_running:
            try:
                chunk = self.audio_queue.get(timeout=1)
                audio_buffer.append(chunk)
                
                if len(audio_buffer) >= frames_to_process:
                    raw_data = b''.join(audio_buffer)
                    audio_buffer = []  # Limpiar buffer para el siguiente ciclo
                    
                    if len(raw_data) > 0:
                        try:
                            # Realizar la transcripción con Vosk
                            if self.recognizer.AcceptWaveform(raw_data):
                                result = json.loads(self.recognizer.Result())
                                current_text = result.get("text", "").strip()
                                
                                if current_text and current_text != last_text:
                                    # Obtener solo el texto nuevo
                                    new_text = current_text[len(last_text):].strip()
                                    if new_text:
                                        logger.info(f"Transcripción: {new_text}")
                                        
                                        # Traducir el texto nuevo
                                        translation = self.translator.translate(new_text, dest=self.target_lang)
                                        
                                        # Añadir a la cola de subtítulos
                                        self.subtitle_queue.put({
                                            "text": new_text,
                                            "translation": translation.text,
                                            "start": time.time(),
                                            "end": time.time() + 2
                                        })
                                        logger.info(f"Traducción: {translation.text}")
                                    
                                    # Actualizar el último texto procesado
                                    last_text = current_text
                            else:
                                # Obtener resultado parcial
                                partial = json.loads(self.recognizer.PartialResult())
                                partial_text = partial.get("partial", "").strip()
                                
                                if partial_text and partial_text != last_text:
                                    # Obtener solo el texto nuevo del parcial
                                    new_text = partial_text[len(last_text):].strip()
                                    if new_text:
                                        # Traducir el texto parcial nuevo
                                        translation = self.translator.translate(new_text, dest=self.target_lang)
                                        
                                        # Añadir a la cola de subtítulos
                                        self.subtitle_queue.put({
                                            "text": new_text,
                                            "translation": translation.text,
                                            "start": time.time(),
                                            "end": time.time() + 1
                                        })
                                    
                                    # Actualizar el último texto procesado
                                    last_text = partial_text
                                    
                        except Exception as e:
                            logger.error(f"Error en la transcripción de Vosk: {e}")

                    # Limpiar la cola para evitar acumulación
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            break
                            
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"Error en el procesamiento de audio: {e}")
                continue

    def start_processing(self, input_device_index: int = None):
        """Inicia la captura y procesamiento de audio."""
        if self.is_running:
            logger.warning("El procesamiento ya está en curso.")
            return
            
        try:
            logger.info("Iniciando procesamiento de audio en tiempo real...")
            
            # Listar dispositivos si no se proporciona índice (para depuración)
            if input_device_index is None:
                 logger.warning("No se especificó input_device_index. Listando dispositivos:")
                 self.list_audio_devices()
                 # Podrías intentar usar el dispositivo por defecto o lanzar un error
                 # Aquí intentaremos usar el dispositivo por defecto
                 try:
                      default_device_info = self.audio_interface.get_default_input_device_info()
                      input_device_index = default_device_info['index']
                      logger.info(f"Usando dispositivo por defecto: Índice {input_device_index} - {default_device_info['name']}")
                 except IOError as e:
                      logger.error(f"No se pudo obtener el dispositivo de entrada por defecto: {e}")
                      logger.error("Por favor, especifica un índice de dispositivo válido.")
                      # Opcional: Mostrar error en Streamlit
                      # st.error("No se encontró un micrófono por defecto. Verifica la configuración de audio.")
                      return # No iniciar si no hay dispositivo

            self.stream = self.audio_interface.open(format=self.FORMAT,
                                                    channels=self.CHANNELS,
                                                    rate=self.RATE,
                                                    input=True,
                                                    frames_per_buffer=self.CHUNK,
                                                    input_device_index=input_device_index)
            
            logger.info("Stream de PyAudio abierto.")
            self.is_running = True
            
            # Iniciar hilo para leer audio
            self.audio_thread = threading.Thread(target=self._read_audio)
            self.audio_thread.daemon = True
            self.audio_thread.start()
            logger.info("Hilo de lectura de audio iniciado.")
            
            # Iniciar hilo para procesar audio
            self.processing_thread = threading.Thread(target=self._process_audio)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            logger.info("Hilo de procesamiento de audio iniciado.")
            
            logger.info("Procesamiento iniciado correctamente.")
            
        except Exception as e:
            logger.error(f"Error al iniciar el procesamiento: {e}")
            # Limpiar recursos si falla el inicio
            self.stop_processing()
            raise

    def _read_audio(self):
        """Lee datos del stream de PyAudio y los pone en la cola."""
        logger.info("Iniciando lectura de audio desde el stream...")
        while self.is_running and self.stream and self.stream.is_active():
            try:
                data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                self.audio_queue.put(data)
            except IOError as e:
                # Este error puede ocurrir si el stream se cierra mientras se lee
                if e.errno == -9988: # Código de error común para Stream is stopped
                     logger.warning("El stream de audio se detuvo mientras se leía.")
                else:
                     logger.error(f"Error de lectura de PyAudio: {e}")
                # Considerar si detener el proceso aquí o intentar reabrir stream
                # Por ahora, simplemente salimos del bucle si hay error grave
                break
            except Exception as e:
                logger.error(f"Error inesperado en _read_audio: {e}")
                break # Salir en caso de error inesperado
        logger.info("Lectura de audio finalizada.")

    def stop_processing(self):
        """Detiene la captura y el procesamiento."""
        logger.info("Intentando detener el procesamiento...")
        if not self.is_running and not self.stream and not self.audio_interface:
             logger.info("El procesamiento ya estaba detenido o no iniciado.")
             return

        self.is_running = False # Señal para que los hilos terminen
        
        # Detener y cerrar el stream de PyAudio
        if self.stream:
            try:
                if self.stream.is_active():
                    self.stream.stop_stream()
                self.stream.close()
                logger.info("Stream de PyAudio detenido y cerrado.")
            except Exception as e:
                 logger.error(f"Error al detener/cerrar stream de PyAudio: {e}")
            finally:
                 self.stream = None

        # Esperar a que los hilos terminen (con timeouts)
        if self.audio_thread and self.audio_thread.is_alive():
            logger.info("Esperando finalización del hilo de lectura de audio...")
            self.audio_thread.join(timeout=1) # Reducir timeout si es necesario
            if self.audio_thread.is_alive():
                 logger.warning("El hilo de lectura de audio no finalizó a tiempo.")
        
        if self.processing_thread and self.processing_thread.is_alive():
            logger.info("Esperando finalización del hilo de procesamiento de audio...")
            # Poner algo en la cola puede ayudar si está bloqueado en get(timeout=1)
            self.audio_queue.put(b'') # Enviar bytes vacíos podría funcionar
            self.processing_thread.join(timeout=3) # Ajustar timeout
            if self.processing_thread.is_alive():
                 logger.warning("El hilo de procesamiento de audio no finalizó a tiempo.")

        # Limpiar colas después de que los hilos (supuestamente) han terminado
        while not self.audio_queue.empty():
            try: self.audio_queue.get_nowait()
            except queue.Empty: break
        while not self.subtitle_queue.empty():
            try: self.subtitle_queue.get_nowait()
            except queue.Empty: break
            
        # Terminar la interfaz de PyAudio (IMPORTANTE: hacerlo al final)
        if self.audio_interface:
            try:
                self.audio_interface.terminate()
                logger.info("Interfaz de PyAudio terminada.")
            except Exception as e:
                 logger.error(f"Error al terminar la interfaz de PyAudio: {e}")
            finally:
                self.audio_interface = None # Marcar como terminado

        logger.info("Procesamiento detenido y recursos liberados.")
        # Resetear hilos por si se reinicia
        self.audio_thread = None
        self.processing_thread = None


    def get_subtitles(self) -> List[Dict]:
        """Obtiene los subtítulos generados hasta el momento."""
        subtitles = []
        while not self.subtitle_queue.empty():
            subtitles.append(self.subtitle_queue.get())
        # Quizás limitar la cantidad de subtítulos devueltos para evitar sobrecargar la UI
        # O implementar lógica para mostrar solo los más recientes
        return subtitles

    def list_audio_devices(self):
        """Lista los dispositivos de entrada de audio disponibles."""
        logger.info("Dispositivos de entrada de audio disponibles:")
        info = self.audio_interface.get_host_api_info_by_index(0)
        numdevices = info.get('deviceCount')
        devices = []
        for i in range(0, numdevices):
            device_info = self.audio_interface.get_device_info_by_host_api_device_index(0, i)
            if device_info.get('maxInputChannels') > 0:
                device_name = device_info.get('name')
                logger.info(f"  Índice {i}: {device_name}")
                devices.append({"index": i, "name": device_name})
        if not devices:
             logger.warning("No se encontraron dispositivos de entrada de audio.")
        return devices