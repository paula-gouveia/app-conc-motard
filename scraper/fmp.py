"""
fmp.py — Scraper para a FMP (Federação de Motociclismo de Portugal).

URL: https://www.fmp.pt/noticias/mototurismo/calendario-de-mototurismo-2026/

Estrutura do site:
  A FMP publica o calendário de mototurismo como um artigo de notícia.
  O conteúdo é uma tabela HTML ou uma lista com colunas:
    Data | Prova | Local | Organização | Distrito

Estes são eventos de Tier 1 — eventos oficiais da federação,
normalmente mais organizados e com mais visibilidade.

Diferenças em relação ao MotardFM:
  - Estrutura tabular (não texto livre) → parsing mais simples.
  - Tem district/organização explícitos.
  - Não tem cartazes/imagens por norma.
  - O URL pode mudar a cada ano (o número no final muda).
    Se a URL não funcionar, o main.py deve ser actualizado com o novo URL.
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
from .normalizer import normalizar_tipo, inferir_regiao_pt

logger = logging.getLogger(__name__)

# Mapeamento meses PT (abreviados → número)
MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
    # Por extenso
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


def _parse_data_fmp(texto: str, ano: int) -> tuple[Optional[str], Optional[str]]:
    """
    Parseia datas no formato FMP.

    Formatos observados:
      "14 Jun"          → dia único, mês abreviado
      "14 e 15 Jun"     → dois dias
      "14 a 16 Jun"     → intervalo
      "14 Jun a 16 Jun" → intervalo com mês em ambos
      "14/06"           → DD/MM

    Retorna (data_inicio, data_fim) em ISO YYYY-MM-DD.
    """
    t = texto.strip().lower()

    # DD/MM
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s*(?:a\s*(\d{1,2})/(\d{1,2}))?$', t)
    if m:
        d1, mes1, d2, mes2 = m.groups()
        inicio = f"{ano}-{int(mes1):02d}-{int(d1):02d}"
        fim = f"{ano}-{int(mes2):02d}-{int(d2):02d}" if d2 else inicio
        return inicio, fim

    # "14 a 16 Jun" ou "14 e 15 Jun"
    m = re.match(r'^(\d{1,2})\s+[ae]\s+(\d{1,2})\s+(\w+)$', t)
    if m:
        d1, d2, mes = m.groups()
        num = MESES.get(mes[:3])
        if num:
            return f"{ano}-{num:02d}-{int(d1):02d}", f"{ano}-{num:02d}-{int(d2):02d}"

    # "14 Jun"
    m = re.match(r'^(\d{1,2})\s+(\w+)$', t)
    if m:
        d, mes = m.groups()
        num = MESES.get(mes[:3])
        if num:
            iso = f"{ano}-{num:02d}-{int(d):02d}"
            return iso, iso

    return None, None


def run(url: str, session: requests.Session | None = None, ano: int = 2026) -> list[Concentracao]:
    """
    Scraper do calendário de mototurismo da FMP.

    A FMP publica os eventos como uma tabela HTML. As colunas variam de ano
    para ano mas tipicamente são: Data, Prova, Local, Organização, Distrito.

    Fluxo:
    1. Fazer fetch da página.
    2. Encontrar a tabela de eventos.
    3. Parsear cada linha.
    4. Geocodificar.

    Returns:
        Lista de objectos Concentracao (tier=1).
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: FMP ===")

    soup = get_soup(url, session, delay=1.0)
    if not soup:
        logger.error("Não foi possível aceder à FMP. A abortar.")
        return []

    agora = datetime.utcnow().isoformat()
    eventos: list[Concentracao] = []

    # A FMP usa tabelas HTML para o calendário.
    # Tentamos encontrar a tabela que contenha os cabeçalhos esperados.
    tabelas = soup.find_all("table")
    tabela_alvo = None
    for tabela in tabelas:
        texto = tabela.get_text().lower()
        # Verificar se esta tabela tem conteúdo de calendário
        if any(k in texto for k in ("data", "prova", "local", "distrito", "organiz")):
            tabela_alvo = tabela
            break

    if tabela_alvo:
        _parsear_tabela(tabela_alvo, eventos, agora, ano)
    else:
        # Fallback: tentar encontrar listas ou parágrafos com datas
        logger.warning("FMP: tabela não encontrada. A tentar parsing de listas.")
        _parsear_fallback(soup, eventos, agora, ano)

    logger.info("FMP: %d eventos recolhidos.", len(eventos))
    return eventos


