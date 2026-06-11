# Plano de Desenvolvimento — App Concentrações Motard

> Documento de planeamento por fases. Não contém código nem ficheiros técnicos.
> Atualizado: 2026-06-11

---

## Fontes de dados identificadas

### Portugal — Fonte primária

#### motardfm.org/calendario/
**URL:** https://motardfm.org/calendario/

O site mais completo e melhor mantido para Portugal. Em operação desde o ano 2000, tem uma comunidade ativa de grupos motards que enviam os seus eventos diretamente. Atualizado com muita frequência (última atualização: 9 de junho de 2026).

**Qualidade dos dados: ALTA**

- Mais de 200 eventos para 2026 (de junho a dezembro), cobrindo Portugal continental e ilhas
- Estrutura consistente: `DD – nome do evento – local (tipo) [CARTAZ]`
- Eventos multi-dia no formato `DD a DD –` ou `DD e DD –`
- Usa cor para assinalar alterações (vermelho), novidades (azul) e eventos com cartaz (laranja)
- Muitos eventos têm página própria com detalhes (local, cartaz, contacto)
- É a fonte de referência que os outros sites agregam

**Limitações:**
- O conteúdo é texto livre (não uma API nem JSON estruturado) — requer parsing
- Alguns eventos têm poucos detalhes ("SEM INFO")
- Cancelamentos podem demorar a aparecer

---

#### allstarsradio.net/agenda-motard/
**URL:** https://allstarsradio.net/agenda-motard/

Rádio online portuguesa com uma secção de agenda motard. Declara explicitamente que agrega a partir de FMP, MotardFM e clubes diretamente.

**Qualidade dos dados: BOA (mas derivada)**

- Lista complementar com alguns eventos extras não presentes no MotardFM
- Mesmo formato textual
- Útil como fonte de validação cruzada

**Nota:** Como agrega do MotardFM, não faz sentido usar como fonte primária. Útil para identificar eventos que eventualmente não chegaram ao MotardFM.

---

#### fmp.pt (Federação de Motociclismo de Portugal)
**URL:** https://www.fmp.pt/noticias/mototurismo/calendario-de-mototurismo-2026/23487/

Fonte oficial da federação nacional. Publica o calendário oficial de concentrações e eventos de mototurismo sob a alçada da FMP.

**Qualidade dos dados: MUITO ALTA mas seletiva**

- Apenas ~30 concentrações "oficialmente registadas" + Troféu Nacional de Moto-Ralis Turísticos + eventos FMP (Portugal Lés-a-Lés, Dia Nacional do Motociclista)
- Dados fiáveis e verificados
- Serve como marcador dos "grandes eventos" do ano

**Nota:** Útil para destacar eventos tier-1. Não substitui o MotardFM em volume.

---

### Espanha — Fonte primária

#### eventomotor.com
**URL:** https://www.eventomotor.com/concentraciones-moteras-2026

O site mais estruturado para Espanha. Cada evento tem uma página própria com campos bem definidos.

**Qualidade dos dados: BOA**

- 113 eventos registados para 2026 (63 futuros visíveis na página)
- Dados por evento: data, localidade, província, comunidade autónoma, tipo (Concentración, Trail, Custom, etc.), disciplina
- HTML limpo e previsível, favorável a scraping
- Inclui eventos históricos do ano (útil para referência)

**Limitações:**
- Volume menor que o MotardFM (menos eventos pequenos/locais)
- Foco em toda a Península (não só Galiza/Norte)

---

#### concentracionesdemotos.com
**URL:** https://www.concentracionesdemotos.com/concentraciones/

Site espanhol com filtros por comunidade autónoma, província, tipo e mês. Em operação desde 2009.

**Qualidade dos dados: MODERADA**

- Menos eventos visíveis que o EventoMotor para o mesmo período
- Tem filtro por comunidade autónoma (útil para focar Galiza e Norte de Espanha)
- Páginas individuais por evento
- Permite submissão pública de eventos

**Nota:** Boa opção secundária para cobrir eventos pequenos da Galiza e Norte de Espanha que não chegam ao EventoMotor.

---

## Decisão sobre fontes

| Prioridade | Fonte | Cobertura |
|---|---|---|
| 1 | motardfm.org | Portugal — principal |
| 2 | fmp.pt | Portugal — grandes eventos oficiais |
| 3 | eventomotor.com | Espanha — principal |
| 4 | allstarsradio.net | Portugal — validação cruzada |
| 5 | concentracionesdemotos.com | Espanha — complemento para Galiza/Norte |

---

## Fases de desenvolvimento

---

### Fase 0 — Análise de fontes e modelo de dados *(atual)*

**Objetivo:** Perceber exatamente que campos existem em cada fonte e definir o esquema comum de dados antes de escrever uma linha de código.

Tarefas:
1. Mapear os campos disponíveis em cada fonte (nome, datas, local, distrito, tipo de evento, link cartaz, contacto, coordenadas GPS)
2. Definir o modelo de dados unificado (o "contrato" entre o scraper e a base de dados)
3. Classificar os tipos de evento e criar uma taxonomia consistente (concentração, aniversário, motochurrasco, moto-rali, encontro, etc.)
4. Decidir estratégia para eventos duplicados entre fontes (deduplicação)
5. Definir campos obrigatórios vs opcionais

**Entregável:** Documento de modelo de dados + taxonomia de tipos de evento

---

