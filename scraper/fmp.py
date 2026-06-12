"""
fmp.py — Scraper para a FMP (Federação de Motociclismo de Portugal).

URL: https://www.fmp.pt/noticias/mototurismo/calendario-de-mototurismo-2026/

Estrutura real do site (inspeccionada):
  A FMP publica o calendário como um artigo WordPress com texto livre.
  NÃO é uma tabela HTML.

  Organização do artigo:
    <strong>Eventos FMP</strong>          ← cabeçalho de secção (negrito)
    12 de abril – 28º Dia Nacional...     ← linha de evento
    30 abr. a 3 de maio – 2º Portugal...  ← linha de evento
    ...
    <strong>29º Troféu Nacional de Moto-Ralis Turísticos</strong>
    28/29 de março – M.C. Albufeira ...
    ...
    <strong>Concentrações</strong>
    27 fev. a 1 de março – M.C Covilhã
    ...

  Separador entre campos: EN DASH (–) com espaços à volta.
  Cada linha: "Data – Organização/Nome [– Localidade]"

Formatos de data observados:
  "12 de abril"               → dia único, mês por extenso
  "28/29 de março"            → dois dias no mesmo mês (barra)
  "10 a 13 de junho"          → intervalo, mesmo mês ("e" também aceite: "5 e 6 de junho")
  "30 abr. a 3 de maio"       → intervalo cross-mês (abreviação + extenso)
  "27 fev. a 1 de março"      → idem
  "Junho (a definir)"         → mês sem dia definido → ignorar
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

# Meses PT — por extenso e abreviados
MESES = {
    "jan": 1, "fev": 2, "mar": 3, "abr": 4,
    "mai": 5, "jun": 6, "jul": 7, "ago": 8,
    "set": 9, "out": 10, "nov": 11, "dez": 12,
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}

# Cabeçalhos de secção → tipo_evento normalizado
SECOES = {
    "eventos fmp":                              "evento_fmp",
    "troféu nacional de moto-ralis":            "moto_rali_trofeu",
    "trofeu nacional de moto-ralis":            "moto_rali_trofeu",
    "concentrações":                            "concentracao",
    "concentracoes":                            "concentracao",
}


def _detectar_secao(texto: str) -> Optional[str]:
    """Retorna o tipo_evento se o texto corresponde a um cabeçalho de secção."""
    t = texto.lower().strip()
    for chave, tipo in SECOES.items():
        if chave in t:
            return tipo
    return None


def _normalizar_mes(texto: str) -> Optional[int]:
    """Converte nome ou abreviação de mês para número (1-12)."""
    t = texto.lower().strip().rstrip(".")
    # Tentar correspondência exacta
    if t in MESES:
        return MESES[t]
    # Tentar pelos primeiros 3 caracteres (cobre abreviações como "abr.", "jul.")
    if len(t) >= 3 and t[:3] in MESES:
        return MESES[t[:3]]
    return None


def _parse_data(texto: str, ano: int) -> tuple[Optional[str], Optional[str]]:
    """
    Parseia os formatos de data usados pela FMP.

    Retorna (data_inicio, data_fim) em YYYY-MM-DD,
    ou (None, None) se o formato não for reconhecido.
    """
    t = texto.strip().lower()

    # "28/29 de março" → dois dias no mesmo mês
    m = re.match(r'^(\d{1,2})/(\d{1,2})\s+de\s+(\w+\.?)', t)
    if m:
        d1, d2, mes = m.groups()
        num = _normalizar_mes(mes)
        if num:
            return f"{ano}-{num:02d}-{int(d1):02d}", f"{ano}-{num:02d}-{int(d2):02d}"

    # "30 abr. a 3 de maio" ou "27 fev. a 1 de março" → cross-mês
    m = re.match(r'^(\d{1,2})\s+(\w+\.?)\s+a\s+(\d{1,2})\s+de\s+(\w+\.?)', t)
    if m:
        d1, mes1, d2, mes2 = m.groups()
        num1, num2 = _normalizar_mes(mes1), _normalizar_mes(mes2)
        if num1 and num2:
            return f"{ano}-{num1:02d}-{int(d1):02d}", f"{ano}-{num2:02d}-{int(d2):02d}"

    # "10 a 13 de junho" ou "5 e 6 de junho" → intervalo mesmo mês
    m = re.match(r'^(\d{1,2})\s+[ae]\s+(\d{1,2})\s+de\s+(\w+\.?)', t)
    if m:
        d1, d2, mes = m.groups()
        num = _normalizar_mes(mes)
        if num:
            return f"{ano}-{num:02d}-{int(d1):02d}", f"{ano}-{num:02d}-{int(d2):02d}"

    # "12 de abril" → dia único
    m = re.match(r'^(\d{1,2})\s+de\s+(\w+\.?)', t)
    if m:
        d, mes = m.groups()
        num = _normalizar_mes(mes)
        if num:
            iso = f"{ano}-{num:02d}-{int(d):02d}"
            return iso, iso

    # "Junho (a definir)" → sem dia ainda — ignorar
    return None, None


def _parsear_linha_evento(linha: str, tipo_secao: str, ano: int) -> Optional[dict]:
    """
    Parseia uma linha de evento do artigo FMP.

    Formato esperado: "Data – Nome/Organização [– Localidade]"
    O separador é o EN DASH (–) com espaços.
    """
    linha = linha.strip()
    if not linha or len(linha) < 5:
        return None

    # Separar pelos " – " (EN DASH com espaços)
    # Também aceitar " - " (hífen ASCII) para robustez
    partes = re.split(r'\s+[–\-]\s+', linha)
    if len(partes) < 2:
        return None

    data_texto = partes[0].strip()
    nome_org = partes[1].strip()
    localidade = partes[2].strip() if len(partes) >= 3 else None

    # Parsear data
    data_inicio, data_fim = _parse_data(data_texto, ano)
    if not data_inicio:
        return None

    # Para o Troféu, a localidade pode estar entre parênteses no nome
    # Ex: "M.C. Albufeira (Ria Formosa)" → organização + local entre ()
    m_paren = re.search(r'\(([^)]+)\)\s*$', nome_org)
    if m_paren and not localidade:
        localidade = m_paren.group(1)
        nome_org = nome_org[:m_paren.start()].strip()

    return {
        "nome":         nome_org,
        "data_inicio":  data_inicio,
        "data_fim":     data_fim,
        "organizador":  nome_org,
        "localidade":   localidade.split(",")[0].strip() if localidade else None,
        "tipo_secao":   tipo_secao,
    }


def run(url: str, session: requests.Session | None = None, ano: int = 2026) -> list[Concentracao]:
    """
    Scraper do calendário de mototurismo da FMP.

    Fluxo:
    1. Fetch da página do artigo.
    2. Encontrar o corpo do artigo.
    3. Percorrer todos os elementos de texto:
       - <strong> sozinho → cabeçalho de secção → actualizar tipo corrente
       - linha com data → parsear como evento
    4. Geocodificar localidades.

    Returns:
        Lista de Concentracao (tier=1, pais="PT").
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: FMP ===")

    soup = get_soup(url, session, delay=1.0)
    if not soup:
        logger.error("FMP: não foi possível aceder à página. A abortar.")
        return []

    # Encontrar o corpo do artigo WordPress
    conteudo = (
        soup.find("div", class_="entry-content")
        or soup.find("article")
        or soup.find("main")
        or soup
    )

    agora = datetime.utcnow().isoformat()
    tipo_atual = "concentracao"  # default se não encontrar cabeçalho
    eventos: list[Concentracao] = []

    # Extrair todo o texto do artigo, linha a linha
    # get_text(separator="\n") garante uma linha por elemento inline
    texto_completo = conteudo.get_text(separator="\n")
    linhas = [l.strip() for l in texto_completo.splitlines() if l.strip()]

    for linha in linhas:
        # Detectar cabeçalho de secção (bold headers no artigo FMP)
        tipo_detectado = _detectar_secao(linha)
        if tipo_detectado:
            tipo_atual = tipo_detectado
            logger.debug("FMP: secção detectada: %s → %s", linha[:40], tipo_atual)
            continue

        # Tentar parsear como linha de evento
        dados = _parsear_linha_evento(linha, tipo_atual, ano)
        if not dados:
            continue

        coords, uncertain = geocode(
            localidade=dados.get("localidade"),
            pais="Portugal",
        )
        lat = coords[0] if coords else None
        lng = coords[1] if coords else None

        c = Concentracao(
            nome=dados["nome"],
            data_inicio=dados["data_inicio"],
            data_fim=dados["data_fim"],
            pais="PT",
            fonte="fmp",
            tipo_evento=dados["tipo_secao"],
            tier=1,
            tem_cartaz=False,
            cancelado=False,
            sem_info=False,
            geocoding_uncertain=uncertain,
            atualizado_em=agora,
            organizador=dados.get("organizador"),
            localidade=dados.get("localidade"),
            latitude=lat,
            longitude=lng,
            url_evento=url,
        )
        eventos.append(c)
        logger.debug("FMP: %s (%s)", c.nome, c.data_inicio)

    logger.info("FMP: %d eventos recolhidos.", len(eventos))
    return eventos
