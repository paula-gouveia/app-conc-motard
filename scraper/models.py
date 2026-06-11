"""
models.py — Estrutura de dados de uma Concentração Motard.

Usa dataclass (biblioteca padrão Python, sem dependências externas).

O ID é gerado automaticamente com base em pais + fonte + nome + data_inicio,
o que garante estabilidade entre execuções: o mesmo evento scrapeado amanhã
produz o mesmo ID que hoje, facilitando atualizações incrementais.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Optional


@dataclass
class Concentracao:
    # --- Campos obrigatórios ---
    nome: str                       # Nome limpo do evento
    data_inicio: str                # ISO date: YYYY-MM-DD
    pais: str                       # "PT" ou "ES"
    fonte: str                      # "motardfm" | "fmp" | "eventomotor" | "concentracionesdemotos"
    tipo_evento: str                # Ver taxonomia em normalizer.py
    tier: int                       # 1 = evento FMP oficial; 2 = evento regular
    tem_cartaz: bool                # True se existe imagem do cartaz
    cancelado: bool                 # True se marcado como cancelado na fonte
    sem_info: bool                  # True se a fonte marcou "SEM INFO" (PT)
    geocoding_uncertain: bool       # True se a geocodificação pode estar errada
    atualizado_em: str              # ISO datetime da última actualização pelo scraper

    # --- Campos opcionais ---
    data_fim: Optional[str] = None              # ISO date; igual a data_inicio se 1 dia
    organizador: Optional[str] = None          # Nome do clube/grupo organizador
    localidade: Optional[str] = None           # Cidade/vila do evento
    distrito_provincia: Optional[str] = None   # Distrito PT ou Província ES
    regiao: Optional[str] = None               # Região NUT II (PT) ou Comunidade Autónoma (ES)
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    url_cartaz: Optional[str] = None           # URL da imagem do cartaz
    url_evento: Optional[str] = None           # URL da página do evento na fonte
    url_fonte_oficial: Optional[str] = None    # URL oficial do organizador (via EventoMotor)
    descricao: Optional[str] = None            # Texto descritivo (quando disponível)
    preco: Optional[str] = None                # Preço (texto livre, p.ex. "30€ / 10€ domingo")
    contacto_telefone: Optional[str] = None
    contacto_email: Optional[str] = None
    url_maps: Optional[str] = None             # Link Google Maps ou equivalente

    # --- ID gerado automaticamente (não passar ao construtor) ---
    id: str = field(init=False)

    def __post_init__(self) -> None:
        """
        Gera um ID estável de 12 chars com SHA-256.

        Componentes do hash: pais + fonte + nome_normalizado + data_inicio.
        Usar SHA-256 (em vez de MD5) é boa prática mesmo para IDs não
        criptográficos — colisões são ainda menos prováveis.

        O ID muda se o nome ou a data de início mudarem na fonte (trata-se
        como remoção + adição nova no update incremental).
        """
        chave = f"{self.pais}|{self.fonte}|{self.nome.lower().strip()}|{self.data_inicio}"
        self.id = hashlib.sha256(chave.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict:
        """Converte a dataclass para dicionário, pronto para JSON."""
        return asdict(self)
