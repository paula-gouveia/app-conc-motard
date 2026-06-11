-- =============================================================================
-- schema.sql — Estrutura da base de dados no Supabase
--
-- COMO USAR:
--   1. No dashboard do Supabase: SQL Editor → New query
--   2. Cola este ficheiro completo e clica em "Run"
--   3. Deves ver "Success. No rows returned" para cada statement
--
-- Este ficheiro é idempotente: podes correr várias vezes sem erros
-- (todos os CREATE usam IF NOT EXISTS / OR REPLACE).
-- =============================================================================


-- ---------------------------------------------------------------------------
-- Tabela principal: concentracoes
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS concentracoes (
    -- Identificador estável de 12 chars (SHA-256 truncado de pais|fonte|nome|data_inicio).
    -- Calculado pelo scraper → permite upserts idempotentes:
    -- o mesmo evento scrapeado amanhã tem o mesmo ID que hoje.
    id                  TEXT            PRIMARY KEY,

    -- Dados essenciais
    nome                TEXT            NOT NULL,
    data_inicio         DATE,
    data_fim            DATE,

    -- Origem
    pais                TEXT            NOT NULL    CHECK (pais IN ('PT', 'ES')),
    fonte               TEXT            NOT NULL    CHECK (fonte IN ('motardfm', 'fmp', 'eventomotor', 'concentracionesdemotos')),
    tipo_evento         TEXT            NOT NULL,   -- Ver taxonomia em normalizer.py
    tier                SMALLINT        NOT NULL    DEFAULT 2,   -- 1=FMP oficial; 2=regular

    -- Flags
    tem_cartaz          BOOLEAN         NOT NULL    DEFAULT FALSE,
    cancelado           BOOLEAN         NOT NULL    DEFAULT FALSE,
    sem_info            BOOLEAN         NOT NULL    DEFAULT FALSE,
    geocoding_uncertain BOOLEAN         NOT NULL    DEFAULT FALSE,

    -- Organização
    organizador         TEXT,

    -- Localização textual
    localidade          TEXT,
    distrito_provincia  TEXT,           -- Distrito (PT) ou Província (ES)
    regiao              TEXT,           -- NUT II (PT) ou Comunidade Autónoma (ES)

    -- Coordenadas GPS
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,

    -- URLs
    url_cartaz          TEXT,
    url_evento          TEXT,
    url_fonte_oficial   TEXT,
    url_maps            TEXT,

    -- Conteúdo extra
    descricao           TEXT,
    preco               TEXT,
    contacto_telefone   TEXT,
    contacto_email      TEXT,

    -- Auditoria
    criado_em           TIMESTAMPTZ     NOT NULL    DEFAULT NOW(),
    atualizado_em       TIMESTAMPTZ     NOT NULL    DEFAULT NOW()
);

COMMENT ON TABLE concentracoes IS
    'Concentrações e eventos motard em Portugal e Espanha, scrapeados de motardfm.org, fmp.pt, eventomotor.com e concentracionesdemotos.com.';

COMMENT ON COLUMN concentracoes.id IS
    'SHA-256[:12] de pais|fonte|nome_lower|data_inicio — estável entre runs do scraper.';
COMMENT ON COLUMN concentracoes.tier IS
    '1 = evento oficial FMP; 2 = evento regular de clube/grupo.';
COMMENT ON COLUMN concentracoes.sem_info IS
    'True se a fonte marcou o evento como "SEM INFO" (apenas MotardFM).';
COMMENT ON COLUMN concentracoes.geocoding_uncertain IS
    'True se as coordenadas vieram de um fallback menos específico (distrito em vez de localidade).';


-- ---------------------------------------------------------------------------
-- Índices
-- ---------------------------------------------------------------------------

-- Query principal: eventos futuros ordenados por data
CREATE INDEX IF NOT EXISTS idx_conc_data_inicio
    ON concentracoes (data_inicio);

CREATE INDEX IF NOT EXISTS idx_conc_data_fim
    ON concentracoes (data_fim);

-- Filtros frequentes
CREATE INDEX IF NOT EXISTS idx_conc_pais
    ON concentracoes (pais);

CREATE INDEX IF NOT EXISTS idx_conc_fonte
    ON concentracoes (fonte);

CREATE INDEX IF NOT EXISTS idx_conc_tipo_evento
    ON concentracoes (tipo_evento);

CREATE INDEX IF NOT EXISTS idx_conc_cancelado
    ON concentracoes (cancelado);

-- Para o mapa: filtrar por país + coordenadas não nulas
CREATE INDEX IF NOT EXISTS idx_conc_pais_coords
    ON concentracoes (pais, latitude, longitude)
    WHERE latitude IS NOT NULL AND longitude IS NOT NULL;

-- Query mais frequente: eventos futuros, por data
CREATE INDEX IF NOT EXISTS idx_conc_data_inicio_nome
    ON concentracoes (data_inicio, nome);


-- ---------------------------------------------------------------------------
-- Trigger: atualizar atualizado_em automaticamente
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION set_atualizado_em()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    NEW.atualizado_em = NOW();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_concentracoes_atualizado_em ON concentracoes;
CREATE TRIGGER trg_concentracoes_atualizado_em
    BEFORE UPDATE ON concentracoes
    FOR EACH ROW
    EXECUTE FUNCTION set_atualizado_em();


-- ---------------------------------------------------------------------------
-- Row Level Security (RLS)
--
-- Leitura pública (anon key) → a app frontend pode ler sem autenticação.
-- Escrita apenas com service_role key → o scraper usa esta chave,
-- que bypassa o RLS por definição no Supabase.
-- ---------------------------------------------------------------------------

ALTER TABLE concentracoes ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "leitura_publica" ON concentracoes;

CREATE POLICY "leitura_publica" ON concentracoes
    FOR SELECT
    USING (true);


-- ---------------------------------------------------------------------------
-- Views úteis
-- ---------------------------------------------------------------------------

-- Eventos futuros (os que a app mostra por defeito)
CREATE OR REPLACE VIEW concentracoes_futuras AS
SELECT *
FROM   concentracoes
WHERE  data_inicio >= CURRENT_DATE
  AND  cancelado = FALSE
ORDER  BY data_inicio, nome;

COMMENT ON VIEW concentracoes_futuras IS
    'Eventos a partir de hoje, não cancelados, ordenados cronologicamente.';

-- Só Portugal
CREATE OR REPLACE VIEW concentracoes_pt AS
SELECT *
FROM   concentracoes_futuras
WHERE  pais = 'PT';

-- Só Espanha
CREATE OR REPLACE VIEW concentracoes_es AS
SELECT *
FROM   concentracoes_futuras
WHERE  pais = 'ES';
