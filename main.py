"""
main.py — Ponto de entrada do scraper de concentrações motard.

Executa todos os scrapers, agrega os resultados, remove duplicados,
e escreve o ficheiro JSON final.

Uso:
    python main.py                  # usa o ANO definido em config.py
    python main.py --ano 2027       # substitui o ANO
    python main.py --dry-run        # corre mas não escreve o ficheiro

Porquê um ficheiro JSON único (e não um por fonte)?
  O frontend vai carregar um único ficheiro. Ter os dados agregados e
  deduplicados no servidor simplifica muito a lógica do cliente.
  Se quisermos depurar uma fonte específica, podemos filtrar por `fonte`.

Estrutura do output JSON:
  {
    "meta": {
      "gerado_em": "2026-06-01T06:00:00",
      "total_eventos": 312,
      "por_fonte": {"motardfm": 180, "fmp": 45, "eventomotor": 60, "concentracionesdemotos": 27}
    },
    "eventos": [ <lista de Concentracao.to_dict()> ]
  }
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

# Importar configurações
import config
from scraper.base import make_session
from scraper import motardfm, fmp, eventomotor, concentracionesdemotos
from scraper.normalizer import deduplicate

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def _configurar_logging() -> None:
    """Configura logging para consola + ficheiro."""
    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(exist_ok=True)

    data_hoje = datetime.utcnow().strftime("%Y%m%d_%H%M")
    log_file = log_dir / f"scraper_{data_hoje}.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("geopy").setLevel(logging.WARNING)


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------

def _escrever_json(eventos, caminho: str) -> None:
    """Serializa a lista de eventos para JSON com metadados."""
    path = Path(caminho)
    path.parent.mkdir(exist_ok=True)

    por_fonte: dict[str, int] = {}
    for ev in eventos:
        por_fonte[ev.fonte] = por_fonte.get(ev.fonte, 0) + 1

    output = {
        "meta": {
            "gerado_em": datetime.utcnow().isoformat(),
            "total_eventos": len(eventos),
            "por_fonte": por_fonte,
        },
        "eventos": [ev.to_dict() for ev in eventos],
    }

    with open(path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    logging.getLogger(__name__).info("JSON escrito em: %s (%d eventos)", path, len(eventos))


# ---------------------------------------------------------------------------
# Ponto de entrada
# ---------------------------------------------------------------------------

def main(ano: int = None, dry_run: bool = False) -> None:
    logger = logging.getLogger(__name__)

    if ano is None:
        ano = config.ANO

    logger.info("=" * 60)
    logger.info("SCRAPER CONCENTRAÇÕES MOTARD — ano %d", ano)
    logger.info("=" * 60)

    session = make_session()
    todos_eventos = []

    # --- PT: MotardFM ---
    try:
        eventos_motardfm = motardfm.run(session=session, ano=ano)
        todos_eventos.extend(eventos_motardfm)
        logger.info("motardfm: %d eventos", len(eventos_motardfm))
    except Exception as e:
        logger.error("Erro no scraper motardfm: %s", e, exc_info=True)

    # --- PT: FMP ---
    try:
        eventos_fmp = fmp.run(url=config.FMP_URL, session=session, ano=ano)
        todos_eventos.extend(eventos_fmp)
        logger.info("fmp: %d eventos", len(eventos_fmp))
    except Exception as e:
        logger.error("Erro no scraper FMP: %s", e, exc_info=True)

    # --- ES: EventoMotor ---
    try:
        eventos_eventomotor = eventomotor.run(url=config.EVENTOMOTOR_URL, session=session, ano=ano)
        todos_eventos.extend(eventos_eventomotor)
        logger.info("eventomotor: %d eventos", len(eventos_eventomotor))
    except Exception as e:
        logger.error("Erro no scraper eventomotor: %s", e, exc_info=True)

    # --- ES: ConcentracionesDeMoots ---
    try:
        eventos_cdm = concentracionesdemotos.run(
            url_principal=config.CONCENTRACIONESDEMOTOS_URL,
            urls_mensais=config.CONCENTRACIONESDEMOTOS_MESES_ES,
            session=session,
            ano=ano,
        )
        todos_eventos.extend(eventos_cdm)
        logger.info("concentracionesdemotos: %d eventos", len(eventos_cdm))
    except Exception as e:
        logger.error("Erro no scraper concentracionesdemotos: %s", e, exc_info=True)

    logger.info("-" * 60)
    logger.info("Total antes de deduplicação: %d", len(todos_eventos))

    # --- Deduplicação ---
    eventos_finais = deduplicate(todos_eventos)
    logger.info("Total após deduplicação: %d", len(eventos_finais))

    # --- Escrever output ---
    if dry_run:
        logger.info("[DRY RUN] Não foi escrito nenhum ficheiro.")
    else:
        _escrever_json(eventos_finais, config.OUTPUT_FILE)

    logger.info("=" * 60)
    logger.info("CONCLUÍDO")
    logger.info("=" * 60)


if __name__ == "__main__":
    _configurar_logging()

    parser = argparse.ArgumentParser(description="Scraper de concentrações motard PT+ES")
    parser.add_argument("--ano", type=int, default=None, help="Ano a scraper (default: config.ANO)")
    parser.add_argument("--dry-run", action="store_true", help="Correr sem escrever o JSON de output")
    args = parser.parse_args()

    main(ano=args.ano, dry_run=args.dry_run)
