"""
normalizer.py — Normalização de tipos de evento e deduplicação.

Duas responsabilidades:
  1. normalizar_tipo(): converte o texto original de cada fonte (ex:
     "(Aniversário)", "Trail", "Concentración") para um valor uniforme
     da taxonomia definida na Fase 0.

  2. deduplicate(): remove eventos duplicados quando dois scrapers
     reportam o mesmo evento (ex: EventoMotor + concentracionesdemotos).
"""

from __future__ import annotations

import difflib
import logging
from typing import Optional

from .models import Concentracao

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Taxonomia — dicionários de mapeamento por idioma
# ---------------------------------------------------------------------------
# Chave: texto original em minúsculas (pode ser substring)
# Valor: tipo_evento normalizado

_TIPOS_PT: dict[str, str] = {
    "concentração": "concentracao",
    "concentracao": "concentracao",
    "aniversário": "aniversario",
    "aniversario": "aniversario",
    "motochurrasco": "motochurrasco",
    "churrascada": "motochurrasco",
    "feijoada": "motochurrasco",
    "motofeijoada": "motochurrasco",
    "convívio": "convivio",
    "convivio": "convivio",
    "encontro motard": "convivio",
    "encontro de mot": "convivio",  # cobre "encontro de motas e motorizadas"
    "sardinhada": "convivio",
    "motochurrasco": "motochurrasco",
    "moto-rali": "moto_rali",
    "moto rali": "moto_rali",
    "rali turist": "moto_rali",    # cobre "rali turístico"
    "passeio": "passeio",
    "benção": "bencao",
    "bencao": "bencao",
    "bênção": "bencao",
    "pequeno almoço": "matinal",
    "matabicho": "matinal",
    "arraial": "arraial",
    "magusto": "magusto",
    "motomagusto": "magusto",
    "halloween": "halloween",
    "pais natais": "natal",
    "pai natal": "natal",
    "natal solidário": "natal",
    "natal": "natal",
    "solidária": "solidario",
    "solidario": "solidario",
    "desfile": "desfile",
    "run nocturno": "run",
    "run noturno": "run",
    "motas antigas": "classicas",
    "motorizadas clás": "classicas",
    "clássicas": "classicas",
    "classicas": "classicas",
    "moto fest": "festival",
    "off-road": "trail",
    "off road": "trail",
    "trail": "trail",
    "motochurrasco": "motochurrasco",
    "bucha motard": "convivio",
    "bucha": "convivio",
    "magusto": "magusto",
    "peregrinação": "passeio",
    "peregrinacao": "passeio",
}

_TIPOS_ES: dict[str, str] = {
    "concentración": "concentracao",
    "concentracion": "concentracao",
    "trail": "trail",
    "custom y harley": "custom",
    "custom": "custom",
    "rutas moteras": "passeio",
    "rutas": "passeio",
    "ruta motera": "passeio",
    "festival motero": "festival",
    "festival": "festival",
    "motoalmuerzo": "matinal",
    "matinal": "matinal",
    "clásicas": "classicas",
    "clasicas": "classicas",
    "offroad": "trail",
    "cross y montaña": "trail",
    "scooter": "outro",
    "rodadas": "rodadas",
    "racing": "rodadas",
    "kedada": "convivio",
    "quedada": "convivio",
    "encuentro": "convivio",
}

# ---------------------------------------------------------------------------
# Mapeamento de regiões PT (distrito → NUT II aproximada)
# ---------------------------------------------------------------------------
_REGIAO_PT: dict[str, str] = {
    "viana do castelo": "Norte",
    "braga": "Norte",
    "porto": "Norte",
    "vila real": "Norte",
    "bragança": "Norte",
    "aveiro": "Centro",
    "coimbra": "Centro",
    "viseu": "Centro",
    "guarda": "Centro",
    "castelo branco": "Centro",
    "leiria": "Centro",
    "santarém": "Alentejo",
    "lisboa": "Lisboa e Vale do Tejo",
    "setúbal": "Lisboa e Vale do Tejo",
    "setubal": "Lisboa e Vale do Tejo",
    "portalegre": "Alentejo",
    "évora": "Alentejo",
    "evora": "Alentejo",
    "beja": "Alentejo",
    "faro": "Algarve",
}

# ---------------------------------------------------------------------------
# Normalização de tipo de evento
# ---------------------------------------------------------------------------

