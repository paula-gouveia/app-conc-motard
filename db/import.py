"""
db/import.py — Importar o JSON do scraper para o Supabase.

Uso:
    python db/import.py                        # importa data/concentracoes.json
    python db/import.py data/outro.json        # importa ficheiro específico

Requer as variáveis de ambiente (via .env ou GitHub Secrets):
    SUPABASE_URL          URL do projeto (ex: https://xxxx.supabase.co)
    SUPABASE_SERVICE_KEY  Chave service_role (permite escrita, bypassa RLS)

Como funciona o upsert:
    Para cada evento no JSON, faz INSERT ... ON CONFLICT (id) DO UPDATE.
    - ID não existe → insere (novo evento)
    - ID já existe  → actualiza todos os campos excepto criado_em
    O campo atualizado_em é gerido pelo trigger na BD.

    O ID é SHA-256[:12] de (pais|fonte|nome|data_inicio), estável entre runs.
    O mesmo evento scrapeado na semana seguinte tem o mesmo ID → UPDATE.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import sys
from datetime import datetime
from pathlib import Path

# Carregar .env se existir (desenvolvimento local)
# Em produção (GitHub Actions) as variáveis vêm de os.environ directamente
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# truststore: necessário em Windows com proxy corporativo que inspecciona HTTPS
if platform.system() == "Windows":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

from supabase import create_client

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuração
# ---------------------------------------------------------------------------
DEFAULT_JSON = Path(__file__).parent.parent / "data" / "concentracoes.json"
BATCH_SIZE = 100  # seguro para o rate limit do Supabase


def _normalizar_url(url: str) -> str:
    """Remove /rest/v1 do URL se o utilizador o tiver copiado do dashboard."""
    url = url.rstrip("/")
    if url.endswith("/rest/v1"):
        url = url[:-len("/rest/v1")]
    return url


def _get_client():
    url = _normalizar_url(os.environ.get("SUPABASE_URL", "").strip())
    key = os.environ.get("SUPABASE_SERVICE_KEY", "").strip()

    if not url or not key:
        logger.error(
            "Variáveis SUPABASE_URL e/ou SUPABASE_SERVICE_KEY não definidas.\n"
            "Cria um ficheiro .env na raiz do projecto com:\n"
            "  SUPABASE_URL=https://<projecto>.supabase.co\n"
            "  SUPABASE_SERVICE_KEY=<service_role_key>"
        )
        sys.exit(1)

    return create_client(url, key)


def _preparar_registo(ev: dict) -> dict:
    """
    Converte um evento do JSON para o formato da tabela concentracoes.

    Notas de conversão:
    - Campos None → NULL no Supabase (compatível com colunas opcionais)
    - data_inicio / data_fim já estão em YYYY-MM-DD → compatível com DATE
    - latitude/longitude são float ou None → compatível com DOUBLE PRECISION
    - criado_em não é enviado (gerido por DEFAULT NOW() na BD)
    - atualizado_em não é enviado (gerido pelo trigger da BD)
    """
    return {
        "id":                   ev["id"],
        "nome":                 ev["nome"],
        "data_inicio":          ev.get("data_inicio"),
        "data_fim":             ev.get("data_fim"),
        "pais":                 ev["pais"],
        "fonte":                ev["fonte"],
        "tipo_evento":          ev["tipo_evento"],
        "tier":                 ev.get("tier", 2),
        "tem_cartaz":           ev.get("tem_cartaz", False),
        "cancelado":            ev.get("cancelado", False),
        "sem_info":             ev.get("sem_info", False),
        "geocoding_uncertain":  ev.get("geocoding_uncertain", False),
        "organizador":          ev.get("organizador"),
        "localidade":           ev.get("localidade"),
        "distrito_provincia":   ev.get("distrito_provincia"),
        "regiao":               ev.get("regiao"),
        "latitude":             ev.get("latitude"),
        "longitude":            ev.get("longitude"),
        "url_cartaz":           ev.get("url_cartaz"),
        "url_evento":           ev.get("url_evento"),
        "url_fonte_oficial":    ev.get("url_fonte_oficial"),
        "url_maps":             ev.get("url_maps"),
        "descricao":            ev.get("descricao"),
        "preco":                ev.get("preco"),
        "contacto_telefone":    ev.get("contacto_telefone"),
        "contacto_email":       ev.get("contacto_email"),
    }


def _deduplicar(registos: list[dict]) -> list[dict]:
    """
    Garante que não há IDs repetidos antes do upsert.

    O PostgreSQL rejeita batches com o mesmo id duplicado:
    'ON CONFLICT DO UPDATE command cannot affect row a second time'.
    Mantém o último registo visto para cada ID (o mais recente).
    """
    unicos: dict[str, dict] = {}
    for r in registos:
        unicos[r["id"]] = r
    return list(unicos.values())


def importar(json_path: Path | None = None) -> None:
    json_path = json_path or DEFAULT_JSON

    if not json_path.exists():
        logger.error("Ficheiro não encontrado: %s", json_path)
        sys.exit(1)

    logger.info("A ler %s …", json_path)
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)

    eventos_raw = data.get("eventos", [])
    meta = data.get("meta", {})

    logger.info(
        "JSON: %d eventos (gerado em %s)",
        len(eventos_raw),
        meta.get("gerado_em", "?"),
    )

    if not eventos_raw:
        logger.warning("Nenhum evento no JSON. Nada a importar.")
        return

    registos = [_preparar_registo(e) for e in eventos_raw]
    total_raw = len(registos)
    registos = _deduplicar(registos)

    if len(registos) < total_raw:
        logger.info(
            "Deduplicados: %d → %d registos (%d ignorados)",
            total_raw, len(registos), total_raw - len(registos),
        )

    client = _get_client()
    logger.info("Ligado ao Supabase: %s", _normalizar_url(os.environ.get("SUPABASE_URL", "")))

    inicio = datetime.now()
    total_ok = 0
    erros = 0
    total_batches = (len(registos) + BATCH_SIZE - 1) // BATCH_SIZE

    for i in range(0, len(registos), BATCH_SIZE):
        batch = registos[i: i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        try:
            client.table("concentracoes").upsert(batch, on_conflict="id").execute()
            total_ok += len(batch)
            logger.info("  Batch %d/%d: %d registos OK", batch_num, total_batches, len(batch))
        except Exception as e:
            erros += 1
            logger.error("  Batch %d/%d FALHOU: %s", batch_num, total_batches, e)

    duracao = (datetime.now() - inicio).total_seconds()
    logger.info("=" * 50)
    if erros == 0:
        logger.info("Concluído em %.1f s — %d eventos importados/actualizados.", duracao, total_ok)
    else:
        logger.warning(
            "Concluído com %d erros — %d/%d eventos importados.",
            erros, total_ok, len(registos),
        )
    logger.info("=" * 50)


if __name__ == "__main__":
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    importar(path)
