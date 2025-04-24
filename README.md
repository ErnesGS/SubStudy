# SubStudy

**Proyecto de Inteligencia Artificial y Big Data: SubStudy**

## 1. Definición del Problema y Objetivos

### Problema a Resolver
El aprendizaje de idiomas a través de contenido multimedia es una estrategia efectiva, pero los subtítulos tradicionales no permiten una interacción dinámica con el contenido. SubStudy busca mejorar esta experiencia proporcionando subtítulos automáticos y traducidos en tiempo real, facilitando el estudio de idiomas.

### Objetivos
- Desarrollar un modelo de **speech-to-text** (STT) para generar subtítulos automáticos de videos y streams.
- Implementar un sistema de **traducción interactiva** que permita visualizar la traducción al pasar el cursor sobre una frase.
- Integrar SubStudy con **Anki** para generar flashcards automáticamente y comprobar la pronunciación de las palabras aprendidas.

## 2. Exploración del Estado del Arte y Alcance

### Estado del Arte
Actualmente, existen herramientas como:
- **YouTube Auto-Subtitles**: Genera subtítulos automáticos, pero sin traducción interactiva.
- **DeepL y Google Translate**: Permiten traducciones de textos, pero sin integración con subtítulos en tiempo real.
- **Whisper (OpenAI)**: Ofrece un sistema avanzado de speech-to-text con alta precisión.

### Alcance del Proyecto
- **Primera Versión**: Generación de subtítulos automáticos y traducción interactiva.
- **Futuras Mejoras**: Integración con múltiples fuentes de video, mejora en la detección de errores de pronunciación y personalización del aprendizaje.

## 3. Planificación del Desarrollo

| Fase | Descripción | Duración |
|---|---|---|
| **Investigación y selección de tecnologías** | Evaluación de APIs y modelos STT/Translate. | 2 semanas |
| **Desarrollo del prototipo** | Implementación inicial del sistema de subtítulos y traducción. | 4 semanas |
| **Integración con Anki** | Generación de flashcards automáticas. | 3 semanas |
| **Optimización y pruebas** | Pruebas en distintos entornos y ajuste de algoritmos. | 3 semanas |
| **Documentación y preparación de la presentación** | Redacción de informe y código en GitHub. | 2 semanas |

## 4. Herramientas y Tecnologías

- **Lenguaje de programación**: Python.
- **Modelos de STT**: Whisper (OpenAI).
- **APIs de Traducción**: DeepL o Google Translate.
- **Integración con Anki**: AnkiConnect.
- **Interfaz de la aplicación**: PySide6/Qt

## 5. Fuentes de Datos Previstas

- **Audio y video en tiempo real** de plataformas como YouTube, Twitch o archivos locales.
- **Datos generados** por los usuarios en su interacción con las traducciones y flashcards.

## 6. Modo de empleo
Para utilizar la aplicación:
- Clona el repositorio en tu equipo.
- **Instala las dependencias**: pip install -r requirements.txt
- **Ejecuta la aplicación**: python app.py
- **Generar tarjetas en Anki**: debes tener abierta la aplicación de anki y tener instalado el complemento de Ankiconect