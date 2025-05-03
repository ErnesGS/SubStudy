# anki_integration.py - Módulo común para interacción con Anki
import requests
import json
import logging

logger = logging.getLogger(__name__)

class AnkiConnector:
    """Clase para manejar todas las interacciones con AnkiConnect"""
    
    def __init__(self, deck_name="SubStudy", model_name="Básico", 
                 front_field="Anverso", back_field="Reverso", url="http://localhost:8765"):
        self.ANKICONNECT_URL = url
        self.ANKI_DECK_NAME = deck_name
        self.ANKI_MODEL_NAME = model_name
        self.ANKI_FRONT_FIELD = front_field
        self.ANKI_BACK_FIELD = back_field
    
    def add_note(self, front_text, back_text, tags=None):
        """
        Añade una nota a Anki
        
        Args:
            front_text: Texto para el campo frontal
            back_text: Texto para el campo trasero
            tags: Lista de etiquetas (opcional)
            
        Returns:
            tuple: (success, message_or_note_id)
        """
        if tags is None:
            tags = ["substudy", "realtime"]
            
        # Preparar datos para AnkiConnect
        note_data = {
            "deckName": self.ANKI_DECK_NAME,
            "modelName": self.ANKI_MODEL_NAME,
            "fields": {
                self.ANKI_FRONT_FIELD: front_text,
                self.ANKI_BACK_FIELD: back_text
            },
            "options": {
                "allowDuplicate": False
            },
            "tags": tags
        }
        
        payload = json.dumps({"action": "addNote", "version": 6, "params": {"note": note_data}})

        try:
            response = requests.post(self.ANKICONNECT_URL, data=payload, timeout=3)
            response.raise_for_status()
            result = response.json()

            if result.get("error") is not None:
                error_msg = result["error"]
                logger.error(f"Error de AnkiConnect: {error_msg}")
                return False, self._format_anki_error(error_msg)
            elif result.get("result") is not None:
                logger.info(f"Nota añadida a Anki con ID: {result['result']}")
                return True, result['result']
            else:
                logger.warning(f"Respuesta inesperada de AnkiConnect: {result}")
                return False, "Respuesta inesperada de Anki"

        except requests.exceptions.ConnectionError:
            logger.error("Error de conexión con AnkiConnect")
            return False, "Error: No se pudo conectar con Anki.\nAsegúrate de que Anki esté abierto y AnkiConnect instalado."
        except requests.exceptions.Timeout:
            logger.error("Timeout al conectar con AnkiConnect")
            return False, "Error: Tiempo de espera agotado al conectar con Anki."
        except Exception as e:
            logger.error(f"Error inesperado al comunicarse con Anki: {e}")
            return False, f"Error: {e}"
    
    def find_due_cards(self):
        """
        Busca tarjetas vencidas en el mazo
        
        Returns:
            tuple: (success, [card_ids] o mensaje_error)
        """
        query = f'deck:"{self.ANKI_DECK_NAME}" is:due'
        
        try:
            payload = json.dumps({"action": "findCards", "version": 6, "params": {"query": query}})
            response = requests.post(self.ANKICONNECT_URL, data=payload, timeout=3)
            response.raise_for_status()
            result = response.json()

            if result.get("error"):
                return False, f"AnkiConnect Error: {result['error']}"
            
            card_ids = result.get("result", [])
            return True, card_ids
            
        except Exception as e:
            logger.error(f"Error al buscar tarjetas en Anki: {e}")
            return False, f"Error: {e}"
    
    def get_card_info(self, card_id):
        """
        Obtiene información de una tarjeta específica
        
        Args:
            card_id: ID de la tarjeta
            
        Returns:
            tuple: (success, card_info o mensaje_error)
        """
        try:
            payload = json.dumps({"action": "cardsInfo", "version": 6, "params": {"cards": [card_id]}})
            response = requests.post(self.ANKICONNECT_URL, data=payload, timeout=3)
            response.raise_for_status()
            result = response.json()

            if result.get("error"):
                return False, f"AnkiConnect Error: {result['error']}"

            card_info = result.get("result", [])
            if not card_info:
                return False, "No se pudo obtener información de la tarjeta"
            
            return True, card_info[0]
            
        except Exception as e:
            logger.error(f"Error al obtener información de tarjeta: {e}")
            return False, f"Error: {e}"
    
    def _format_anki_error(self, error_msg):
        """Formatea mensajes de error comunes de Anki"""
        if "deck was not found" in error_msg:
            return f"Error Anki: Mazo '{self.ANKI_DECK_NAME}' no encontrado.\nPor favor, créalo en Anki."
        elif "model was not found" in error_msg:
            return f"Error Anki: Modelo '{self.ANKI_MODEL_NAME}' no encontrado.\nPor favor, asegúrate de que existe."
        elif "duplicate" in error_msg:
            return "Nota duplicada (ya existe en Anki)."
        else:
            return f"Error de Anki: {error_msg}" 