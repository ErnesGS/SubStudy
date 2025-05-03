import sys
import pyaudio
import requests
import json
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QComboBox, QSpacerItem, QSizePolicy, QFrame, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QPoint, Slot, QEvent, Signal
from PySide6.QtGui import QMouseEvent, QPalette, QColor, QFontMetrics
from anki_integration import AnkiConnector

# Asegúrate de que transcription.py esté accesible
try:
    from transcription import RealTimeTranscriptionManager
except ImportError:
    print("Error: No se pudo importar RealTimeTranscriptionManager.")
    print("Asegúrate de que transcription.py esté en el mismo directorio o en el PYTHONPATH.")
    sys.exit(1)
import logging # Usar el mismo logger si se desea

logger = logging.getLogger(__name__)

# Clase QLabel Personalizada para detectar Hover y emitir señal
class HoverLabel(QLabel):
    # Definir la señal (fuera de __init__)
    hoverChanged = Signal(bool) 

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True)
        self._hovering = False

    def enterEvent(self, event: QEvent):
        if not self._hovering:
            logger.debug("HoverLabel: Enter")
            self._hovering = True
            # Emitir señal indicando que el hover ha comenzado
            self.hoverChanged.emit(True) 
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        if self._hovering:
            logger.debug("HoverLabel: Leave")
            self._hovering = False
            # Emitir señal indicando que el hover ha terminado
            self.hoverChanged.emit(False) 
        super().leaveEvent(event)

class SubtitleLineLabel(QLabel):
    hovered = Signal(object)  # Emite el subtítulo (dict) al hacer hover
    rightClicked = Signal(object)  # Emite el subtítulo (dict) al click derecho
    unhovered = Signal()  # NUEVO: señal para cuando el ratón sale

    def __init__(self, subtitle, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.subtitle = subtitle
        self.setMouseTracking(True)
        self.setText(subtitle["text"])
        self.setStyleSheet("font-size:16pt;font-weight:bold;color:white;")
        self.setAlignment(Qt.AlignCenter)

    def enterEvent(self, event):
        self.hovered.emit(self.subtitle)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.unhovered.emit()  # NUEVO: emitir señal al salir
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.rightClicked.emit(self.subtitle)
        super().mousePressEvent(event)

# --- NUEVA CLASE PARA EL POPUP DE TRADUCCIÓN ---
class TranslationPopup(QWidget):
    addToAnkiClicked = Signal(object)  # Emite el subtítulo (dict) al pulsar el botón

    def __init__(self, parent=None):
        super().__init__(parent)
        # Flags: Tooltip (ayuda a auto-ocultarse), sin bordes, siempre encima
        self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground) # Fondo transparente para la ventana
        self.setAttribute(Qt.WA_DeleteOnClose) # Borrar al cerrar (aunque la ocultaremos)

        # Layout y Etiqueta interna
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0) # Sin márgenes para el layout

        # Frame interno para el fondo coloreado y bordes redondeados
        self.frame = QFrame(self)
        self.frame.setStyleSheet("""
            QFrame {
                background-color: rgba(40, 40, 40, 0.9); /* Fondo oscuro semitransparente */
                border-radius: 5px;
                padding: 5px 8px; /* Padding interno */
            }
        """)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(0,0,0,0)

        self.label = QLabel("Translation", self.frame) # Padre es el frame
        self.label.setStyleSheet("color: #dddddd; font-size: 12pt; background-color: transparent;") # Texto claro
        self.label.setWordWrap(True)
        
        frame_layout.addWidget(self.label) # Añadir label al layout del frame
        self.anki_button = QPushButton("Añadir a Anki", self.frame)
        self.anki_button.setStyleSheet("background-color: #40b040; color: white; border-radius: 4px;")
        self.anki_button.clicked.connect(self._emit_add_to_anki)
        frame_layout.addWidget(self.anki_button)
        layout.addWidget(self.frame)
        self.current_subtitle = None

    def setSubtitle(self, subtitle):
        self.current_subtitle = subtitle
        self.label.setText(f'({subtitle["translation"]})')
        self.adjustSize()

    def showAt(self, position: QPoint):
        """Mueve el popup a la posición global y lo muestra."""
        self.move(position)
        self.show()

    def _emit_add_to_anki(self):
        if self.current_subtitle:
            self.addToAnkiClicked.emit(self.current_subtitle)

