import sys
import pyaudio
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QLabel, 
    QPushButton, QComboBox, QSpacerItem, QSizePolicy, QFrame
)
from PySide6.QtCore import Qt, QTimer, QPoint, Slot, QEvent
from PySide6.QtGui import QMouseEvent, QPalette, QColor

# Asegúrate de que transcription.py esté accesible
try:
    from transcription import RealTimeTranscriptionManager
except ImportError:
    print("Error: No se pudo importar RealTimeTranscriptionManager.")
    print("Asegúrate de que transcription.py esté en el mismo directorio o en el PYTHONPATH.")
    sys.exit(1)
import logging # Usar el mismo logger si se desea

logger = logging.getLogger(__name__)

# Clase QLabel Personalizada para detectar Hover fácilmente
class HoverLabel(QLabel):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setMouseTracking(True) # Necesario para recibir eventos move sin presionar botón
        self._hovering = False

    def enterEvent(self, event: QEvent):
        if not self._hovering:
            logger.debug("HoverLabel: Enter")
            self._hovering = True
            # Aquí podríamos emitir una señal si quisiéramos desacoplar más
            # Por ahora, podemos llamar a un método del padre directamente si es simple
            if hasattr(self.parentWidget(), 'show_translation'):
                 self.parentWidget().show_translation(True)
        super().enterEvent(event)

    def leaveEvent(self, event: QEvent):
        if self._hovering:
            logger.debug("HoverLabel: Leave")
            self._hovering = False
            if hasattr(self.parentWidget(), 'show_translation'):
                 self.parentWidget().show_translation(False)
        super().leaveEvent(event)


class SubtitleOverlayWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.rt_manager = None
        self.audio_interface = pyaudio.PyAudio() # Interfaz para listar dispositivos
        self._offset = None # Para arrastrar la ventana
        self.current_original = "" # Almacenar texto actual
        self.current_translation = "" # Almacenar traducción actual

        self.init_ui()
        self.populate_audio_devices()
        
        # Timer para actualizar subtítulos
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_subtitles_display)
        self.update_interval_ms = 300 # Milisegundos (ajustable)

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
        frame_layout = QVBoxLayout(self.content_frame)
        frame_layout.setContentsMargins(15, 10, 15, 10) # Márgenes internos

        # --- Controles (dentro del frame) ---
        controls_layout = QHBoxLayout()
        
        # Idiomas
        self.source_lang_combo = QComboBox()
        self.source_lang_combo.addItems(["auto", "en", "es", "fr", "de", "it", "pt"])
        self.source_lang_combo.setToolTip("Idioma del audio original")

        self.target_lang_combo = QComboBox()
        self.target_lang_combo.addItems(["es", "en", "fr", "de", "it", "pt"])
        self.target_lang_combo.setCurrentText("en") # Predeterminado
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

        controls_layout.addWidget(self.start_button)
        controls_layout.addWidget(self.stop_button)

        # --- Layout para Subtítulos (Original y Traducción) ---
        subtitles_layout = QVBoxLayout()
        subtitles_layout.setSpacing(0) # Sin espacio entre original y traducción

        # Etiqueta para Texto Original (ahora es HoverLabel)
        # Pasamos self.content_frame como padre para que HoverLabel pueda llamar a show_translation
        self.original_label = HoverLabel(self.content_frame)
        self.original_label.setText("...")
        self.original_label.setAlignment(Qt.AlignCenter)
        self.original_label.setWordWrap(True)
        self.original_label.setStyleSheet("font-size: 16pt; font-weight: bold; padding-bottom: 0px;") # Negrita y sin padding inferior
        self.original_label.setMinimumHeight(40) # Ajustar altura mínima

        # Etiqueta para Traducción (inicialmente oculta)
        self.translation_label = QLabel(self.content_frame) # Padre es el frame
        self.translation_label.setText("")
        self.translation_label.setAlignment(Qt.AlignCenter)
        self.translation_label.setWordWrap(True)
        self.translation_label.setStyleSheet("font-size: 14pt; font-style: italic; color: #cccccc; padding-top: 0px;") # Gris claro, cursiva
        self.translation_label.setVisible(False) # Oculta por defecto
        self.translation_label.setMinimumHeight(35) # Altura mínima

        # Añadir etiquetas al layout de subtítulos
        subtitles_layout.addWidget(self.original_label)
        subtitles_layout.addWidget(self.translation_label)

        # Añadir layout de subtítulos al layout del frame
        frame_layout.addLayout(controls_layout)
        frame_layout.addLayout(subtitles_layout)
        
        main_layout.addWidget(self.content_frame) # Añadir el frame al layout principal
        self.setLayout(main_layout)

        # Tamaño inicial (ajustable)
        self.resize(600, 200) 

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
                    self.audio_device_combo.addItem(device_name, userData=i) # Guardar índice en userData
                    if i == default_device_index:
                         self.audio_device_combo.setCurrentIndex(self.audio_device_combo.count() - 1)

        except Exception as e:
            logger.error(f"Error al listar dispositivos de audio: {e}")
            self.original_label.setText(f"Error audio: {e}")

    @Slot() # Decorador opcional pero bueno para claridad
    def start_capture(self):
        if self.rt_manager is not None:
            logger.warning("Intento de iniciar captura cuando ya está activa.")
            return

        source_lang = self.source_lang_combo.currentText()
        target_lang = self.target_lang_combo.currentText()
        device_index = self.audio_device_combo.currentData() # Obtener índice desde userData

        if device_index is None:
            self.original_label.setText("Error: ¡Selecciona un dispositivo de audio!")
            logger.error("No se seleccionó un dispositivo de audio.")
            return

        try:
            logger.info(f"Iniciando captura: Src={source_lang}, Tgt={target_lang}, Device={device_index}")
            self.original_label.setText("Iniciando...")
            QApplication.processEvents() # Forzar actualización de la etiqueta

            # Crear e iniciar el manager
            self.rt_manager = RealTimeTranscriptionManager(source_lang, target_lang)
            self.rt_manager.start_processing(input_device_index=device_index)
            
            # Iniciar timer para obtener subtítulos
            self.update_timer.start(self.update_interval_ms)
            
            # Actualizar estado de la UI
            self.start_button.setEnabled(False)
            self.stop_button.setEnabled(True)
            self.source_lang_combo.setEnabled(False)
            self.target_lang_combo.setEnabled(False)
            self.audio_device_combo.setEnabled(False)
            self.original_label.setText("Escuchando...")
            logger.info("Captura iniciada y timer activado.")

        except Exception as e:
            logger.error(f"Error al iniciar RealTimeTranscriptionManager: {e}")
            self.original_label.setText(f"Error al iniciar: {e}")
            self.rt_manager = None # Asegurarse de que está None si falla
            # Restaurar estado botones si falla
            self.start_button.setEnabled(True)
            self.stop_button.setEnabled(False)
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
        self.source_lang_combo.setEnabled(True)
        self.target_lang_combo.setEnabled(True)
        self.audio_device_combo.setEnabled(True)
        # Limpiar etiquetas y estado hover
        self.original_label.setText("...")
        self.translation_label.setText("")
        self.translation_label.setVisible(False)
        self.current_original = ""
        self.current_translation = ""
        logger.info("Captura detenida.")

    @Slot()
    def update_subtitles_display(self):
        if self.rt_manager and self.rt_manager.is_running:
            try:
                subtitles = self.rt_manager.get_subtitles() # Obtener todos los nuevos
                if subtitles:
                    # Mostrar el último subtítulo recibido
                    last_sub = subtitles[-1] 
                    self.current_original = last_sub['text']
                    self.current_translation = last_sub['translation']
                    
                    # Actualizar texto original (visible siempre)
                    self.original_label.setText(self.current_original)
                    
                    # Actualizar texto de traducción (aunque esté oculta)
                    self.translation_label.setText(f"({self.current_translation})")

                    # Si el ratón está AHORA MISMO sobre la etiqueta original,
                    # asegurarse de que la traducción sea visible.
                    # Esto maneja el caso donde llega un nuevo subtítulo MIENTRAS se hace hover.
                    if self.original_label._hovering:
                         self.translation_label.setVisible(True)
                    else:
                         self.translation_label.setVisible(False)

            except Exception as e:
                logger.error(f"Error al obtener/mostrar subtítulos: {e}")
                # Podrías mostrar el error en la etiqueta o simplemente registrarlo
                # self.original_label.setText(f"Error display: {e}")

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

    # --- Manejo del cierre ---
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
        event.accept() # Aceptar el cierre

    # Método llamado por HoverLabel para mostrar/ocultar traducción
    # Debe estar en el widget padre de HoverLabel (content_frame)
    # o delegar desde el padre si HoverLabel estuviera más anidado.
    # Aquí, como el padre es self.content_frame, y este método está en SubtitleOverlayWindow
    # necesitamos una referencia o hacer este método accesible.
    # La forma más simple ahora es ponerlo aquí y que HoverLabel llame a parentWidget().show_translation()
    @Slot(bool) # Para indicar que recibe un booleano
    def show_translation(self, show: bool):
        """Muestra u oculta la etiqueta de traducción."""
        logger.debug(f"show_translation llamado con: {show}")
        if self.translation_label: # Asegurarse de que existe
             # Solo mostrar si hay texto de traducción
            if show and self.current_translation:
                 self.translation_label.setVisible(True)
            else:
                 self.translation_label.setVisible(False)

# --- Punto de Entrada ---
if __name__ == "__main__":
    # Configurar logging si es necesario
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    app = QApplication(sys.argv)
    
    window = SubtitleOverlayWindow()
    window.show()
    
    sys.exit(app.exec())