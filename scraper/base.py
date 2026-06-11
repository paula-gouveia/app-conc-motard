"""
base.py — Utilitários HTTP partilhados por todos os scrapers.

Contém:
- make_session(): cria uma sessão HTTP com headers de browser realistas
- get_soup(): pedido HTTP com retry automático + BeautifulSoup

Porquê usar Session em vez de requests.get() directo?
  Session reutiliza a ligação TCP (keep-alive), reduzindo latência quando
  fazemos múltiplos pedidos ao mesmo domínio.

Porquê o delay entre pedidos?
  Cortesia com os servidores. Sem delay, um scraper pode fazer centenas de
  pedidos por segundo e sobrecarregar o site, ou levar a um ban de IP.
  1–1.5 segundos é um valor razoável para sites não-críticos.
"""

from __future__ import annotations

import os
import platform
import time
import logging

import requests
from bs4 import BeautifulSoup

# truststore: usar os certificados do sistema em vez do bundle certifi.
# Em redes Windows com proxy corporativo ou antivírus que inspecciona HTTPS,
# o certifi falha. truststore resolve isso usando os certificados do OS.
# Em Linux (GitHub Actions) o SSL do sistema funciona sem isto.
if platform.system() == "Windows":
    try:
        import truststore
        truststore.inject_into_ssl()
    except ImportError:
        pass

logger = logging.getLogger(__name__)

# User-Agent de browser real.
# Porquê não usar "ConcentracoesBot/1.0"?
# Alguns sites WordPress/Elementor usam WAFs (Cloudflare, Wordfence) que
# bloqueiam pedidos com UAs não-browser com 403. Um UA de Chrome evita-os.
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)

BROWSER_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "pt-PT,pt;q=0.9,es;q=0.8,en-US;q=0.7,en;q=0.6",
    # Sem "br" (Brotli): requests não descomprime Brotli nativamente.
    # Incluir "br" no Accept-Encoding faria o servidor responder com Brotli
    # e nós receberíamos bytes ininterpretáveis.
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0",
}


def _ssl_verify() -> bool:
    """Controla verificação SSL via variável de ambiente SCRAPER_SSL_VERIFY."""
    value = os.environ.get("SCRAPER_SSL_VERIFY", "1").strip().lower()
    return value not in ("0", "false", "no", "off")


def make_session() -> requests.Session:
    """Cria e devolve uma sessão HTTP com headers de browser e timeout padrão."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    session.verify = _ssl_verify()
    if not session.verify:
        logger.warning("Verificação SSL desactivada (SCRAPER_SSL_VERIFY=0).")
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    return session


def get_soup(
    url: str,
    session: requests.Session | None = None,
    delay: float = 1.0,
    timeout: int = 20,
    retries: int = 3,
) -> BeautifulSoup | None:
    """
    Faz um pedido GET e devolve o HTML como BeautifulSoup.

    Args:
        url:     URL a aceder.
        session: Sessão HTTP a reutilizar (cria uma nova se None).
        delay:   Segundos de espera ANTES do pedido (cortesia com o servidor).
        timeout: Timeout em segundos por pedido.
        retries: Número de tentativas em caso de erro transitório.

    Returns:
        Objecto BeautifulSoup, ou None se todos os retries falharem.
    """
    if session is None:
        session = make_session()

    for tentativa in range(1, retries + 1):
        if delay > 0:
            time.sleep(delay)
        try:
            resp = session.get(url, timeout=timeout)
            resp.raise_for_status()
            # html.parser é o parser built-in do Python — sem dependências
            # externas e suficientemente robusto para HTML de sites WordPress.
            return BeautifulSoup(resp.text, "html.parser")
        except requests.exceptions.HTTPError as e:
            logger.warning("HTTP %s em %s (tentativa %d/%d)", e.response.status_code, url, tentativa, retries)
            if e.response.status_code in (403, 404, 410):
                break  # Erros permanentes — não vale a pena repetir
        except requests.exceptions.ConnectionError:
            logger.warning("Erro de ligação em %s (tentativa %d/%d)", url, tentativa, retries)
        except requests.exceptions.Timeout:
            logger.warning("Timeout em %s (tentativa %d/%d)", url, tentativa, retries)
        except requests.exceptions.RequestException as e:
            logger.warning("Erro inesperado em %s: %s (tentativa %d/%d)", url, e, tentativa, retries)

        if tentativa < retries:
            time.sleep(2 ** tentativa)  # Backoff exponencial: 2s, 4s

    logger.error("Não foi possível aceder a: %s após %d tentativas.", url, retries)
    return None
