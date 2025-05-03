# pronunciation_practice.py
import sys
import pyaudio
import requests
import json
import wave
import tempfile
import os
import random
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QProgressBar, QMessageBox, QTextEdit, QFrame
)
from PySide6.QtCore import Qt, QTimer, Slot, Signal, QObject, QSize, QThread
from fuzzywuzzy import fuzz  # Para comparación de texto
from anki_integration import AnkiConnector

# Reutilizar TranscriptionManager para la transcripción
try:
    # Asumimos que transcription.py está en el mismo directorio o accesible
    from transcription import TranscriptionManager 
except ImportError:
    print("Error: No se pudo importar TranscriptionManager.")
    print("Asegúrate de que transcription.py esté en el mismo directorio o en el PYTHONPATH.")
    sys.exit(1)
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Worker para Tareas en Hilo Separado (Anki, Grabación, Transcripción) ---
# Esto evita que la GUI se congele durante operaciones largas
class WorkerSignals(QObject):
    card_fetched = Signal(str, str, str) # frase, card_id (como str), error_msg
    recording_done = Signal(str) # path_to_wav
    transcription_done = Signal(str, str) # transcribed_text, error_msg
    error = Signal(str) # Mensaje de error general

class PronunciationWorker(QObject):
    # Audio Recording Params
    CHUNK = 1024 * 2
    FORMAT = pyaudio.paInt16
    CHANNELS = 1
    RATE = 16000
    RECORD_DURATION_SECONDS = 5 # Duración fija por ahora

    def __init__(self, transcription_manager: TranscriptionManager, audio_interface: pyaudio.PyAudio):
        super().__init__()
        self.signals = WorkerSignals()
        self.transcription_manager = transcription_manager
        self.audio_interface = audio_interface
        self.current_card_id = None
        self.is_recording = False
        self.stream = None
        self.frames = []
        # Inicializar AnkiConnector
        self.anki_connector = AnkiConnector()

    @Slot()
    def fetch_card(self):
        logger.info("Worker: Buscando tarjetas en Anki...")
        success, result = self.anki_connector.find_due_cards()
        if not success:
            logger.error(f"Error al buscar tarjetas: {result}")
            self.signals.card_fetched.emit("", "-1", result)
            return
        card_ids = result
        if not card_ids:
            logger.info("No se encontraron tarjetas vencidas.")
            self.signals.card_fetched.emit("", "-1", f"No hay tarjetas para repasar en '{self.anki_connector.ANKI_DECK_NAME}'.")
            return
        # Selección aleatoria
        card_id = random.choice(card_ids)
        success, card_info = self.anki_connector.get_card_info(card_id)
        if not success:
            logger.error(f"Error al obtener información de tarjeta: {card_info}")
            self.signals.card_fetched.emit("", "-1", card_info)
            return
        phrase = card_info["fields"].get(self.anki_connector.ANKI_FRONT_FIELD, {}).get("value", "")
        if not phrase:
            logger.error(f"El campo '{self.anki_connector.ANKI_FRONT_FIELD}' está vacío en la tarjeta.")
            self.signals.card_fetched.emit("", "-1", f"El campo '{self.anki_connector.ANKI_FRONT_FIELD}' está vacío.")
            return
        logger.info(f"Tarjeta obtenida (ID: {card_id}): '{phrase}'")
        self.current_card_id = card_id
        self.signals.card_fetched.emit(phrase, str(card_id), "")

    @Slot()
    def start_recording(self):
        if self.is_recording:
            return
        
        logger.info("Worker: Iniciando grabación...")
        self.is_recording = True
        self.frames = []
        try:
            self.stream = self.audio_interface.open(format=self.FORMAT,
                                                    channels=self.CHANNELS,
                                                    rate=self.RATE,
                                                    input=True,
                                                    frames_per_buffer=self.CHUNK)
            
            # Grabar en un bucle corto o usar un temporizador
            for _ in range(0, int(self.RATE / self.CHUNK * self.RECORD_DURATION_SECONDS)):
                 if not self.is_recording: break # Permitir interrupción (aunque no implementada aquí)
                 try:
                      data = self.stream.read(self.CHUNK, exception_on_overflow=False)
                      self.frames.append(data)
                 except IOError as e:
                     logger.warning(f"IOError durante grabación: {e}")
                     break # Salir si hay error de stream

            logger.info("Worker: Grabación finalizada.")

        except Exception as e:
            logger.error(f"Error durante la grabación: {e}")
            self.signals.error.emit(f"Error de grabación: {e}")
        finally:
            self.is_recording = False
            if self.stream:
                try:
                    self.stream.stop_stream()
                    self.stream.close()
                except Exception as e:
                     logger.error(f"Error al cerrar stream: {e}")
                self.stream = None
            
            # Guardar audio grabado en archivo temporal WAV
            if self.frames:
                 self.save_recording()
            else:
                 logger.warning("No se grabaron frames.")
                 self.signals.error.emit("No se pudo grabar audio.")


    def save_recording(self):
         # Crear archivo WAV temporal
         with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_wav:
              wav_path = tmp_wav.name
              wf = wave.open(tmp_wav, 'wb')
              wf.setnchannels(self.CHANNELS)
              wf.setsampwidth(self.audio_interface.get_sample_size(self.FORMAT))
              wf.setframerate(self.RATE)
              wf.writeframes(b''.join(self.frames))
              wf.close()
              logger.info(f"Audio grabado guardado temporalmente en: {wav_path}")
              self.signals.recording_done.emit(wav_path) # Emitir ruta al archivo


    @Slot(str)
    def transcribe_audio_file(self, wav_path):
        logger.info(f"Worker: Transcribiendo archivo: {wav_path}")
        try:
            # Aquí necesitamos decidir el idioma. Por ahora, lo dejamos en 'auto'
            # Lo ideal sería saber el idioma de self.current_phrase
            language_to_transcribe = "auto" # O un idioma específico
            segments = self.transcription_manager.transcribe_audio(wav_path, language=language_to_transcribe)
            
            # Unir segmentos si Whisper los devuelve separados
            transcribed_text = " ".join([seg['text'] for seg in segments]).strip()
            
            logger.info(f"Transcripción: '{transcribed_text}'")
            self.signals.transcription_done.emit(transcribed_text, "") # Éxito

        except Exception as e:
            logger.error(f"Error durante la transcripción: {e}")
            self.signals.transcription_done.emit("", f"Error Transcripción: {e}")
        finally:
            # Eliminar archivo temporal
             if os.path.exists(wav_path):
                  try:
                       os.remove(wav_path)
                       logger.info(f"Archivo temporal eliminado: {wav_path}")
                  except Exception as e:
                       logger.error(f"Error al eliminar archivo temporal {wav_path}: {e}")