# Clase Principal Modificada
class SubtitleOverlayWindow(QWidget):
    SUBTITLE_DURATION = 4  # segundos que permanece cada subtítulo
    MAX_SUBTITLES = 5      # máximo de subtítulos en pantalla

    def __init__(self):
        super().__init__()
        self.rt_manager = None
        self.audio_interface = pyaudio.PyAudio() # Interfaz para listar dispositivos
        self._offset = None # Para arrastrar la ventana
        self.current_original = "" # Almacenar texto actual
        self.current_translation = "" # Almacenar traducción actual
        
        # Inicializar AnkiConnector
        self.anki_connector = AnkiConnector()
        
        # --- Crear instancia del Popup ---
        self.translation_popup = TranslationPopup() 
        self.active_subtitles = []  # Lista de dicts: {"text", "translation", "timestamp"}
        self.subtitle_labels = []  # NUEVO: lista de labels de línea
        self.translation_popup.addToAnkiClicked.connect(self.add_subtitle_to_anki)

        self.init_ui()
        self.populate_audio_devices()
        
        # Timer para actualizar subtítulos
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_subtitles_display)
        self.update_interval_ms = 150 # Reducido desde 300 

    def init_ui(self):
        self.setWindowTitle("SubStudy Overlay")
        
        # --- Configuración de la ventana ---
        self.setWindowFlags(Qt.FramelessWindowHint | # Sin bordes
                            Qt.WindowStaysOnTopHint |  # Siempre encima
                            Qt.Tool)                 # Evita aparecer en la barra de tareas (opcional)
        self.setAttribute(Qt.WA_TranslucentBackground) # Fondo transparente

        # --- Layout Principal ---
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0) # Sin márgenes externos

        # --- Frame para contenido (con fondo semitransparente) ---
        self.content_frame = QFrame(self)
        self.content_frame.setObjectName("contentFrame") # Para aplicar estilos
        # Estilo básico para visualización
        self.content_frame.setStyleSheet("""
            #contentFrame {
                background-color: rgba(20, 20, 20, 0.85); /* Negro semitransparente */
                border-radius: 10px;
            }
            QLabel { /* Estilo base para todas las etiquetas dentro */
                color: white;
                padding: 2px 5px; /* Añadir padding pequeño */
            }
        """)
        self.frame_layout = QVBoxLayout(self.content_frame)
        self.frame_layout.setContentsMargins(15, 10, 15, 10) # Márgenes internos

        # --- Controles (dentro del frame) ---
        controls_layout = QHBoxLayout()
        
        # Idiomas
        self.source_lang_combo = QComboBox()
        self.source_lang_combo.addItems(["es", "en", "pt", "fr", "de", "it", "auto"])
        self.source_lang_combo.setToolTip("Idioma del audio original")

        self.target_lang_combo = QComboBox()
        self.target_lang_combo.addItems(["es", "en", "fr", "de", "it", "pt"])
        self.target_lang_combo.setCurrentText("es") # Predeterminado
        self.target_lang_combo.setToolTip("Idioma al que traducir")
        
        # Dispositivo de Audio
        self.audio_device_combo = QComboBox()
        self.audio_device_combo.setToolTip("Dispositivo de entrada de audio")
        
        controls_layout.addWidget(QLabel("Fuente:"))
        controls_layout.addWidget(self.source_lang_combo)
        controls_layout.addWidget(QLabel("Traducir a:"))
        controls_layout.addWidget(self.target_lang_combo)
        controls_layout.addWidget(QLabel("Micrófono:"))
        controls_layout.addWidget(self.audio_device_combo, 1) # Darle más espacio si es necesario

        # Botones Start/Stop
        self.start_button = QPushButton("Iniciar")
        self.start_button.clicked.connect(self.start_capture)
        self.stop_button = QPushButton("Detener")
        self.stop_button.clicked.connect(self.stop_capture)
        self.stop_button.setEnabled(False) # Deshabilitado inicialmente

        # --- NUEVO: Botón Enviar a Anki ---
        self.anki_button = QPushButton("Añadir a Anki")
        self.anki_button.clicked.connect(self.send_to_anki)
        self.anki_button.setToolTip(f"Enviar a Anki (Mazo: {self.ANKI_DECK_NAME}, Modelo: {self.ANKI_MODEL_NAME})")
        self.anki_button.setEnabled(False) # Deshabilitado inicialmente

        # --- NUEVO: Botón Cerrar ---
        self.close_button = QPushButton("X") # Botón simple de cierre
        self.close_button.setToolTip("Cerrar aplicación")
        self.close_button.setFixedWidth(30) # Hacerlo pequeño
        self.close_button.setStyleSheet("QPushButton { color: white; background-color: #555555; border-radius: 5px; } QPushButton:hover { background-color: #cc0000; }")
        self.close_button.clicked.connect(self.close) # Conectar a self.close

        # Añadir botones al layout
        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)
        controls_layout.addWidget(self.anki_button) # Añadir botón Anki
        controls_layout.addWidget(self.close_button) # Añadir botón Cerrar

        # --- Layout para Subtítulos (Original y Traducción) ---
        self.subtitles_layout = QVBoxLayout()
        self.subtitles_layout.setSpacing(0) # Sin espacio entre original y traducción

        # Etiqueta para Texto Original (ahora es HoverLabel)
        # Pasamos self.content_frame como padre para que HoverLabel pueda llamar a show_translation
        self.original_label = None  # Ya no se usa como antes

        # Añadir etiquetas al layout de subtítulos
        self.frame_layout.addLayout(controls_layout)
        self.frame_layout.addLayout(self.subtitles_layout)
        
        main_layout.addWidget(self.content_frame) # Añadir el frame al layout principal
        self.setLayout(main_layout)

        # Tamaño inicial (ajustable)
        self.resize(700, 150) 

    def show_critical_error(self, message, exception=None):
        """Muestra un error crítico y lo registra."""
        if exception:
            logger.error(f"{message}: {exception}")
        else:
            logger.error(message)
        QMessageBox.critical(self, "Error crítico", message)

    def populate_audio_devices(self):
        self.audio_device_combo.clear()
        try:
            info = self.audio_interface.get_host_api_info_by_index(0)
            numdevices = info.get('deviceCount')
            default_device_index = -1
            try:
                default_info = self.audio_interface.get_default_input_device_info()
                default_device_index = default_info['index']
            except IOError:
                logger.warning("No se pudo obtener el dispositivo de entrada por defecto.")

            for i in range(0, numdevices):
                device_info = self.audio_interface.get_device_info_by_host_api_device_index(0, i)
                if device_info.get('maxInputChannels') > 0:
                    device_name = f"({i}) {device_info.get('name')}"
                    self.audio_device_combo.addItem(device_name, userData=i)
                    if i == default_device_index:
                        self.audio_device_combo.setCurrentIndex(self.audio_device_combo.count() - 1)
        except Exception as e:
            self.show_critical_error("Error al listar dispositivos de audio", e)

    @Slot() # Decorador opcional pero bueno para claridad
    def start_capture(self):
        if self.rt_manager is not None:
            logger.warning("Intento de iniciar captura cuando ya está activa.")
            return

        source_lang = self.source_lang_combo.currentText()
        target_lang = self.target_lang_combo.currentText()
        device_index = self.audio_device_combo.currentData() # Obtener índice desde userData

        if device_index is None:
            self.show_status_message("Error: ¡Selecciona un dispositivo de audio!", color="red")
            logger.error("No se seleccionó un dispositivo de audio.")
            return

        try:
            logger.info(f"Iniciando captura: Src={source_lang}, Tgt={target_lang}, Device={device_index}")
            self.show_status_message("Iniciando...", color="orange")
            QApplication.processEvents() # Forzar actualización de la etiqueta

            # Crear e iniciar el manager
            self.rt_manager = RealTimeTranscriptionManager(source_lang, target_lang)
            self.rt_manager.start_processing(input_device_index=device_index)
            
            # Iniciar timer para obtener subtítulos
            self.update_timer.start(self.update_interval_ms)
            
            # Actualizar estado de la UI
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.anki_button.setEnabled(False) # Asegurar que Anki esté deshabilitado al inicio
            self.close_button.setEnabled(True) # El botón de cerrar siempre activo
            self.source_lang_combo.setEnabled(False)
            self.target_lang_combo.setEnabled(False)
            self.audio_device_combo.setEnabled(False)
            self.show_status_message("Escuchando...", color="green")
            logger.info("Captura iniciada y timer activado.")

        except Exception as e:
            logger.error(f"Error al iniciar RealTimeTranscriptionManager: {e}")
            self.show_status_message(f"Error al iniciar: {e}", color="red")
            self.rt_manager = None # Asegurarse de que está None si falla
            # Restaurar estado botones si falla
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
            self.anki_button.setEnabled(False)
            self.source_lang_combo.setEnabled(True)
            self.target_lang_combo.setEnabled(True)
            self.audio_device_combo.setEnabled(True)

    @Slot()
    def stop_capture(self):
        logger.info("Deteniendo captura...")
        self.update_timer.stop() # Detener el timer primero

        if self.rt_manager:
            try:
                self.rt_manager.stop_processing()
            except Exception as e:
                 logger.error(f"Error durante stop_processing: {e}")
            finally:
                 self.rt_manager = None # Liberar la instancia

        # Actualizar estado de la UI
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.anki_button.setEnabled(False) # Deshabilitar Anki al detener
        self.close_button.setEnabled(True)
        self.source_lang_combo.setEnabled(True)
        self.target_lang_combo.setEnabled(True)
        self.audio_device_combo.setEnabled(True)
        # Limpiar etiquetas y estado hover
        self.show_status_message("...")
        self.current_original = ""
        self.current_translation = ""
        logger.info("Captura detenida.")

    @Slot()
    def update_subtitles_display(self):
        import time
        now = time.time()
        # Eliminar subtítulos antiguos
        self.active_subtitles = [
            s for s in self.active_subtitles
            if now - s["timestamp"] < self.SUBTITLE_DURATION
        ]
        # Añadir nuevo subtítulo si hay uno nuevo
        if self.rt_manager and self.rt_manager.is_running:
            try:
                subtitles = self.rt_manager.get_subtitles()
                for sub in subtitles:
                    # Evitar duplicados exactos consecutivos
                    if not self.active_subtitles or sub['text'] != self.active_subtitles[-1]['text']:
                        self.active_subtitles.append({
                            "text": sub['text'],
                            "translation": sub['translation'],
                            "timestamp": now
                        })
                # Limitar el número de subtítulos activos
                if len(self.active_subtitles) > self.MAX_SUBTITLES:
                    self.active_subtitles = self.active_subtitles[-self.MAX_SUBTITLES:]
            except Exception as e:
                logger.error(f"Error al obtener/mostrar subtítulos: {e}")

        # --- ACTUALIZAR SUBTÍTULOS EN PANTALLA ---
        # Eliminar labels antiguos
        for label in self.subtitle_labels:
            label.deleteLater()
        self.subtitle_labels = []

        # Añadir nuevos labels
        for s in self.active_subtitles:
            label = SubtitleLineLabel(s, self.content_frame)
            label.hovered.connect(self.show_translation_popup_for_line)
            label.rightClicked.connect(self.show_popup_and_add_to_anki)
            label.unhovered.connect(self.hide_translation_popup)  # NUEVO: conectar señal
            self.subtitles_layout.addWidget(label)
            self.subtitle_labels.append(label)

    @Slot(object)
    def show_translation_popup_for_line(self, subtitle):
        # Mostrar el popup encima de la línea correspondiente
        sender = self.sender()
        if isinstance(sender, SubtitleLineLabel):
            self.translation_popup.setSubtitle(subtitle)
            label_pos = sender.mapToGlobal(QPoint(0, 0))
            popup_height = self.translation_popup.height()
            label_width = sender.width()
            popup_width = self.translation_popup.width()
            popup_x = label_pos.x() + (label_width - popup_width) // 2
            popup_y = label_pos.y() - popup_height - 5
            if popup_y < 0:
                popup_y = label_pos.y() + sender.height() + 5
            self.translation_popup.showAt(QPoint(popup_x, popup_y))
        else:
            self.translation_popup.hide()

    @Slot(object)
    def show_popup_and_add_to_anki(self, subtitle):
        # Enviar directamente a Anki al hacer click derecho
        self.add_subtitle_to_anki(subtitle)
        # (Opcional) Mostrar el popup también:
        self.show_translation_popup_for_line(subtitle)

    @Slot(object)
    def add_subtitle_to_anki(self, subtitle):
        # Lógica para añadir a Anki usando los datos del subtítulo
        self.current_original = subtitle["text"]
        self.current_translation = subtitle["translation"]
        self.send_to_anki()

    # --- Métodos para arrastrar la ventana (MODIFICADOS) ---
    def mousePressEvent(self, event: QMouseEvent):
        # Comprobar si el clic fue en el frame y no en un control hijo interactivo
        target_widget = self.childAt(event.position().toPoint())
        interactive_widgets = (QPushButton, QComboBox) # Widgets que no deben iniciar arrastre
        
        # Si el clic NO es en un botón o combobox (o es directamente en el frame)
        # Y es el botón izquierdo...
        if event.button() == Qt.LeftButton and \
           (target_widget is None or target_widget == self.content_frame or \
            not isinstance(target_widget, interactive_widgets)):
            
            self._offset = event.position().toPoint()
            logger.debug(f"Mouse Press - Offset: {self._offset}")
        else:
            # Si se hizo clic en un control, pasar el evento
            super().mousePressEvent(event)
            # Asegurarse de que no iniciemos un arrastre si el clic fue en un control
            self._offset = None 

    def mouseMoveEvent(self, event: QMouseEvent):
        if self._offset is not None and event.buttons() & Qt.LeftButton:
            new_global_pos = event.globalPosition().toPoint() - self._offset
            logger.debug(f"Mouse Move - Global Cursor: {event.globalPosition().toPoint()}, New Global Pos: {new_global_pos}")
            self.move(new_global_pos)
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton and self._offset is not None:
            logger.debug("Mouse Release - Clearing offset")
            self._offset = None
        super().mouseReleaseEvent(event)

    # --- Manejo del cierre (MODIFICADO) ---
    def closeEvent(self, event):
        logger.info("Evento de cierre detectado.")
        self.stop_capture() # Asegurarse de detener todo

        # Terminar PyAudio global si ya no se necesita
        if self.audio_interface:
            try:
                self.audio_interface.terminate()
                logger.info("Interfaz PyAudio global terminada.")
            except Exception as e:
                logger.error(f"Error al terminar PyAudio global en closeEvent: {e}")
            finally:
                self.audio_interface = None
        
        # Ocultar y cerrar el popup explícitamente
        if self.translation_popup:
            self.translation_popup.close() 

        logger.info("Aceptando evento de cierre...")
        event.accept() # Aceptar el cierre de la ventana

        # --- DESCOMENTAR ESTA LÍNEA ---
        # Forzar la salida del bucle de eventos principal de Qt.
        logger.info("Forzando salida de la aplicación Qt.")
        QApplication.instance().quit() 
        # -----------------------------

    # --- NUEVO SLOT PARA ENVIAR A ANKI ---
    @Slot()
    def send_to_anki(self):
        if not self.current_original or not self.current_translation:
            logger.warning("Intento de enviar a Anki sin datos válidos.")
            self.show_error_message("No hay subtítulo actual para enviar.")
            return

        logger.info(f"Enviando a Anki: '{self.current_original}' / '{self.current_translation}'")
        
        # Usar el AnkiConnector
        success, message = self.anki_connector.add_note(
            self.current_original, 
            self.current_translation,
            tags=["substudy", "realtime"]
        )
        
        if success:
            # Mostrar mensaje de éxito temporal en el botón
            self.show_temporary_message("¡Enviado a Anki!", is_error=False)
        else:
            # Mostrar mensaje de error
            self.show_error_message(message)

    # --- Funciones auxiliares para mensajes ---
    def show_error_message(self, message):
        """Muestra un diálogo de error modal."""
        QMessageBox.warning(self, "Error", message)

    def show_temporary_message(self, message, duration_ms=2000, is_error=False):
        """Muestra un mensaje temporal en el botón de Anki."""
        original_text = self.anki_button.text()
        original_stylesheet = self.anki_button.styleSheet()
        
        self.anki_button.setEnabled(False) # Deshabilitar mientras muestra mensaje
        self.anki_button.setText(message)
        if is_error:
             self.anki_button.setStyleSheet("background-color: #b04040; color: white;") # Rojo para error
        else:
             self.anki_button.setStyleSheet("background-color: #40b040; color: white;") # Verde para éxito

        # Timer para restaurar el botón
        QTimer.singleShot(duration_ms, lambda: self.restore_anki_button(original_text, original_stylesheet))

    def restore_anki_button(self, original_text, original_stylesheet):
        """Restaura el texto y estilo del botón Anki."""
        if self.anki_button: # Comprobar si aún existe
            self.anki_button.setText(original_text)
            self.anki_button.setStyleSheet(original_stylesheet)
            # Volver a habilitar solo si hay texto actual
            self.anki_button.setEnabled(bool(self.current_original) and self.stop_button.isEnabled())

    def show_status_message(self, message, color="orange"):
        # Elimina labels antiguos
        for label in self.subtitle_labels:
            label.deleteLater()
        self.subtitle_labels = []
        # Crea un label temporal para el mensaje
        label = QLabel(message, self.content_frame)
        label.setStyleSheet(f"font-size:14pt;font-weight:bold;color:{color};")
        label.setAlignment(Qt.AlignCenter)
        self.subtitles_layout.addWidget(label)
        self.subtitle_labels.append(label)

    @Slot()
    def hide_translation_popup(self):
        self.translation_popup.hide()

# --- Punto de Entrada ---
if __name__ == "__main__":
    # Configurar logging si es necesario
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    app = QApplication(sys.argv)
    window = SubtitleOverlayWindow()
    window.show()
    # app.exec() devolverá un código de salida cuando quit() sea llamado
    exit_code = app.exec() 
    logger.info(f"Saliendo de la aplicación con código: {exit_code}")
    sys.exit(exit_code)