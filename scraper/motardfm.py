"""
motardfm.py — Scraper para motardfm.org/calendario/

Estrutura do site:
  WordPress + Elementor. O calendário é uma página de texto livre organizada
  por meses (headers H2/H3) com um evento por linha (parágrafo P).

Formato típico de cada linha:
  "DD – Nome do Clube – Local (Tipo) [CARTAZ|SEM INFO|CANCELADO]"
  "DD a DD – Nome do Evento – Local (Tipo) CARTAZ"
  "31 de Julho a 2 de Agosto – Nome – Local CARTAZ"

Estratégia de parsing:
  1. Encontrar a div de conteúdo principal.
  2. Iterar pelos elementos filho:
     - H2/H3 → actualizar o mês corrente
     - P → extrair evento
  3. Para cada P: extrair texto, URL (se houver link), e fazer parsing
     da data, nome, organizador, tipo, e flags.
  4. Para eventos com CARTAZ e URL de detalhe, visitar a página para
     obter a imagem do cartaz (og:image).

Notas de parsing:
  - O separador entre campos é o EN DASH (–, U+2013), não o hífen ASCII.
  - Eventos com datas "cross-mês" (ex: "31 de Julho a 2 de Agosto")
    têm o mês escrito por extenso na própria linha.
  - A ordem nas listas de flags pode variar: CARTAZ pode aparecer antes
    ou depois do tipo entre parênteses.
"""

from __future__ import annotations

import re
import logging
from datetime import datetime
from typing import Optional

import requests

from .base import get_soup, make_session
from .geocoding import geocode
from .models import Concentracao
from .normalizer import normalizar_tipo, inferir_regiao_pt

logger = logging.getLogger(__name__)

BASE_URL = "https://motardfm.org/calendario/"

# Mapeamento meses PT → número
MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4,
    "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
    "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12,
}


# ---------------------------------------------------------------------------
# Parsing de datas
# ---------------------------------------------------------------------------

def _parse_data_linha(linha: str, mes_atual: int, ano: int) -> tuple[Optional[str], Optional[str]]:
    """
    Extrai data de início e fim de uma linha do calendário MotardFM.

    Padrões suportados (todos têm EN DASH como separador final):
      "10 –"                               → dia único, mês da secção
      "10 e 11 –"                          → 2 dias, mês da secção
      "10 a 13 –"                          → intervalo, mês da secção
      "31 de Julho e 1 de Agosto –"        → cross-mês, meses por extenso
      "31 de Julho a 2 de Agosto –"        → cross-mês, meses por extenso
      "25 a 28 – ..."                      → intervalo sem mês explícito

    Retorna (data_inicio, data_fim) em formato YYYY-MM-DD,
    ou (None, None) se o padrão não for reconhecido.
    """
    t = linha.strip().lower()

    # Padrão cross-mês por extenso: "31 de Julho a/e 2 de Agosto"
    m = re.match(
        r'^(\d{1,2})\s+de\s+(\w+)\s+[ae]\s+(\d{1,2})\s+de\s+(\w+)',
        t,
    )
    if m:
        d1, mes1, d2, mes2 = m.groups()
        num1, num2 = MESES.get(mes1), MESES.get(mes2)
        if num1 and num2:
            return (
                f"{ano}-{num1:02d}-{int(d1):02d}",
                f"{ano}-{num2:02d}-{int(d2):02d}",
            )

    # Padrão dia único com mês por extenso: "10 de Junho –"
    m = re.match(r'^(\d{1,2})\s+de\s+(\w+)\s+[–\-]', t)
    if m:
        d, mes = m.groups()
        num = MESES.get(mes)
        if num:
            iso = f"{ano}-{num:02d}-{int(d):02d}"
            return iso, iso

    # Padrão intervalo "DD a DD –" dentro do mesmo mês
    m = re.match(r'^(\d{1,2})\s+a\s+(\d{1,2})\s+[–\-]', t)
    if m:
        d1, d2 = m.groups()
        return (
            f"{ano}-{mes_atual:02d}-{int(d1):02d}",
            f"{ano}-{mes_atual:02d}-{int(d2):02d}",
        )

    # Padrão 2 dias "DD e DD –"
    m = re.match(r'^(\d{1,2})\s+e\s+(\d{1,2})\s+[–\-]', t)
    if m:
        d1, d2 = m.groups()
        return (
            f"{ano}-{mes_atual:02d}-{int(d1):02d}",
            f"{ano}-{mes_atual:02d}-{int(d2):02d}",
        )

    # Padrão dia único "DD –"
    m = re.match(r'^(\d{1,2})\s+[–\-]', t)
    if m:
        d = m.group(1)
        iso = f"{ano}-{mes_atual:02d}-{int(d):02d}"
        return iso, iso

    return None, None


# ---------------------------------------------------------------------------
# Parsing de uma linha de evento
# ---------------------------------------------------------------------------

