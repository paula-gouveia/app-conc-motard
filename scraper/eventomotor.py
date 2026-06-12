"""
eventomotor.py — Scraper para eventomotor.com (Espanha).

URL: https://www.eventomotor.com/concentraciones-moteras-2026

Estrutura real do site (inspeccionada):
  A página de listagem contém TODOS os dados necessários directamente no HTML.
  Cada evento é um link <a href="/evento/slug-YYYY-MM-DD">...</a>
  cujo texto concatenado tem o formato:

    "12JUN TrailmotoHuescaArtic Quest12-14 jun / Canfranc, HuescaVer evento"

  Componentes:
    - "12JUN"           → dia + mês (não usado — usamos a data do URL)
    - "Trail"           → tipo de evento
    - "moto"            → literal
    - "Huesca"          → província (concatenada sem espaço a seguir a "moto")
    - "Artic Quest"     → nome do evento
    - "12-14 jun"       → intervalo de datas
    - "/ Canfranc,"     → cidade
    - "Huesca"          → província (repetida)
    - "Ver evento"      → literal

  URL: /evento/artic-quest-2026-06-12
    → data_inicio = "2026-06-12" (extraída da URL)

Estratégia:
  Parsear directamente a listagem — NÃO visitar páginas de detalhe.
  Todos os campos necessários estão na listagem.
  As páginas de detalhe têm a mesma informação (+ fonte oficial)
  mas visitar 60-100 páginas adicionava ~3 min ao scraper sem ganho real.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import Optional

import requests

from .base import get_soup, make_session
from .geocoding import geocode
from .models import Concentracao
from .normalizer import normalizar_tipo

logger = logging.getLogger(__name__)

MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}


def _data_de_url(url: str) -> Optional[str]:
    """
    Extrai a data ISO do slug da URL do EventoMotor.
    Ex: "/evento/artic-quest-2026-06-12" → "2026-06-12"
    """
    m = re.search(r'-(\d{4}-\d{2}-\d{2})$', url)
    return m.group(1) if m else None


def _data_fim_de_texto(texto: str, data_inicio: str) -> str:
    """
    Extrai a data de fim a partir do intervalo no texto do link.
    Ex: "12-14 jun" → "2026-06-14"
    Se não encontrar, retorna a data_inicio (evento de 1 dia).
    """
    ano = data_inicio[:4]

    # Padrão: "DD-DD mmm" (ex: "12-14 jun")
    m = re.search(r'\d{1,2}-(\d{1,2})\s+([a-záéíóúñ]{3})', texto, re.IGNORECASE)
    if m:
        end_day = m.group(1)
        mes_abbr = m.group(2).lower()[:3]
        num = MESES_ES.get(mes_abbr)
        if num:
            return f"{ano}-{num:02d}-{int(end_day):02d}"

    # Padrão: "DD mmm" sem range → mesmo que início
    return data_inicio


def _parsear_link_listagem(href: str, texto: str, ano: int) -> Optional[dict]:
    """
    Extrai os dados de um evento a partir do link de listagem do EventoMotor.

    Args:
        href:  URL do evento (ex: "/evento/artic-quest-2026-06-12")
        texto: Texto concatenado do link (ex: "12JUN TrailmotoHuescaArtic Quest12-14 jun / Canfranc, HuescaVer evento")
        ano:   Ano esperado (para validação)

    Returns:
        Dicionário com os campos extraídos, ou None se falhar.
    """
    data_inicio = _data_de_url(href)
    if not data_inicio:
        return None

    # Garantir que é do ano correcto
    if not data_inicio.startswith(str(ano)):
        return None

    # Separar texto em: prefix / "city, provinceVer evento"
    # O separador " / " é consistente em todos os eventos
    if ' / ' not in texto:
        return None

    prefix, _, localizacao = texto.partition(' / ')
    # localizacao: "Canfranc, HuescaVer evento"
    # Remover "Ver evento" do final
    localizacao = localizacao.replace('Ver evento', '').strip()

    # city, province
    if ',' in localizacao:
        cidade, _, provincia = localizacao.partition(',')
        cidade = cidade.strip()
        provincia = provincia.strip()
    else:
        cidade = localizacao.strip()
        provincia = None

    # Data de fim a partir do intervalo no prefix
    data_fim = _data_fim_de_texto(prefix, data_inicio)

    # Tipo: texto entre DDmm e "moto" (ex: "Trail" em "12JUN TrailmotoHuesca")
    tipo_raw = None
    m = re.search(r'^\d{1,2}\w{3,4}\s+([\w\s]*?)moto', prefix, re.IGNORECASE)
    if m:
        tipo_raw = m.group(1).strip()

    # Nome do evento: texto entre "moto{Provincia}" e o intervalo de datas
    nome = None
    if provincia:
        # Procurar "moto{provincia}" no prefix (case-insensitive)
        moto_prov = 'moto' + provincia
        idx = prefix.lower().find(moto_prov.lower())
        if idx >= 0:
            depois_prov = prefix[idx + len(moto_prov):]
            # Remover o intervalo de datas do final: "12-14 jun" ou "12 jun"
            m_data = re.search(r'\d{1,2}[-\s]\d*\s*\w{3}', depois_prov)
            nome = depois_prov[:m_data.start()].strip() if m_data else depois_prov.strip()

    # Fallback: usar slug da URL como nome
    if not nome:
        slug = re.sub(r'-\d{4}-\d{2}-\d{2}$', '', href.split('/')[-1])
        nome = slug.replace('-', ' ').title()

    if not nome:
        return None

    return {
        "nome":         nome,
        "data_inicio":  data_inicio,
        "data_fim":     data_fim,
        "tipo_raw":     tipo_raw,
        "cidade":       cidade,
        "provincia":    provincia,
        "url_evento":   f"https://www.eventomotor.com{href}" if href.startswith('/') else href,
    }


def run(url: str, session: requests.Session | None = None, ano: int = 2026) -> list[Concentracao]:
    """
    Scraper do EventoMotor — parseia directamente a listagem, sem visitar detalhe.

    Fluxo:
    1. Fetch da página de listagem de concentrações.
    2. Encontrar todos os links <a href="/evento/..."> com texto de evento.
    3. Parsear data, cidade, província, tipo e nome de cada link.
    4. Geocodificar.

    Returns:
        Lista de Concentracao.
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: eventomotor.com ===")

    soup = get_soup(url, session, delay=1.5)
    if not soup:
        logger.error("EventoMotor: não foi possível aceder à listagem. A abortar.")
        return []

    agora = datetime.utcnow().isoformat()
    eventos: list[Concentracao] = []
    vistos: set[str] = set()

    # Encontrar todos os links de eventos: <a href="/evento/...">
    for a in soup.find_all('a', href=re.compile(r'/evento/')):
        href = a.get('href', '')
        if not href:
            continue

        # Normalizar para URL relativa
        if href.startswith('https://www.eventomotor.com'):
            href = href[len('https://www.eventomotor.com'):]

        if href in vistos:
            continue
        vistos.add(href)

        texto = a.get_text(separator='', strip=True)
        dados = _parsear_link_listagem(href, texto, ano)
        if not dados:
            logger.debug("EventoMotor: não foi possível parsear link: %s", href)
            continue

        tipo = normalizar_tipo(dados.get("tipo_raw"), pais="ES")

        coords, uncertain = geocode(
            localidade=dados.get("cidade"),
            distrito_provincia=dados.get("provincia"),
            pais="España",
        )
        lat = coords[0] if coords else None
        lng = coords[1] if coords else None

        c = Concentracao(
            nome=dados["nome"],
            data_inicio=dados["data_inicio"],
            data_fim=dados["data_fim"],
            pais="ES",
            fonte="eventomotor",
            tipo_evento=tipo,
            tier=2,
            tem_cartaz=False,
            cancelado=False,
            sem_info=False,
            geocoding_uncertain=uncertain,
            atualizado_em=agora,
            localidade=dados.get("cidade"),
            distrito_provincia=dados.get("provincia"),
            latitude=lat,
            longitude=lng,
            url_evento=dados.get("url_evento"),
        )
        eventos.append(c)
        logger.debug("EventoMotor: %s (%s)", c.nome, c.data_inicio)

    logger.info("eventomotor.com: %d eventos recolhidos.", len(eventos))
    return eventos
