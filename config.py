"""
config.py — Configuração central do scraper.

Todos os parâmetros ajustáveis estão aqui: URLs das fontes, caminhos de
ficheiros, e a frequência do scraper.

Para alterar a frequência do scraper, edita SCRAPER_SCHEDULE abaixo.
O valor é uma expressão cron (minuto hora dia mês dia-da-semana).
Depois actualiza o mesmo valor em .github/workflows/scraper.yml.
"""

# ---------------------------------------------------------------------------
# Frequência do scraper
# ---------------------------------------------------------------------------
# Opção A — semanal (domingos às 06:00 UTC) — ACTIVO por omissão
SCRAPER_SCHEDULE = "0 6 * * 0"

# Opção B — diário (06:00 UTC) — descomentar para activar
# SCRAPER_SCHEDULE = "0 6 * * *"

# ---------------------------------------------------------------------------
# Ano do calendário
# ---------------------------------------------------------------------------
ANO = 2026

# ---------------------------------------------------------------------------
# URLs das fontes
# ---------------------------------------------------------------------------
MOTARDFM_URL = "https://motardfm.org/calendario/"

# ATENÇÃO: o URL da FMP muda a cada ano. Verificar em Janeiro de cada ano
# em https://www.fmp.pt/categoria/noticias/mototurismo/
FMP_URL = "https://www.fmp.pt/noticias/mototurismo/calendario-de-mototurismo-2026/23487/"

EVENTOMOTOR_URL = "https://www.eventomotor.com/concentraciones-moteras-2026"

CONCENTRACIONESDEMOTOS_URL = "https://www.concentracionesdemotos.com/concentraciones/"

# Páginas mensais do concentracionesdemotos que não aparecem na listagem principal
CONCENTRACIONESDEMOTOS_MESES_ES = [
    "https://www.concentracionesdemotos.com/julio-2026",
    "https://www.concentracionesdemotos.com/agosto-2026",
    "https://www.concentracionesdemotos.com/septiembre-2026",
    "https://www.concentracionesdemotos.com/octubre-2026",
    "https://www.concentracionesdemotos.com/noviembre-2026",
    "https://www.concentracionesdemotos.com/diciembre-2026",
]

# ---------------------------------------------------------------------------
# Caminhos de ficheiros
# ---------------------------------------------------------------------------
DATA_DIR = "data"
OUTPUT_FILE = "data/concentracoes.json"
LOG_DIR = "logs"