def _parsear_linha(texto: str, url_evento: Optional[str], mes_atual: int, ano: int) -> Optional[dict]:
    """
    Extrai todos os campos de uma linha de evento do calendário MotardFM.

    Retorna um dicionário com os campos extraídos, ou None se a linha
    não parecer ser um evento válido.
    """
    # Remover espaços extra e normalizar o dash
    texto = texto.strip()
    if not texto or len(texto) < 5:
        return None

    # Detectar flags
    cancelado = "CANCELADO" in texto.upper()
    sem_info = "SEM INFO" in texto.upper()
    tem_cartaz = "CARTAZ" in texto.upper()

    # Verificar se a linha começa com um número (dia do mês)
    # — isto filtra cabeçalhos, notas de rodapé, etc.
    if not re.match(r'^\d', texto):
        return None

    # Extrair as datas
    data_inicio, data_fim = _parse_data_linha(texto, mes_atual, ano)
    if not data_inicio:
        logger.debug("Data não reconhecida na linha: %s", texto[:60])
        return None

    # Remover a parte da data e o separador do início da linha
    # "10 a 13 – Portugal..." → "Portugal..."
    # "31 de Julho a 2 de Agosto – Nome..." → "Nome..."
    corpo = re.sub(
        r'^\d{1,2}(?:\s+(?:a|e)\s+\d{1,2})?(?:\s+de\s+\w+(?:\s+[ae]\s+\d{1,2}\s+de\s+\w+)?)?'
        r'\s*[–\-]\s*',
        '', texto, count=1,
    ).strip()

    # Remover flags do final do corpo
    # Ex: "Nome (Tipo) CARTAZ" → "Nome (Tipo)"
    # Ex: "Nome CARTAZ COMPLETO" → "Nome"
    corpo = re.sub(r'\s+CARTAZ\s*(?:COMPLETO)?\s*$', '', corpo, flags=re.IGNORECASE).strip()
    corpo = re.sub(r'\s+SEM\s+INFO\s*$', '', corpo, flags=re.IGNORECASE).strip()
    corpo = re.sub(r'\s+CANCELADO\s*$', '', corpo, flags=re.IGNORECASE).strip()

    # Extrair tipo de evento entre parênteses (último par de parênteses da linha)
    tipo_raw = None
    m = re.search(r'\(([^)]+)\)\s*$', corpo)
    if m:
        tipo_raw = m.group(1)
        corpo = corpo[:m.start()].strip()

    # O que resta é "Organizador – Localidade" ou apenas "Nome do Evento"
    # Separar pelo EN DASH se existir
    partes = [p.strip() for p in corpo.split('–') if p.strip()]

    # Heurística:
    # - Se há 2+ partes, a primeira é o organizador/nome, a última é a localidade.
    # - Se há 1 parte, é o nome do evento (sem localidade explícita).
    if len(partes) >= 2:
        organizador = partes[0]
        localidade_raw = partes[-1]
        # Se a localidade tem vírgula, pegar só a cidade (antes da vírgula)
        # Ex: "Lapa, Cartaxo" → localidade="Lapa", distrito=? (não disponível aqui)
        localidade = localidade_raw.split(",")[0].strip()
        nome = corpo  # nome completo inclui tudo
    else:
        organizador = partes[0] if partes else corpo
        localidade = None
        nome = corpo

    # Limpar o nome (remover o organizador duplicado se for igual ao nome)
    nome = nome.strip()
    if not nome:
        nome = organizador

    return {
        "nome": nome,
        "data_inicio": data_inicio,
        "data_fim": data_fim,
        "organizador": organizador,
        "localidade": localidade,
        "tipo_raw": tipo_raw,
        "tem_cartaz": tem_cartaz,
        "cancelado": cancelado,
        "sem_info": sem_info,
        "url_evento": url_evento,
    }


# ---------------------------------------------------------------------------
# Obter URL do cartaz na página de detalhe
# ---------------------------------------------------------------------------

def _obter_url_cartaz(url: str, session: requests.Session) -> Optional[str]:
    """
    Visita a página de detalhe de um evento e extrai a URL do cartaz (og:image).

    O MotardFM usa og:image como imagem principal do post — é o cartaz.
    Usamos a meta tag og:image em vez de tentar encontrar a imagem no DOM
    porque o Elementor pode mudar a estrutura HTML mas a og:image é estável.
    """
    soup = get_soup(url, session, delay=1.2)
    if not soup:
        return None

    og_image = soup.find("meta", property="og:image")
    if og_image and og_image.get("content"):
        return og_image["content"]

    # Fallback: primeira imagem dentro da área de conteúdo
    conteudo = soup.find("article") or soup.find("main")
    if conteudo:
        img = conteudo.find("img", src=re.compile(r"\.(jpg|jpeg|png|webp)", re.I))
        if img:
            return img.get("src")

    return None


# ---------------------------------------------------------------------------
# Encontrar a div de conteúdo principal
# ---------------------------------------------------------------------------