def _parsear_tabela(tabela, eventos: list, agora: str, ano: int) -> None:
    """Parseia a tabela principal do calendário FMP."""
    linhas = tabela.find_all("tr")

    # Detectar índices das colunas pelo cabeçalho
    idx_data = idx_prova = idx_local = idx_org = idx_dist = None
    cabecalho = linhas[0] if linhas else None
    if cabecalho:
        cels = cabecalho.find_all(["th", "td"])
        for i, cel in enumerate(cels):
            t = cel.get_text(strip=True).lower()
            if "data" in t:
                idx_data = i
            elif "prova" in t or "evento" in t or "nome" in t:
                idx_prova = i
            elif "local" in t:
                idx_local = i
            elif "organiz" in t:
                idx_org = i
            elif "distrit" in t or "distrito" in t:
                idx_dist = i

    # Defaults sensatos se o cabeçalho não foi encontrado
    if idx_data is None:
        idx_data = 0
    if idx_prova is None:
        idx_prova = 1
    if idx_local is None:
        idx_local = 2
    if idx_org is None:
        idx_org = 3
    if idx_dist is None:
        idx_dist = 4

    for linha in linhas[1:]:  # Saltar cabeçalho
        cels = linha.find_all(["td", "th"])
        if len(cels) < 2:
            continue

        def cel_texto(idx):
            if idx is not None and idx < len(cels):
                return cels[idx].get_text(strip=True)
            return None

        data_texto = cel_texto(idx_data)
        prova = cel_texto(idx_prova)
        local = cel_texto(idx_local)
        org = cel_texto(idx_org)
        distrito = cel_texto(idx_dist)

        if not data_texto or not prova:
            continue

        data_inicio, data_fim = _parse_data_fmp(data_texto, ano)
        if not data_inicio:
            logger.debug("FMP: data não reconhecida: %s", data_texto)
            continue

        # Tipo: para eventos FMP, o nome da prova geralmente contém o tipo
        tipo = normalizar_tipo(prova, pais="PT")

        # Geocodificação: usar localidade se disponível, senão distrito
        localidade = local.split(",")[0].strip() if local else None
        coords, uncertain = geocode(
            localidade=localidade,
            distrito_provincia=distrito,
            pais="Portugal",
        )
        lat = coords[0] if coords else None
        lng = coords[1] if coords else None

        regiao = inferir_regiao_pt(distrito)

        c = Concentracao(
            nome=prova,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pais="PT",
            fonte="fmp",
            tipo_evento=tipo,
            tier=1,
            tem_cartaz=False,
            cancelado=False,
            sem_info=False,
            geocoding_uncertain=uncertain,
            atualizado_em=agora,
            organizador=org,
            localidade=localidade,
            distrito_provincia=distrito,
            regiao=regiao,
            latitude=lat,
            longitude=lng,
        )
        eventos.append(c)
        logger.debug("FMP evento: %s (%s)", c.nome, c.data_inicio)


def _parsear_fallback(soup, eventos: list, agora: str, ano: int) -> None:
    """
    Fallback para quando a FMP não usa tabela.
    Tenta parsear o conteúdo como texto com datas + nomes.
    Menos preciso — serve de salvaguarda se o layout mudar.
    """
    conteudo = soup.find("article") or soup.find("main") or soup
    paragrafos = conteudo.find_all("p")

    for p in paragrafos:
        texto = p.get_text(strip=True)
        if not texto or len(texto) < 8:
            continue

        # Tentar extrair data do início do parágrafo
        m = re.match(r'^(\d{1,2}\s+(?:jan|fev|mar|abr|mai|jun|jul|ago|set|out|nov|dez)\w*)', texto, re.IGNORECASE)
        if not m:
            continue

        data_texto = m.group(1)
        data_inicio, data_fim = _parse_data_fmp(data_texto, ano)
        if not data_inicio:
            continue

        nome = texto[m.end():].strip(" –-").strip()
        if not nome:
            continue

        c = Concentracao(
            nome=nome,
            data_inicio=data_inicio,
            data_fim=data_fim,
            pais="PT",
            fonte="fmp",
            tipo_evento="outro",
            tier=1,
            tem_cartaz=False,
            cancelado=False,
            sem_info=False,
            geocoding_uncertain=True,
            atualizado_em=agora,
        )
        eventos.append(c)
