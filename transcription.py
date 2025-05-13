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
import subprocess

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def check_ffmpeg():
    """Verifica si ffmpeg está instalado y accesible en el PATH."""
    try:
        result = subprocess.run(['ffmpeg', '-version'], capture_output=True, text=True)
        if result.returncode == 0:
            # Configurar pydub para usar ffmpeg si es necesario
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
        self.audio_interface = None # Inicializar a None
        try:
            logger.info("Inicializando RealTimeTranscriptionManager con PyAudio...")
            
            # Crear PyAudio Interface primero
            self.audio_interface = pyaudio.PyAudio()

            # Cargar modelo y traductor
            self.model = whisper.load_model("base")
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
            # Asegurarse de terminar PyAudio si se creó pero algo más falló
            if self.audio_interface:
                try:
                    self.audio_interface.terminate()
                    logger.info("Interfaz de PyAudio terminada debido a error de inicialización.")
                except Exception as term_error:
                     logger.error(f"Error al terminar PyAudio durante manejo de error inicial: {term_error}")
            raise # Relanzar la excepción original
            
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

    def _process_audio(self):
        """Consume datos de la cola de audio, transcribe y traduce."""
        logger.info("Iniciando procesamiento de la cola de audio...")
        audio_buffer = []
        frames_to_process = int(self.RATE / self.CHUNK * self.RECORD_SECONDS)
        
        while self.is_running:
            try:
                # Esperar datos en la cola
                chunk = self.audio_queue.get(timeout=1) # Esperar 1 segundo
                audio_buffer.append(chunk)
                
                if len(audio_buffer) >= frames_to_process:
                    # Unir los chunks del buffer
                    raw_data = b''.join(audio_buffer)
                    audio_buffer = [] # Limpiar buffer para el siguiente ciclo
                    
                    # Convertir a formato numpy float32 (requerido por Whisper)
                    audio_np = np.frombuffer(raw_data, dtype=np.int16).astype(np.float32) / 32768.0
                    
                    if audio_np.size > 0:
                        logger.info(f"Procesando {len(raw_data)/2/self.RATE:.2f} segundos de audio...")
                        # Transcribir el audio acumulado
                        options = {
                            "language": self.source_lang if self.source_lang != "auto" else None,
                            "task": "transcribe",
                            "fp16": torch.cuda.is_available()
                        }
                        
                        result = self.model.transcribe(audio_np, **options)
                        
                        if result and result["text"].strip():
                            logger.info(f"Transcripción: {result['text']}")
                            
                            # Procesar cada segmento detectado
                            # Whisper puede devolver un solo texto o segmentos
                            if "segments" in result and result["segments"]:
                                for segment in result["segments"]:
                                    text = segment["text"].strip()
                                    if text:
                                        # Traducir el texto
                                        translation = self.translator.translate(text, dest=self.target_lang)
                                        
                                        # Añadir a la cola de subtítulos
                                        # Nota: Los timestamps de Whisper en trozos cortos pueden no ser precisos
                                        # o relativos al inicio del chunk, no al inicio global.
                                        # Para tiempo real simple, podemos omitir start/end o usar un contador.
                                        self.subtitle_queue.put({
                                            "text": text,
                                            "translation": translation.text,
                                            "start": time.time(), # Usar tiempo actual como referencia simple
                                            "end": time.time() + 5 # Duración estimada
                                        })
                                        logger.info(f"Traducción: {translation.text}")
                            else: # Si no hay segmentos, usar el texto completo
                                 text = result["text"].strip()
                                 if text:
                                     translation = self.translator.translate(text, dest=self.target_lang)
                                     self.subtitle_queue.put({
                                          "text": text,
                                          "translation": translation.text,
                                          "start": time.time(),
                                          "end": time.time() + 5
                                     })
                                     logger.info(f"Traducción: {translation.text}")

                    # Limpiar la cola para evitar acumulación si el procesamiento es lento
                    while not self.audio_queue.empty():
                        try:
                            self.audio_queue.get_nowait()
                        except queue.Empty:
                            break
                            
            except queue.Empty:
                # No hay datos en la cola, continuar esperando
                continue
            except Exception as e:
                logger.error(f"Error en el procesamiento de audio: {e}")
                # Pausar brevemente para evitar bucles de error rápidos
                time.sleep(0.1)
        
        logger.info("Procesamiento de audio finalizado.")

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

class TranscriptionManager:
    def __init__(self):
        try:
            logger.info("Inicializando modelo Whisper...")
            # Usar el modelo base que es más rápido y requiere menos recursos
            self.model = whisper.load_model("medium")
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