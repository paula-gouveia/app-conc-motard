"""
geocoding.py — Converter localidades em coordenadas GPS via Nominatim.

Nominatim é o serviço de geocoding da OpenStreetMap. É gratuito, sem API key,
mas com duas regras de utilização:
  1. Máximo 1 pedido por segundo (respeitamos com time.sleep).
  2. User-Agent identificador obrigatório (fornecemos abaixo).

Porquê um cache em memória?
  O mesmo município pode aparecer em dezenas de eventos. Sem cache,
  faríamos o mesmo pedido HTTP ao Nominatim repetidamente. O cache é um
  dicionário simples que dura enquanto o scraper corre numa execução.

Estratégia de fallback:
  1. Tenta "localidade, País" (mais específico)
  2. Se falhar, tenta "distrito/província, País" (mais geral)
  3. Se falhar, retorna None e marca geocoding_uncertain=True no evento.
"""

from __future__ import annotations

import time
import logging
from typing import Optional

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderServiceError

logger = logging.getLogger(__name__)

# Cache em memória: chave = query string, valor = (lat, lng) ou None
_cache: dict[str, Optional[tuple[float, float]]] = {}

# Singleton do geocoder
_geocoder: Optional[Nominatim] = None


def _get_geocoder() -> Nominatim:
    global _geocoder
    if _geocoder is None:
        # O user_agent identifica a nossa aplicação ao Nominatim.
        # Usar um nome descritivo é boa prática e evita throttling agressivo.
        _geocoder = Nominatim(user_agent="conc-motard-pt/1.0 (uso pessoal)")
    return _geocoder


def geocode(
    localidade: Optional[str],
    distrito_provincia: Optional[str] = None,
    pais: str = "Portugal",
) -> tuple[Optional[tuple[float, float]], bool]:
    """
    Converte uma localidade em coordenadas (lat, lng).

    Args:
        localidade:         Nome da localidade/cidade (ex: "Figueira da Foz").
        distrito_provincia: Fallback mais geral (ex: "Coimbra" ou "Huesca").
        pais:               País para contextualizar a pesquisa ("Portugal" ou "España").

    Returns:
        Tuplo ((lat, lng), uncertain):
          - (lat, lng) são as coordenadas, ou None se não encontrado.
          - uncertain é True se o resultado veio de um fallback menos específico
            ou se o geocoding falhou completamente.
    """
    # Constrói queries da mais específica para a mais geral
    queries: list[str] = []
    if localidade:
        queries.append(f"{localidade}, {pais}")
    if distrito_provincia and distrito_provincia != localidade:
        queries.append(f"{distrito_provincia}, {pais}")

    if not queries:
        return None, True

    geo = _get_geocoder()

    for i, query in enumerate(queries):
        uncertain = (i > 0)  # qualquer resultado após a primeira query é incerto

        # Verifica o cache primeiro
        if query in _cache:
            cached = _cache[query]
            if cached is not None:
                logger.debug("Cache hit: %s", query)
                return cached, uncertain
            continue  # Já tentado e falhou — passa para a próxima query

        # Nominatim exige ≥1 segundo entre pedidos
        time.sleep(1.1)

        try:
            location = geo.geocode(query, language="pt")
            if location:
                coords = (location.latitude, location.longitude)
                _cache[query] = coords
                logger.info("Geocodificado: %s → %.4f, %.4f", query, *coords)
                return coords, uncertain
            else:
                logger.warning("Sem resultado para: %s", query)
                _cache[query] = None

        except GeocoderTimedOut:
            logger.error("Timeout ao geocodificar: %s", query)
        except GeocoderServiceError as e:
            logger.error("Erro no serviço Nominatim para %s: %s", query, e)

    logger.warning("Geocodificação falhou para: %s / %s (%s)", localidade, distrito_provincia, pais)
    return None, True
