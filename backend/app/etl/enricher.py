"""
Phase 2 — AI Enrichment Agent
-------------------------------
Calls Groq (model set by settings.groq_chat_model) to generate structured
metadata for each vehicle. Returns a validated AIEnrichmentOutput model.

Usage:
    from app.etl.enricher import enrich_vehicle
    result = await enrich_vehicle(raw_vehicle)
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional

import structlog
from groq import Groq
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import settings
from app.core.segments import PROMPT_SEGMENTS
from app.schemas.inventory import AIEnrichmentOutput, RawVehicle

log = structlog.get_logger()

# ── Configure Groq client once ───────────────────────────────
_client = Groq(api_key=settings.groq_api_key)

# ── Enrichment prompt ────────────────────────────────────────
_SEGMENT_LIST = ", ".join(PROMPT_SEGMENTS)

_SYSTEM_PROMPT = f"""Automotive data specialist. Enrich vehicle specs as JSON.
Rules: Never invent features. Only use provided data. Tags must come from:
Family-friendly, Fuel-efficient, Sporty, Luxury, City-ready, Off-road capable,
Eco-friendly, Long-range, Budget-friendly, Premium, Practical, Performance
ai_segment MUST be exactly one of: {_SEGMENT_LIST}"""

_USER_TEMPLATE = """Specs:
{specs}

Return JSON only:
{{"ai_lifestyle_tags":[1-4 approved tags],"ai_segment":"one approved segment","ai_summary":"2-3 factual sentences for a buyer","ai_selling_points":[2-5 points from specs only],"ai_comparable_models":[2-3 real models],"ai_confidence":0.0-1.0}}"""


def _build_specs_string(vehicle: RawVehicle) -> str:
    """Format a vehicle's raw specs into a clean string for the prompt."""
    lines = [
        f"Make/Model: {vehicle.year} {vehicle.make} {vehicle.model} {vehicle.trim or ''}".strip(),
        f"Body type: {vehicle.body_type or 'Unknown'}",
        f"Fuel: {vehicle.fuel_type or 'Unknown'}",
        f"Transmission: {vehicle.transmission or 'Unknown'}",
        f"Engine: {vehicle.engine or 'Not specified'}",
        f"Seats: {vehicle.seats or 'Not specified'}",
        f"Mileage: {vehicle.mileage:,} km",
        f"Price: ${vehicle.price:,.0f}",
        f"Condition: {vehicle.condition or 'Not specified'}",
    ]
    if vehicle.features:
        lines.append(f"Features: {', '.join(vehicle.features[:15])}")
    return "\n".join(lines)


@retry(
    retry=retry_if_exception_type(Exception),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    stop=stop_after_attempt(3),
)
async def enrich_vehicle(vehicle: RawVehicle) -> Optional[AIEnrichmentOutput]:
    """
    Call Groq to enrich a single vehicle. Returns AIEnrichmentOutput on success.

    Retries up to 3 times with exponential backoff; if all attempts fail it
    raises tenacity.RetryError wrapping the last error (e.g. a Groq 429). The
    pipeline caller catches this — a quota error stops the run cleanly, any
    other error skips just that vehicle.
    """
    specs  = _build_specs_string(vehicle)
    prompt = _USER_TEMPLATE.format(specs=specs)

    try:
        response = await asyncio.to_thread(
            _client.chat.completions.create,
            model=settings.groq_chat_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )

        raw_json = json.loads(response.choices[0].message.content)
        result   = AIEnrichmentOutput(**raw_json)

        log.info(
            "enrichment_success",
            vin=vehicle.vin,
            segment=result.ai_segment,
            confidence=result.ai_confidence,
            needs_review=result.ai_confidence < 0.7,
        )
        return result

    except Exception as e:
        log.error("enrichment_failed", vin=vehicle.vin, error=str(e))
        raise  # let tenacity retry