# --- GUI Principal ---
class PronunciationPracticeWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.current_phrase = ""
        self.current_card_id = "-1"
        self.audio_interface = pyaudio.PyAudio()
        # Crear una instancia del TranscriptionManager (carga el modelo)
        try:
             self.transcription_manager = TranscriptionManager()
        except Exception as e:
             QMessageBox.critical(self, "Error Crítico", f"No se pudo inicializar el modelo Whisper: {e}\nLa aplicación se cerrará.")
             sys.exit(1)

        self.init_ui()
        
        # Configurar Worker y QThread
        self.worker_thread = QThread() # Hilo contenedor
        self.worker = PronunciationWorker(self.transcription_manager, self.audio_interface)
        self.setup_worker_connections()


    def init_ui(self):
        self.setWindowTitle("SubStudy - Práctica de Pronunciación")
        self.setMinimumSize(500, 350)

        main_layout = QVBoxLayout(self)

        # --- Sección Tarjeta Anki ---
        anki_group = QFrame(); anki_group.setFrameShape(QFrame.StyledPanel)
        anki_layout = QVBoxLayout(anki_group)
        
        self.fetch_button = QPushButton("Obtener Siguiente Tarjeta de Anki")
        self.fetch_button.clicked.connect(self.request_fetch_card)

        self.phrase_label = QLabel("Presiona 'Obtener Tarjeta' para empezar.")
        self.phrase_label.setStyleSheet("font-size: 18pt; font-weight: bold; border: 1px solid #555; padding: 15px; background-color: #333; border-radius: 5px;")
        self.phrase_label.setAlignment(Qt.AlignCenter)
        self.phrase_label.setWordWrap(True)
        self.phrase_label.setTextInteractionFlags(Qt.TextSelectableByMouse) # Permitir seleccionar texto

        anki_layout.addWidget(self.fetch_button)
        anki_layout.addWidget(self.phrase_label)

        # --- Sección Grabación y Transcripción ---
        record_group = QFrame(); record_group.setFrameShape(QFrame.StyledPanel)
        record_layout = QVBoxLayout(record_group)

        self.record_button = QPushButton("🎤 Grabar Pronunciación (5s)")
        self.record_button.clicked.connect(self.request_recording)
        self.record_button.setEnabled(False)  # Deshabilitado hasta obtener tarjeta

        # Cambiar a QSize
        icon_size = QSize(self.record_button.fontMetrics().height() * 1.5, self.record_button.fontMetrics().height() * 1.5)
        self.record_button.setIconSize(icon_size)

        self.status_label = QLabel("Estado: Esperando tarjeta")
        self.status_label.setAlignment(Qt.AlignCenter)

        self.transcription_label = QLabel("Tu transcripción aparecerá aquí.")
        self.transcription_label.setStyleSheet("font-style: italic; color: #ccc; border: 1px dashed #666; padding: 10px; border-radius: 3px;")
        self.transcription_label.setAlignment(Qt.AlignCenter)
        self.transcription_label.setWordWrap(True)
        self.transcription_label.setTextInteractionFlags(Qt.TextSelectableByMouse)

        record_layout.addWidget(self.record_button)
        record_layout.addWidget(self.status_label)
        record_layout.addWidget(self.transcription_label)

        # --- Sección Puntuación ---
        score_group = QFrame(); score_group.setFrameShape(QFrame.StyledPanel)
        score_layout = QHBoxLayout(score_group)

        score_layout.addWidget(QLabel("Similitud:"))
        self.score_label = QLabel("N/A")
        self.score_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #4CAF50;") # Verde por defecto
        self.score_label.setAlignment(Qt.AlignCenter)
        score_layout.addWidget(self.score_label)
        score_layout.addStretch()


        # --- Ensamblar Layout Principal ---
        main_layout.addWidget(anki_group)
        main_layout.addWidget(record_group)
        main_layout.addWidget(score_group)
        
        self.setLayout(main_layout)

    def setup_worker_connections(self):
        # Conectar señales del worker a slots de la GUI
        self.worker.signals.card_fetched.connect(self.on_card_fetched)
        self.worker.signals.recording_done.connect(self.on_recording_done)
        self.worker.signals.transcription_done.connect(self.on_transcription_done)
        self.worker.signals.error.connect(self.on_worker_error)
        
        # Mover worker al hilo
        self.worker.moveToThread(self.worker_thread)
        
        # Conectar señal finished del hilo para limpieza (opcional pero bueno)
        self.worker_thread.finished.connect(self.worker.deleteLater) # Limpiar el worker cuando el hilo termine
        
        # Iniciar el hilo QThread
        self.worker_thread.start() # <--- Iniciar QThread
        logger.info("Hilo QThread del Worker iniciado.")


    # --- Slots que INICIAN acciones en el Worker ---
    @Slot()
    def request_fetch_card(self):
         logger.info("GUI: Solicitando fetch_card al worker...")
         self.fetch_button.setEnabled(False)
         self.record_button.setEnabled(False)
         self.status_label.setText("Buscando tarjeta en Anki...")
         self.phrase_label.setText("...")
         self.transcription_label.setText("...")
         self.score_label.setText("N/A")
         # Usar QTimer.singleShot para llamar al slot del worker en su hilo
         QTimer.singleShot(0, self.worker.fetch_card)

    @Slot()
    def request_recording(self):
        logger.info("GUI: Solicitando start_recording al worker...")
        self.record_button.setEnabled(False)
        self.fetch_button.setEnabled(False) # No buscar mientras graba
        self.status_label.setText("Grabando...")
        # Usar QTimer.singleShot para llamar al slot del worker en su hilo
        QTimer.singleShot(0, self.worker.start_recording)

    # --- Slots que RECIBEN resultados del Worker ---
    @Slot(str, str, str)
    def on_card_fetched(self, phrase: str, card_id_str: str, error_msg: str):
        logger.info("GUI: Recibido card_fetched.")
        self.fetch_button.setEnabled(True) # Habilitar botón para buscar otra
        if error_msg:
             self.status_label.setText("Error")
             self.phrase_label.setText(error_msg)
             self.record_button.setEnabled(False)
             self.current_card_id = "-1" # Usar string "-1"
             self.current_phrase = ""
        else:
             self.current_phrase = phrase
             self.current_card_id = card_id_str # Almacenar como string
             self.phrase_label.setText(phrase)
             self.status_label.setText("Tarjeta recibida. ¡Listo para grabar!")
             self.record_button.setEnabled(True) # Habilitar grabación
             self.transcription_label.setText("Tu transcripción aparecerá aquí.")
             self.score_label.setText("N/A")

    @Slot(str)
    def on_recording_done(self, wav_path):
         logger.info("GUI: Recibido recording_done. Solicitando transcripción...")
         self.status_label.setText("Grabación completada. Transcribiendo...")
         # Solicitar transcripción en el hilo del worker
         QTimer.singleShot(0, lambda: self.worker.transcribe_audio_file(wav_path))

    @Slot(str, str)
    def on_transcription_done(self, transcribed_text, error_msg):
        logger.info("GUI: Recibido transcription_done.")
        self.fetch_button.setEnabled(True) # Permitir buscar otra tarjeta
        self.record_button.setEnabled(True) # Permitir grabar de nuevo
        
        if error_msg:
            self.status_label.setText("Error de Transcripción")
            self.transcription_label.setText(error_msg)
            self.score_label.setText("Error")
        else:
            self.transcription_label.setText(transcribed_text if transcribed_text else "(No se detectó audio)")
            if transcribed_text and self.current_phrase:
                 self.compare_and_display_score(transcribed_text)
                 self.status_label.setText("¡Completo! Listo para la siguiente.")
            elif not transcribed_text:
                self.score_label.setText("N/A")
                self.status_label.setText("No se detectó audio. Intenta de nuevo.")
            else: # No había frase original?
                 self.score_label.setText("N/A")
                 self.status_label.setText("Error: No hay frase original para comparar.")

    @Slot(str)
    def on_worker_error(self, error_msg):
         logger.error(f"GUI: Recibido error general del worker: {error_msg}")
         self.status_label.setText(f"Error: {error_msg}")
         # Restaurar botones a un estado seguro
         self.fetch_button.setEnabled(True)
         self.record_button.setEnabled(bool(self.current_phrase)) # Habilitar si hay frase

    # --- Lógica de Comparación (en el hilo GUI) ---
    def compare_and_display_score(self, transcribed_text):
        if not self.current_phrase: return
        
        original_norm = self.current_phrase.lower().strip()
        transcribed_norm = transcribed_text.lower().strip()

        # Usar ratio simple de fuzzywuzzy (0-100)
        score = fuzz.ratio(original_norm, transcribed_norm) 
        logger.info(f"Comparación: '{original_norm}' vs '{transcribed_norm}' -> Score: {score}")
        
        self.score_label.setText(f"{score}%")
        
        # Cambiar color según puntuación
        if score >= 85:
            self.score_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #4CAF50;") # Verde
        elif score >= 60:
            self.score_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #FFC107;") # Amarillo/Naranja
        else:
            self.score_label.setStyleSheet("font-size: 16pt; font-weight: bold; color: #F44336;") # Rojo

    # --- Manejo del cierre ---
    def closeEvent(self, event):
        logger.info("Cerrando ventana de práctica...")
        if self.worker_thread.isRunning():
             logger.info("Solicitando finalización del hilo QThread...")
             self.worker_thread.quit() # Solicita al bucle de eventos del hilo que termine
             if not self.worker_thread.wait(1500): # Esperar máx 1.5s
                  logger.warning("El hilo del worker no terminó limpiamente. Forzando terminación (puede ser inseguro).")
                  # self.worker_thread.terminate() # Descomentar solo como último recurso
             else:
                  logger.info("Hilo QThread finalizado.")

        if self.audio_interface:
            try: self.audio_interface.terminate()
            except Exception as e: logger.error(f"Error al terminar PyAudio: {e}")
        
        event.accept()

# --- Punto de Entrada ---
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = PronunciationPracticeWindow()
    window.show()
    sys.exit(app.exec())