"""
eventomotor.py — Scraper para eventomotor.com (Espanha + Portugal).

URL: https://www.eventomotor.com/concentraciones-moteras-2026

Estrutura do site:
  Listagem paginada de eventos em cards. Cada card tem:
    - Título, data, localidade, província
    - Link para página de detalhe

  A página de detalhe tem dados mais ricos:
    - Descrição completa
    - Preço de entrada
    - Contacto (telefone, email)
    - Morada / Google Maps
    - Site oficial do organizador

Estratégia:
  1. Iterar pelas páginas de listagem (paginação por "?page=N").
  2. Recolher os links de detalhe de cada card.
  3. Visitar cada página de detalhe para obter dados completos.

Porquê visitar páginas de detalhe em vez de usar só a listagem?
  O resumo na listagem está em texto concatenado sem estrutura fiável.
  A página de detalhe tem campos num layout consistente com <dt>/<dd>
  ou <strong> + texto adjacente, que é mais fácil de parsear.
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

BASE_URL = "https://www.eventomotor.com/concentraciones-moteras-2026"

# Meses em espanhol
MESES_ES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4,
    "may": 5, "jun": 6, "jul": 7, "ago": 8,
    "sep": 9, "oct": 10, "nov": 11, "dic": 12,
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_data_es(texto: str, ano: int) -> tuple[Optional[str], Optional[str]]:
    """
    Parseia datas em espanhol.

    Formatos observados no EventoMotor:
      "12 Jun"           → dia único
      "12 y 13 Jun"      → dois dias
      "12 al 14 Jun"     → intervalo
      "12 de junio"      → dia único por extenso
      "12 al 14 de julio"
    """
    t = texto.strip().lower()

    # "12 al 14 de julio" ou "12 al 14 jul"
    m = re.match(r'^(\d{1,2})\s+al\s+(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d1, d2, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            return f"{ano}-{num:02d}-{int(d1):02d}", f"{ano}-{num:02d}-{int(d2):02d}"

    # "12 y 13 jun"
    m = re.match(r'^(\d{1,2})\s+y\s+(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d1, d2, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            return f"{ano}-{num:02d}-{int(d1):02d}", f"{ano}-{num:02d}-{int(d2):02d}"

    # "12 de junio" ou "12 jun"
    m = re.match(r'^(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            iso = f"{ano}-{num:02d}-{int(d):02d}"
            return iso, iso

    return None, None


def _parsear_detalhe(soup, url: str, agora: str, ano: int) -> Optional[Concentracao]:
    """
    Extrai os dados de uma página de detalhe de evento do EventoMotor.

    O EventoMotor usa um layout com campos identificados por texto bold
    ou por tags <dt>/<dd> num description list.
    """

    def _texto(elem) -> str:
        return elem.get_text(strip=True) if elem else ""

    # Título do evento (H1 ou H2 da página)
    titulo = _texto(soup.find("h1")) or _texto(soup.find("h2"))
    if not titulo:
        return None

    # og:title como fallback
    og_title = soup.find("meta", property="og:title")
    if not titulo and og_title:
        titulo = og_title.get("content", "")

    # Estrutura de campos: procurar <dt>/<dd> ou <strong> seguido de texto
    campos: dict[str, str] = {}

    # Tentar <dl>/<dt>/<dd>
    dls = soup.find_all("dl")
    for dl in dls:
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            campos[_texto(dt).lower()] = _texto(dd)

    # Tentar tabela de detalhes
    for tr in soup.find_all("tr"):
        cels = tr.find_all(["td", "th"])
        if len(cels) >= 2:
            chave = _texto(cels[0]).lower().rstrip(":")
            valor = _texto(cels[1])
            if chave and valor:
                campos[chave] = valor

    # Tentar pares <strong>texto</strong>: valor
    for strong in soup.find_all("strong"):
        chave = _texto(strong).lower().rstrip(":")
        # O valor está no próximo sibling de texto
        seguinte = strong.next_sibling
        if seguinte and hasattr(seguinte, 'get_text'):
            valor = seguinte.get_text(strip=True)
        elif seguinte:
            valor = str(seguinte).strip()
        else:
            valor = ""
        if chave and valor:
            campos[chave] = valor

    # Extrair campos conhecidos com variações de chave
    def _campo(*chaves: str) -> Optional[str]:
        for k in chaves:
            for campo_k, v in campos.items():
                if k in campo_k:
                    return v
        return None

    data_texto = _campo("fecha", "date", "data")
    localidade = _campo("localidad", "municipio", "local", "ciudad")
    provincia = _campo("provincia", "province", "district")
    tipo_raw = _campo("tipo", "type", "categoría", "categoria")
    preco = _campo("precio", "entrada", "precio de entrada")
    tel = _campo("teléfono", "telefono", "phone", "contacto")
    email = _campo("email", "correo")
    url_oficial = _campo("web", "website", "organizador web")
    descricao_elem = soup.find("div", class_=re.compile(r"descri|content|texto", re.I))
    descricao = descricao_elem.get_text(strip=True)[:500] if descricao_elem else None

    # Data
    data_inicio, data_fim = (None, None)
    if data_texto:
        data_inicio, data_fim = _parse_data_es(data_texto, ano)

    if not data_inicio:
        # Tentar extrair data do título (ex: "Concentracion X - 12 Junio 2026")
        m = re.search(r'(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:de\s+)?(\d{4})', titulo, re.IGNORECASE)
        if m:
            d, mes, y = m.groups()
            num = MESES_ES.get(mes.lower()[:3])
            if num:
                iso = f"{y}-{num:02d}-{int(d):02d}"
                data_inicio = data_fim = iso

    if not data_inicio:
        logger.debug("EventoMotor: sem data para %s", url)
        return None

    tipo = normalizar_tipo(tipo_raw, pais="ES")

    # Geocodificação: localidade primeiro, depois província
    loca = localidade.split(",")[0].strip() if localidade else None
    coords, uncertain = geocode(
        localidade=loca,
        distrito_provincia=provincia,
        pais="España",
    )
    lat = coords[0] if coords else None
    lng = coords[1] if coords else None

    # Detectar se é PT ou ES pela província/texto
    pais = "ES"
    if provincia and any(p in provincia.lower() for p in ["portugal", "lisboa", "porto", "braga", "faro"]):
        pais = "PT"

    return Concentracao(
        nome=titulo,
        data_inicio=data_inicio,
        data_fim=data_fim,
        pais=pais,
        fonte="eventomotor",
        tipo_evento=tipo,
        tier=2,
        tem_cartaz=False,
        cancelado=False,
        sem_info=False,
        geocoding_uncertain=uncertain,
        atualizado_em=agora,
        localidade=loca,
        distrito_provincia=provincia,
        latitude=lat,
        longitude=lng,
        url_evento=url,
        url_fonte_oficial=url_oficial,
        descricao=descricao,
        preco=preco,
        contacto_telefone=tel,
        contacto_email=email,
    )


def _links_listagem(soup) -> list[str]:
    """
    Extrai os links de detalhe de uma página de listagem do EventoMotor.

    Os cards de evento têm tipicamente um <a> com href apontando para
    /concentracion/<slug> ou /evento/<slug>.
    """
    links = []
    for a in soup.find_all("a", href=re.compile(r'/concentracion[es]*/|/evento/')):
        href = a.get("href", "")
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            links.append(f"https://www.eventomotor.com{href}")
    return list(dict.fromkeys(links))  # deduplica mantendo ordem


def run(url: str, session: requests.Session | None = None, ano: int = 2026) -> list[Concentracao]:
    """
    Scraper do EventoMotor.

    Fluxo:
    1. Fazer fetch da listagem principal (paginação ?page=N).
    2. Para cada card de evento, extrair o link de detalhe.
    3. Visitar cada detalhe e parsear.
    4. Parar quando uma página não tem eventos ou atingirmos 20 páginas.

    Returns:
        Lista de objectos Concentracao.
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: eventomotor.com ===")

    agora = datetime.utcnow().isoformat()
    eventos: list[Concentracao] = []
    todos_links: list[str] = []

    # Iterar pelas páginas de listagem
    for pagina in range(1, 21):  # máximo 20 páginas
        url_pagina = url if pagina == 1 else f"{url}?page={pagina}"
        soup = get_soup(url_pagina, session, delay=1.5)
        if not soup:
            break

        links = _links_listagem(soup)
        if not links:
            logger.debug("EventoMotor: sem eventos na página %d. A parar.", pagina)
            break

        novos = [l for l in links if l not in todos_links]
        todos_links.extend(novos)
        logger.debug("EventoMotor: página %d → %d links (%d novos)", pagina, len(links), len(novos))

        if not novos:
            break  # Todos os links já foram vistos — provavelmente a última página

    logger.info("EventoMotor: %d páginas de detalhe a visitar.", len(todos_links))

    # Visitar cada detalhe
    for link in todos_links:
        soup_detalhe = get_soup(link, session, delay=1.5)
        if not soup_detalhe:
            continue

        concentracao = _parsear_detalhe(soup_detalhe, link, agora, ano)
        if concentracao:
            eventos.append(concentracao)
            logger.debug("EventoMotor: %s (%s)", concentracao.nome, concentracao.data_inicio)

    logger.info("eventomotor.com: %d eventos recolhidos.", len(eventos))
    return eventos
