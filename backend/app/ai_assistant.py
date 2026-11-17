import os
import re
import json
import httpx
from typing import Literal
from pydantic import BaseModel, Field, ValidationError

class ClaimClassification(BaseModel):
    categoria: Literal["FRAUDE", "TRANSFERENCIA", "TARJETA", "CUENTA", "OTRO"]
    prioridad: Literal["ALTA", "MEDIA", "BAJA"]
    resumen: str = Field(..., max_length=200)

def mask_sensitive_data(text: str) -> str:
    """Enmascara PII antes de enviarlo a un proveedor externo (RF9.a)."""
    # 1. Correos electrónicos
    text = re.sub(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', '[EMAIL_OCULTO]', text)
    # 2. Teléfonos (formatos locales e internacionales de 8 a 15 dígitos)
    text = re.sub(r'(\+?\d{1,3}[-.\s]?)?(\(?\d{2,4}\)?[-.\s]?)\d{3,4}[-.\s]?\d{3,4}', '[TELEFONO_OCULTO]', text)
    # 3. Tarjetas (13 a 19 dígitos) o números de cuenta largos (8 a 20 dígitos)
    text = re.sub(r'\b\d{8,20}\b', '[CUENTA_O_TARJETA_OCULTA]', text)
    # 4. Documentos / Cédulas con puntos o guiones (ej: 4.123.456 o 1234567-8)
    text = re.sub(r'\b\d{1,3}(\.\d{3}){2}(-\d)?\b|\b\d{6,8}-\d\b', '[DOCUMENTO_OCULTO]', text)
    return text

def _rule_based_fallback(masked_text: str) -> ClaimClassification:
    """Clasificador determinístico de respaldo si no hay API key o falla el LLM (RF9.c)."""
    lower = masked_text.lower()
    
    if any(w in lower for w in ["fraude", "robo", "no reconozco", "clonada", "estafa", "hack"]):
        cat, prio = "FRAUDE", "ALTA"
    elif any(w in lower for w in ["transferencia", "débito", "debito", "envié", "doble", "giro"]):
        cat, prio = "TRANSFERENCIA", "ALTA" if "doble" in lower else "MEDIA"
    elif any(w in lower for w in ["tarjeta", "crédito", "pos", "cajero", "atm"]):
        cat, prio = "TARJETA", "MEDIA"
    elif any(w in lower for w in ["cuenta", "saldo", "bloqueo", "clave", "acceso"]):
        cat, prio = "CUENTA", "MEDIA"
    else:
        cat, prio = "OTRO", "BAJA"

    summary = masked_text.strip()[:197] + "..." if len(masked_text.strip()) > 200 else masked_text.strip()
    if not summary:
        summary = "Reclamo sin descripción detallada."

    return ClaimClassification(categoria=cat, prioridad=prio, resumen=summary)

async def analyze_claim(raw_text: str) -> dict:
    masked_text = mask_sensitive_data(raw_text)
    api_key = os.getenv("LLM_API_KEY", "").strip()
    api_url = os.getenv("LLM_API_URL", "https://openai.com")
    model_name = os.getenv("LLM_MODEL", "gpt-4o-mini")

    # Modo simulado si no hay variable de entorno configurada (RF9.d)
    if not api_key:
        result = _rule_based_fallback(masked_text)
        return {**result.model_dump(), "modo": "SIMULADO_REGLAS", "texto_enmascarado": masked_text}

    prompt = (
        "Clasifica el siguiente reclamo bancario y responde ÚNICAMENTE con un JSON válido "
        "con las claves: 'categoria' (FRAUDE, TRANSFERENCIA, TARJETA, CUENTA u OTRO), "
        "'prioridad' (ALTA, MEDIA o BAJA) y 'resumen' (máximo 200 caracteres).\n\n"
        f"Reclamo: {masked_text}"
    )

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            response = await client.post(
                api_url,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": model_name,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1
                }
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"].strip()
            
            # Limpiar bloques markdown si el LLM los incluye
            if content.startswith("```"):
                content = re.sub(r"^```(json)?|```$", "", content, flags=re.MULTILINE).strip()

            parsed = json.loads(content)
            validated = ClaimClassification(**parsed)
            return {**validated.model_dump(), "modo": "LLM", "texto_enmascarado": masked_text}

    except (httpx.HTTPError, json.JSONDecodeError, ValidationError, KeyError, Exception):
        # Respaldo automático ante timeout, error de red o JSON inválido (RF9.c)
        result = _rule_based_fallback(masked_text)
        return {**result.model_dump(), "modo": "RESPALDO_REGLAS", "texto_enmascarado": masked_text}