def normalizar_tipo(texto_original: Optional[str], pais: str = "PT") -> str:
    """
    Converte o texto de tipo original para um valor normalizado da taxonomia.

    Estratégia:
    1. Normaliza o texto para minúsculas sem espaços extra.
    2. Testa substrings do dicionário correspondente ao país.
    3. Se não encontrar, devolve "outro".

    Args:
        texto_original: Texto cru extraído da fonte (ex: "(Aniversário)", "Trail").
        pais:           "PT" ou "ES" — determina qual dicionário usar.

    Returns:
        String da taxonomia (ex: "aniversario", "trail", "concentracao", "outro").
    """
    if not texto_original:
        return "outro"

    texto = texto_original.lower().strip().strip("()")

    mapa = _TIPOS_PT if pais == "PT" else _TIPOS_ES

    # Testa correspondência exacta primeiro
    if texto in mapa:
        return mapa[texto]

    # Testa se alguma chave do mapa é substring do texto
    for chave, valor in mapa.items():
        if chave in texto:
            return valor

    return "outro"


def inferir_regiao_pt(distrito: Optional[str]) -> Optional[str]:
    """Devolve a região NUT II aproximada para um distrito português."""
    if not distrito:
        return None
    return _REGIAO_PT.get(distrito.lower().strip())


# ---------------------------------------------------------------------------
# Deduplicação
# ---------------------------------------------------------------------------

def deduplicate(eventos: list[Concentracao]) -> list[Concentracao]:
    """
    Remove duplicados da lista de eventos.

    Dois eventos são considerados duplicados se:
      - Mesmo país
      - Mesma data_inicio
      - Similaridade do nome ≥ 0.80 (medida com SequenceMatcher do difflib)

    Quando duplicados são encontrados, mantém o de fonte com maior prioridade
    e enriquece-o com campos extras do outro (preço, contacto, url_maps).

    Prioridade de fontes:
      PT: motardfm > fmp
      ES: eventomotor > concentracionesdemotos

    Args:
        eventos: Lista de Concentracao com potenciais duplicados.

    Returns:
        Lista sem duplicados, por ordem de data_inicio.
    """
    PRIORIDADE = {
        "motardfm": 0,
        "fmp": 1,
        "eventomotor": 0,
        "concentracionesdemotos": 1,
    }

    # Indexar por (pais, data_inicio) para acelerar a pesquisa
    grupos: dict[tuple[str, str], list[Concentracao]] = {}
    for ev in eventos:
        chave = (ev.pais, ev.data_inicio)
        grupos.setdefault(chave, []).append(ev)

    resultado: list[Concentracao] = []
    ids_processados: set[str] = set()

    for (pais, data), grupo in grupos.items():
        if len(grupo) == 1:
            resultado.append(grupo[0])
            continue

        # Dentro do grupo, detectar pares similares
        processados_no_grupo: set[int] = set()

        for i, ev_a in enumerate(grupo):
            if i in processados_no_grupo:
                continue

            melhor = ev_a
            for j, ev_b in enumerate(grupo):
                if i == j or j in processados_no_grupo:
                    continue

                sim = difflib.SequenceMatcher(
                    None,
                    ev_a.nome.lower(),
                    ev_b.nome.lower(),
                ).ratio()

                if sim >= 0.80:
                    logger.debug(
                        "Duplicado detectado (sim=%.2f): '%s' (%s) vs '%s' (%s)",
                        sim, ev_a.nome, ev_a.fonte, ev_b.nome, ev_b.fonte,
                    )
                    processados_no_grupo.add(j)

                    # Decidir qual manter (menor prioridade = mais autoritativo)
                    pri_a = PRIORIDADE.get(ev_a.fonte, 99)
                    pri_b = PRIORIDADE.get(ev_b.fonte, 99)
                    principal, secundario = (ev_a, ev_b) if pri_a <= pri_b else (ev_b, ev_a)

                    # Enriquecer o principal com campos do secundário que estejam vazios
                    campos_enriquecimento = [
                        "preco", "contacto_telefone", "contacto_email",
                        "url_maps", "descricao", "distrito_provincia",
                        "regiao", "url_fonte_oficial",
                    ]
                    for campo in campos_enriquecimento:
                        if getattr(principal, campo) is None and getattr(secundario, campo) is not None:
                            setattr(principal, campo, getattr(secundario, campo))

                    melhor = principal

            processados_no_grupo.add(i)
            resultado.append(melhor)

    # Ordenar por data_inicio
    resultado.sort(key=lambda e: e.data_inicio)
    logger.info("Deduplicação: %d eventos → %d após remoção de duplicados.", len(eventos), len(resultado))
    return resultado