### Fase 1 — Scraping e normalização de dados

**Objetivo:** Extrair e limpar os dados de cada fonte para um formato JSON estruturado e consistente.

Tarefas:
1. Scraper para o MotardFM (parsing do texto livre por regex — formato bem previsível)
2. Scraper para o FMP (extração do artigo de calendário)
3. Scraper para o EventoMotor (HTML estruturado, mais simples)
4. Scraper para concentracionesdemotos.com (Espanha — Península completa)
5. Script de limpeza e normalização (datas, localizações, tipos)
6. Geocodificação automática via Nominatim (OpenStreetMap) — cobre bem as localidades ibéricas; eventos com localidade ambígua ou muito pequena ficam marcados com flag `geocoding_uncertain: true` para revisão posterior, sem bloquear o fluxo
7. Estratégia de deduplicação entre fontes (dois eventos são considerados duplicados se tiverem nome similar + mesma data + mesmo país)

**Entregável:** Ficheiro `data/concentracoes.json` com todos os eventos normalizados

**Nota técnica:** Stack Python (consistente com o projeto das feiras medievais), com `requests` + `BeautifulSoup` para scraping e `re` para parsing do texto livre do MotardFM.

---

### Fase 2 — Persistência de dados (JSON)

**Objetivo:** Organizar os dados em JSON estruturado e preparar para atualizações incrementais.

Decisão: **JSON puro** (sem SQLite). O volume esperado (~500–700 eventos/ano) é perfeitamente gerível em JSON, evita dependências extra, e facilita o deploy estático do frontend.

Tarefas:
1. Definir schema final do JSON (`data/concentracoes.json`)
2. Script de atualização incremental: compara o JSON existente com o resultado do scraper e só altera o que mudou, preservando campos adicionados manualmente (ex: correções de geocodificação)
3. Campos derivados calculados em runtime pelo frontend: estado do evento (passado / a decorrer / futuro)
4. Manter um `data/concentracoes_YYYY-MM-DD.json` como backup da última versão antes de cada atualização

**Entregável:** `data/concentracoes.json` versionado e script de atualização incremental

---

### Fase 3 — Backend / API

**Objetivo:** Expor os dados da base de dados através de uma API simples para o frontend consumir.

Tarefas:
1. Endpoints principais:
   - `GET /concentracoes` — listar com filtros (país, distrito, mês, tipo, estado)
   - `GET /concentracoes/:id` — detalhes de um evento
   - `GET /concentracoes/proximas` — eventos futuros ordenados por data
2. Filtros: por país (PT/ES), por distrito/região, por intervalo de datas, por tipo de evento
3. Paginação
4. Cache simples (os dados não mudam em tempo real)

**Stack:** Python + FastAPI (como nas feiras medievais) ou Flask, dependendo da preferência

---

### Fase 4 — Frontend

**Objetivo:** Interface para o utilizador descobrir e filtrar eventos.

Tarefas:
1. Vista de lista: eventos ordenados por data, com indicação de passado/futuro
2. Vista de calendário: mês a mês
3. Vista de mapa: marcadores por localização (com clustering)
4. Filtros: país, região/distrito, mês, tipo de evento
5. Destaque para grandes eventos (eventos FMP / com cartaz)
6. Página de detalhe por evento
7. Design responsivo (mobile-first — os motards usam o telemóvel)

**Stack:** HTML/CSS/JS vanilla (consistência com o projeto das feiras medievais)

---

### Fase 5 — Automação e manutenção

**Objetivo:** Garantir que os dados se mantêm atualizados sem intervenção manual.

Tarefas:
1. Agendamento do scraper via GitHub Actions (cron job). Frequência configurável através de uma variável `SCRAPER_SCHEDULE` no ficheiro de configuração:
   ```
   # Opção A — semanal (domingo às 06:00) — ATIVO por omissão
   SCRAPER_SCHEDULE = "0 6 * * 0"

   # Opção B — diário (06:00) — descomentar para ativar
   # SCRAPER_SCHEDULE = "0 6 * * *"
   ```
   Desta forma basta alterar (e descomentar) uma linha para mudar a frequência, sem tocar na lógica do scraper.
2. Log de execução com resumo: X eventos novos, Y alterados, Z removidos
3. Alerta (ex: email ou ficheiro de erro) se uma fonte deixar de responder ou mudar a estrutura
4. Estratégia de fallback: se o scraper de uma fonte falhar, mantém os dados anteriores dessa fonte (não apaga)
5. Deploy do frontend estático em GitHub Pages (não requer servidor)

---

## Resumo visual das fases

```
Fase 0 ──► Fase 1 ──► Fase 2 ──► Fase 3 ──► Fase 4 ──► Fase 5
Modelo     Scraping   BD         API        Frontend   Auto-
de dados   + limpeza  + import              + UI       mação
```

---

## Decisões tomadas

| # | Questão | Decisão |
|---|---|---|
| 1 | Cobertura Espanha | Península completa (EventoMotor + concentracionesdemotos.com) |
| 2 | Persistência | JSON puro (sem SQLite) |
| 3 | Geocodificação | Automática via Nominatim; resultados incertos marcados com flag para revisão |
| 4 | Frontend | HTML/CSS/JS vanilla (consistência com app das feiras medievais) |
| 5 | Frequência do scraper | Domingos às 06:00 por omissão; variável `SCRAPER_SCHEDULE` permite alterar sem tocar no código |
