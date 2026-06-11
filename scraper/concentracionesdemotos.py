"""
concentracionesdemotos.py — Scraper para concentracionesdemotos.com (Espanha).

URLs:
  - Listagem principal: https://www.concentracionesdemotos.com/concentraciones/
  - Páginas mensais (meses restantes do ano):
      https://www.concentracionesdemotos.com/julio-2026
      https://www.concentracionesdemotos.com/agosto-2026
      ... até dezembro-2026

Porquê páginas mensais separadas?
  A listagem principal (/concentraciones/) mostra por defeito os eventos dos
  próximos 2 meses. Para cobrir o resto do ano, usamos as URLs mensais que
  o próprio site disponibiliza no menu de navegação. Estas URLs são definidas
  em config.py (CONCENTRACIONESDEMOTOS_MESES_ES) e incluídas na chamada run().

Estrutura do site:
  Cada evento aparece como um card/artigo com:
    - Título (link para detalhe)
    - Data no formato "DD Mes YYYY"
    - Localidade e Provincia
    - Tipo de evento (etiqueta/badge)

  A página de detalhe tem:
    - Campos estruturados: data, localidade, provincia, preço, organização
    - Descrição livre
    - Às vezes um link para o cartaz ou site do evento

Estratégia:
  1. Fetch de cada URL de listagem (principal + mensais).
  2. Extrair links de detalhe únicos.
  3. Visitar cada detalhe para dados completos.
  Idem ao EventoMotor — detalhe é mais fiável que o resumo da listagem.
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
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4,
    "mayo": 5, "junio": 6, "julio": 7, "agosto": 8,
    "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12,
}


def _parse_data_es(texto: str, ano: int) -> tuple[Optional[str], Optional[str]]:
    """
    Parseia datas em espanhol para este site.

    Formatos típicos do concentracionesdemotos.com:
      "12 de Julio de 2026"
      "12 al 14 de Julio de 2026"
      "12 Julio 2026"
      "12-14 Julio 2026"
    """
    t = texto.strip().lower()
    # Extrair o ano do texto se present (pode diferir de `ano` para eventos de próximo ano)
    m_ano = re.search(r'(\d{4})', t)
    y = int(m_ano.group(1)) if m_ano else ano

    # "12 al 14 de julio de 2026"
    m = re.match(r'^(\d{1,2})\s+al\s+(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d1, d2, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            return f"{y}-{num:02d}-{int(d1):02d}", f"{y}-{num:02d}-{int(d2):02d}"

    # "12-14 julio"
    m = re.match(r'^(\d{1,2})-(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d1, d2, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            return f"{y}-{num:02d}-{int(d1):02d}", f"{y}-{num:02d}-{int(d2):02d}"

    # "12 de julio de 2026" ou "12 julio"
    m = re.match(r'^(\d{1,2})\s+(?:de\s+)?(\w+)', t)
    if m:
        d, mes = m.groups()
        num = MESES_ES.get(mes[:3])
        if num:
            iso = f"{y}-{num:02d}-{int(d):02d}"
            return iso, iso

    return None, None


def _links_listagem(soup) -> list[str]:
    """Extrai links de detalhe de uma página de listagem."""
    links = []
    # concentracionesdemotos.com usa URLs do tipo /concentracion/<slug>/
    for a in soup.find_all("a", href=re.compile(r'/concentracion[es]*/[^/]+/?$')):
        href = a.get("href", "")
        if href.startswith("http"):
            links.append(href)
        elif href.startswith("/"):
            links.append(f"https://www.concentracionesdemotos.com{href}")
    return list(dict.fromkeys(links))


def _parsear_detalhe(soup, url: str, agora: str, ano: int) -> Optional[Concentracao]:
    """
    Extrai dados de uma página de detalhe do concentracionesdemotos.com.

    O site usa um layout com campos em pares chave/valor ou em divs específicas.
    """

    def _texto(elem) -> str:
        return elem.get_text(strip=True) if elem else ""

    # Título
    titulo = _texto(soup.find("h1")) or _texto(soup.find("h2"))
    if not titulo:
        return None

    # Campos estruturados
    campos: dict[str, str] = {}

    # Tentar tabelas de informação
    for tr in soup.find_all("tr"):
        cels = tr.find_all(["td", "th"])
        if len(cels) >= 2:
            chave = _texto(cels[0]).lower().rstrip(":")
            valor = _texto(cels[1])
            if chave and valor:
                campos[chave] = valor

    # Tentar listas de definição
    for dl in soup.find_all("dl"):
        dts = dl.find_all("dt")
        dds = dl.find_all("dd")
        for dt, dd in zip(dts, dds):
            campos[_texto(dt).lower()] = _texto(dd)

    # Tentar <strong>Chave:</strong> Valor
    for strong in soup.find_all("strong"):
        chave = _texto(strong).lower().rstrip(":")
        seguinte = strong.next_sibling
        if seguinte and hasattr(seguinte, 'get_text'):
            valor = seguinte.get_text(strip=True)
        elif seguinte:
            valor = str(seguinte).strip()
        else:
            valor = ""
        if chave and valor:
            campos[chave] = valor

    def _campo(*chaves: str) -> Optional[str]:
        for k in chaves:
            for campo_k, v in campos.items():
                if k in campo_k:
                    return v
        return None

    data_texto = _campo("fecha", "date", "data", "cuando", "cuándo")
    localidade = _campo("localidad", "municipio", "lugar", "ciudad")
    provincia = _campo("provincia", "province")
    tipo_raw = _campo("tipo", "type", "categoría", "categoria")
    preco = _campo("precio", "entrada", "precio de entrada", "importe")
    tel = _campo("teléfono", "telefono", "phone", "contacto")
    email = _campo("email", "correo")
    url_oficial = _campo("web", "website")

    # URL do cartaz (og:image)
    url_cartaz = None
    og_img = soup.find("meta", property="og:image")
    if og_img:
        url_cartaz = og_img.get("content")
    tem_cartaz = bool(url_cartaz)

    # Data
    data_inicio, data_fim = None, None
    if data_texto:
        data_inicio, data_fim = _parse_data_es(data_texto, ano)

    if not data_inicio:
        # Tentar extrair do título
        m = re.search(r'(\d{1,2})\s+(?:de\s+)?(\w+)\s+(?:de\s+)?(\d{4})', titulo, re.IGNORECASE)
        if m:
            d, mes, y = m.groups()
            num = MESES_ES.get(mes.lower()[:3])
            if num:
                iso = f"{y}-{num:02d}-{int(d):02d}"
                data_inicio = data_fim = iso

    if not data_inicio:
        logger.debug("concentracionesdemotos: sem data para %s", url)
        return None

    tipo = normalizar_tipo(tipo_raw, pais="ES")

    loca = localidade.split(",")[0].strip() if localidade else None
    coords, uncertain = geocode(
        localidade=loca,
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
        tem_cartaz=tem_cartaz,
        cancelado=False,
        sem_info=False,
        geocoding_uncertain=uncertain,
        atualizado_em=agora,
        localidade=loca,
        distrito_provincia=provincia,
        latitude=lat,
        longitude=lng,
        url_cartaz=url_cartaz,
        url_evento=url,
        url_fonte_oficial=url_oficial,
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

    Args:
        url_principal: URL da listagem geral (próximos 2 meses).
        urls_mensais:  Lista de URLs de páginas mensais para cobrir o resto do ano.
        session:       Sessão HTTP (cria nova se None).
        ano:           Ano a scraper.

    Returns:
        Lista de objectos Concentracao.
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: concentracionesdemotos.com ===")

    agora = datetime.utcnow().isoformat()
    todos_links: list[str] = []

    # Fetch de todas as páginas de listagem (principal + mensais)
    urls_a_visitar = [url_principal] + (urls_mensais or [])

    for url_listagem in urls_a_visitar:
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

        concentracao = _parsear_detalhe(soup_detalhe, link, agora, ano)
        if concentracao:
            eventos.append(concentracao)
            logger.debug("concentracionesdemotos: %s (%s)", concentracao.nome, concentracao.data_inicio)

    logger.info("concentracionesdemotos.com: %d eventos recolhidos.", len(eventos))
    return eventos
