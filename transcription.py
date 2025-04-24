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
        self.audio_interface = None # Inicializar a None
        try:
            logger.info("Inicializando RealTimeTranscriptionManager con PyAudio...")
            
            # Crear PyAudio Interface primero
            self.audio_interface = pyaudio.PyAudio()

            # Cargar modelo y traductor (pueden tardar o fallar)
            self.model = whisper.load_model("base")
            self.translator = Translator()
            
            self.source_lang = source_lang
            self.target_lang = target_lang
            
            # Configuración de PyAudio
            self.CHUNK = 1024 * 4
            self.FORMAT = pyaudio.paInt16 
            self.CHANNELS = 1
            self.RATE = 16000
            self.RECORD_SECONDS = 5
            
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