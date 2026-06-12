"""
concentracionesdemotos.py — Scraper para concentracionesdemotos.com (Espanha).

Estrutura real do site (inspeccionada):
  LISTAGEM (/concentraciones/):
    Os eventos estão em <li> com links <a> cujo texto tem o formato:
      "EVENT NAME City (Province) DD/MM/YYYY"
    Exemplo:
      "CONCENTRACIÓN MOTORIZOS San Lorenzo de la Parrilla (Cuenca)12/06/2026"
    com href: "https://www.concentracionesdemotos.com/concentracion-motorizos-cuenca/"

    ATENÇÃO: Os URLs de detalhe NÃO seguem um padrão único.
    Alguns: /concentracion-slug/  Outros: /slug/ (sem prefixo).
    Estratégia: detectar os <li> que contêm datas (DD/MM/YYYY).

  PÁGINA DE DETALHE:
    Usa <h3>Rótulo</h3> seguido de texto irmão (não <dl>/<dt>/<dd>).
    Exemplo estrutura HTML:
      <h3>Fecha del Evento</h3>
      <p> 12/06/2026-14/06/2026</p>
      <h3>Tipo de Evento</h3>
      <p> Concentración</p>
      <h3>Quién Organiza</h3>
      <p> Peña Motera La Parrilla</p>
      <h3>Cuánto Cuesta</h3>
      <p> 35€ anticipada - 40€ en el recinto</p>
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


def _parse_data_es(texto: str) -> tuple[Optional[str], Optional[str]]:
    """
    Parseia datas no formato do concentracionesdemotos.com.

    Formatos observados:
      "12/06/2026"                    → dia único
      "12/06/2026-14/06/2026"         → intervalo
      "12/06/2026 - 14/06/2026"       → intervalo com espaços
    """
    t = texto.strip()

    # Intervalo: DD/MM/YYYY-DD/MM/YYYY (com ou sem espaços)
    m = re.match(r'(\d{1,2})/(\d{2})/(\d{4})\s*[-–]\s*(\d{1,2})/(\d{2})/(\d{4})', t)
    if m:
        d1, mes1, ano1, d2, mes2, ano2 = m.groups()
        return f"{ano1}-{int(mes1):02d}-{int(d1):02d}", f"{ano2}-{int(mes2):02d}-{int(d2):02d}"

    # Dia único: DD/MM/YYYY
    m = re.match(r'(\d{1,2})/(\d{2})/(\d{4})', t)
    if m:
        d, mes, ano = m.groups()
        iso = f"{ano}-{int(mes):02d}-{int(d):02d}"
        return iso, iso

    return None, None


def _links_listagem(soup) -> list[str]:
    """
    Extrai os links de detalhe de uma página de listagem.

    Estratégia: procurar <li> que contenham um padrão de data DD/MM/YYYY
    (distingue itens de evento de itens de navegação).
    """
    links = []
    for li in soup.find_all('li'):
        texto_li = li.get_text(strip=True)
        # Um item de evento tem sempre uma data no formato DD/MM/YYYY
        if not re.search(r'\d{2}/\d{2}/\d{4}', texto_li):
            continue
        a = li.find('a')
        if not a:
            continue
        href = a.get('href', '').strip()
        if not href or href in links:
            continue
        # Excluir links internos de navegação (não são eventos)
        skip = ['/concentraciones/', '/racing', '/custom', '/trail',
                '/scooter', '/clasicas', '/noticias/', '/tienda',
                '/publicar-evento/', '/contacto', '/aviso', '/politica']
        if any(href.rstrip('/').endswith(s.rstrip('/')) for s in skip):
            continue
        if href.startswith('/') and not href.startswith('//'):
            href = f"https://www.concentracionesdemotos.com{href}"
        if 'concentracionesdemotos.com' in href:
            links.append(href)

    return list(dict.fromkeys(links))  # deduplica mantendo ordem


def _parsear_detalhe(soup, url: str, agora: str) -> Optional[Concentracao]:
    """
    Extrai dados de uma página de detalhe.

    Estrutura: <h3>Rótulo</h3> seguido de nó de texto irmão.

    Campos disponíveis:
      "Lugar del Evento", "Fecha del Evento", "Tipo de Evento",
      "Quién Organiza", "Cuánto Cuesta" + contacto (telefone/email)
    """

    def _texto(elem) -> str:
        return elem.get_text(strip=True) if elem else ""

    # Título: H1 da página (ou og:title como fallback)
    titulo = _texto(soup.find('h1'))
    if not titulo:
        og = soup.find('meta', property='og:title')
        titulo = og.get('content', '') if og else ''
    if not titulo:
        return None

    # Extrair campos por <h3>Label</h3> + próximo sibling com texto
    campos: dict[str, str] = {}
    for h3 in soup.find_all('h3'):
        label = _texto(h3).lower().strip()
        if not label:
            continue
        # Procurar o próximo sibling que tenha texto
        sib = h3.next_sibling
        while sib is not None:
            if hasattr(sib, 'get_text'):
                valor = sib.get_text(strip=True)
                if valor and len(valor) > 1:
                    campos[label] = valor
                    break
            elif isinstance(sib, str) and sib.strip():
                campos[label] = sib.strip()
                break
            sib = sib.next_sibling

    def _campo(*chaves: str) -> Optional[str]:
        for k in chaves:
            for campo_k, v in campos.items():
                if k in campo_k:
                    return v
        return None

    # Data
    data_texto = _campo("fecha del evento", "fecha")
    data_inicio, data_fim = None, None
    if data_texto:
        data_inicio, data_fim = _parse_data_es(data_texto)

    if not data_inicio:
        logger.debug("concentracionesdemotos: sem data para %s", url)
        return None

    # Localização
    lugar = _campo("lugar del evento", "lugar")
    localidade = None
    provincia = None
    if lugar:
        # Formato: "San Lorenzo de la Parrilla\n(Cuenca)" ou "City (Province)"
        m = re.match(r'^(.+?)\s*\((.+?)\)', lugar.replace('\n', ' '))
        if m:
            localidade = m.group(1).strip()
            provincia = m.group(2).strip()
        else:
            localidade = lugar.strip()

    # Outros campos
    tipo_raw = _campo("tipo de evento", "tipo")
    organizador = _campo("quién organiza", "organiza", "organizador")
    preco = _campo("cuánto cuesta", "precio", "coste", "entrada")
    tel = _campo("teléfono", "telefono")
    email = _campo("email", "correo")

    # Cartaz: og:image
    url_cartaz = None
    og_img = soup.find('meta', property='og:image')
    if og_img:
        url_cartaz = og_img.get('content')

    tipo = normalizar_tipo(tipo_raw, pais="ES")

    coords, uncertain = geocode(
        localidade=localidade,
        distrito_provincia=provincia,
        pais="España",
    )
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None

    return Concentracao(
        nome=titulo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        pais="ES",
        fonte="concentracionesdemotos",
        tipo_evento=tipo,
        tier=2,
        tem_cartaz=bool(url_cartaz),
        cancelado=False,
        sem_info=False,
        geocoding_uncertain=uncertain,
        atualizado_em=agora,
        organizador=organizador,
        localidade=localidade,
        distrito_provincia=provincia,
        latitude=lat,
        longitude=lng,
        url_cartaz=url_cartaz,
        url_evento=url,
        preco=preco,
        contacto_telefone=tel,
        contacto_email=email,
    )


def run(
    url_principal: str,
    urls_mensais: list[str],
    session: requests.Session | None = None,
    ano: int = 2026,
) -> list[Concentracao]:
    """
    Scraper do concentracionesdemotos.com.

    Fluxo:
    1. Fetch de todas as páginas de listagem (principal + mensais).
    2. Extrair links de detalhe de <li> que contêm datas.
    3. Visitar cada página de detalhe com o parser corrigido.

    Returns:
        Lista de Concentracao.
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: concentracionesdemotos.com ===")

    agora = datetime.utcnow().isoformat()
    todos_links: list[str] = []

    for url_listagem in [url_principal] + (urls_mensais or []):
        soup = get_soup(url_listagem, session, delay=1.5)
        if not soup:
            logger.warning("concentracionesdemotos: falhou fetch de %s", url_listagem)
            continue
        links = _links_listagem(soup)
        novos = [l for l in links if l not in todos_links]
        todos_links.extend(novos)
        logger.debug("concentracionesdemotos: %s → %d links (%d novos)", url_listagem, len(links), len(novos))

    logger.info("concentracionesdemotos.com: %d páginas de detalhe a visitar.", len(todos_links))

    eventos: list[Concentracao] = []
    for link in todos_links:
        soup_detalhe = get_soup(link, session, delay=1.5)
        if not soup_detalhe:
            continue
        concentracao = _parsear_detalhe(soup_detalhe, link, agora)
        if concentracao:
            eventos.append(concentracao)
            logger.debug("concentracionesdemotos: %s (%s)", concentracao.nome, concentracao.data_inicio)

    logger.info("concentracionesdemotos.com: %d eventos recolhidos.", len(eventos))
    return eventos