def _encontrar_conteudo(soup) -> Optional[object]:
    """
    Tenta encontrar a div que contém o calendário de eventos.

    O MotardFM usa Elementor, que usa classes como:
      .elementor-widget-text-editor
      .entry-content
      .elementor-section-wrap

    Tentamos vários selectores por ordem de especificidade.
    """
    selectores = [
        ".elementor-widget-text-editor .elementor-widget-container",
        ".elementor-widget-text-editor",
        ".entry-content",
        "article",
        ".elementor-section-wrap",
        "main",
    ]
    for sel in selectores:
        elem = soup.select_one(sel)
        if elem:
            # Verificar se tem H2 com meses (sinal de que encontrámos o calendário)
            h2s = elem.find_all(["h2", "h3"])
            if h2s:
                return elem
    return soup  # fallback: documento inteiro


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------

def run(session: requests.Session | None = None, ano: int = 2026) -> list[Concentracao]:
    """
    Executa o scraper do motardfm.org/calendario/.

    Fluxo:
    1. Fazer fetch da página do calendário.
    2. Encontrar a div de conteúdo.
    3. Iterar pelos elementos:
       - H2/H3 → actualizar mês corrente
       - P/Strong → parsear linha de evento
    4. Para eventos com CARTAZ e URL, visitar a página de detalhe
       para obter a URL do cartaz.
    5. Geocodificar localidades.

    Returns:
        Lista de objectos Concentracao.
    """
    if session is None:
        session = make_session()

    logger.info("=== SCRAPER: motardfm.org ===")

    soup = get_soup(BASE_URL, session, delay=1.0)
    if not soup:
        logger.error("Não foi possível aceder ao MotardFM. A abortar.")
        return []

    conteudo = _encontrar_conteudo(soup)
    agora = datetime.utcnow().isoformat()
    mes_atual = 0  # 0 = ainda não encontrámos nenhum mês
    eventos: list[Concentracao] = []

    # Iterar por todos os elementos relevantes do conteúdo
    for elem in conteudo.find_all(["h1", "h2", "h3", "h4", "p", "li", "strong"]):
        texto_elem = elem.get_text(separator=" ", strip=True)

        # --- Detectar cabeçalho de mês ---
        # Os meses aparecem como H2/H3, em maiúsculas, sozinhos na linha
        if elem.name in ("h2", "h3"):
            texto_mes = texto_elem.strip().upper()
            # Remove texto de formatação como "**" ou espaços
            texto_mes = re.sub(r'[*#\s]+', '', texto_mes)
            for nome_mes, num in MESES.items():
                if nome_mes.upper() in texto_mes or texto_mes == nome_mes.upper():
                    mes_atual = num
                    logger.debug("Mês detectado: %s (%d)", nome_mes, num)
                    break
            continue

        # Ignorar se ainda não encontrámos o primeiro mês
        if mes_atual == 0:
            continue

        # --- Ignorar elementos P que são claramente cabeçalhos ou notas ---
        # (ex: "ACTUALIZADO", "9 de JUNHO", notas de rodapé)
        if re.match(r'^(ACTUAL|ENVIA|ESTE|A VERM|A AZUL|A LAR)', texto_elem, re.IGNORECASE):
            continue

        # --- Extrair URL do link (se existir) ---
        link = elem.find("a")
        url_evento = None
        if link and link.get("href"):
            href = link["href"]
            # Só guardar URLs de páginas de detalhe do próprio MotardFM
            if "motardfm.org/concentracoes/" in href:
                url_evento = href

        # --- Parsear a linha como evento ---
        dados = _parsear_linha(texto_elem, url_evento, mes_atual, ano)
        if not dados:
            continue

        # Tipo normalizado
        tipo = normalizar_tipo(dados.get("tipo_raw"), pais="PT")

        # Geocodificação
        coords, uncertain = geocode(
            localidade=dados.get("localidade"),
            pais="Portugal",
        )
        lat = coords[0] if coords else None
        lng = coords[1] if coords else None

        # URL do cartaz (visita a página de detalhe se necessário)
        url_cartaz = None
        if dados["tem_cartaz"] and dados["url_evento"]:
            url_cartaz = _obter_url_cartaz(dados["url_evento"], session)

        concentracao = Concentracao(
            nome=dados["nome"],
            data_inicio=dados["data_inicio"],
            data_fim=dados["data_fim"],
            pais="PT",
            fonte="motardfm",
            tipo_evento=tipo,
            tier=2,  # eventos motardfm são sempre tier 2 (tier 1 é FMP)
            tem_cartaz=dados["tem_cartaz"],
            cancelado=dados["cancelado"],
            sem_info=dados["sem_info"],
            geocoding_uncertain=uncertain,
            atualizado_em=agora,
            organizador=dados.get("organizador"),
            localidade=dados.get("localidade"),
            latitude=lat,
            longitude=lng,
            url_cartaz=url_cartaz,
            url_evento=dados.get("url_evento"),
        )
        eventos.append(concentracao)
        logger.debug("Evento extraído: %s (%s)", concentracao.nome, concentracao.data_inicio)

    logger.info("motardfm.org: %d eventos recolhidos.", len(eventos))
    return eventos
