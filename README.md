# SubStudy

**Proyecto de Inteligencia Artificial y Big Data: SubStudy**

SubStudy es una aplicación de escritorio multiplataforma pensada para quienes estudian idiomas usando contenido multimedia. La app genera subtítulos en tiempo real a partir del audio del sistema o micrófono, los traduce y permite interactuar con ellos fácilmente. Además, incluye integración con Anki para crear tarjetas de memoria de forma automática y una herramienta para practicar la pronunciación.

---

## 1. Problema y Objetivos

### Problema a Resolver

Aprender idiomas con videos o streams es muy eficaz, pero los subtítulos convencionales son estáticos y no permiten interactuar más allá de la simple lectura. SubStudy mejora esta experiencia proporcionando subtítulos automáticos y traducidos en tiempo real, y herramientas prácticas para reforzar el aprendizaje.

### Objetivos

* Crear subtítulos automáticos a partir de cualquier fuente de audio.
* Traducir los subtítulos al instante y permitir consultar la traducción sobre la marcha.
* Integrar con Anki para generar tarjetas de estudio con solo un clic.
* Incorporar un sistema para practicar la pronunciación usando reconocimiento de voz.

---

## 2. Características principales

* **Subtítulos en tiempo real** usando Whisper (OpenAI).
* **Traducción instantánea** mediante Google Translate.
* **Overlay interactivo**: subtítulos flotantes que se pueden mover y ajustar.
* **Popup de traducción** al pasar el ratón sobre cada línea.
* **Integración con Anki** (vía AnkiConnect): creación rápida de tarjetas.
* **Práctica de pronunciación**: repasa frases y mide tu precisión.
* **Optimización**: uso eficiente de recursos y manejo robusto de errores.

---

## 3. Instalación

### Requisitos

* Python 3.8+
* [ffmpeg](https://ffmpeg.org/download.html) instalado y en el PATH
* Anki con [AnkiConnect](https://foosoft.net/projects/anki-connect/)

### Instalación de dependencias

```bash
pip install -r requirements.txt
```

### Configuración opcional

Puedes elegir el modelo de Whisper (tiny, base, small, etc.) configurando la variable de entorno:

```bash
# Windows
set WHISPER_MODEL_SIZE=base

# Linux/Mac
export WHISPER_MODEL_SIZE=base
```

---

## 4. Uso

### Subtítulos y traducción en tiempo real

```bash
python app.py
```

* Configura idioma de origen, idioma de traducción y dispositivo de audio.
* Haz clic en "Iniciar" para comenzar.
* Mueve y ajusta el overlay según prefieras.
* Pasa el ratón sobre cualquier línea para ver la traducción.
* Clic derecho para enviar la frase a Anki.

### Práctica de pronunciación

```bash
python pronunciation_practice.py
```

* Pulsa "Obtener Siguiente Tarjeta de Anki".
* Graba tu pronunciación.
* El sistema transcribe tu audio y muestra el porcentaje de similitud con la frase original.

---

## 5. Estructura del proyecto

* `app.py`: Overlay principal de subtítulos y traducción.
* `transcription.py`: Motor de transcripción y traducción.
* `anki_integration.py`: Lógica de integración con Anki.
* `pronunciation_practice.py`: Herramienta para practicar pronunciación.
* `requirements.txt`: Dependencias.

---

## 6. Notas y recomendaciones

* El overlay puede necesitar permisos especiales en algunos sistemas (p. ej., en macOS para capturar audio).
* Asegúrate de que Anki esté abierto y AnkiConnect activo antes de usar la integración.
* Si notas problemas de rendimiento, prueba con un modelo Whisper más pequeño.

---

## Créditos

Desarrollado por \[Tu Nombre o Equipo]. Basado en tecnologías de código abierto: OpenAI Whisper, PySide6, Google Translate y AnkiConnect.

---

¿Ideas o mejoras? ¡No dudes en abrir un issue o enviar un pull request!