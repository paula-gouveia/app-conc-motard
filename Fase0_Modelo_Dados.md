# Fase 0 — Modelo de Dados

> Documento de referência para a Fase 1 (scraping).  
> Atualizado: 2026-06-11

---

## 1. Mapeamento de campos por fonte

### 1.1 MotardFM — Página principal do calendário

Fonte: `https://motardfm.org/calendario/`  
Formato: texto livre organizado por meses, sem API nem JSON.

| Campo extraído | Exemplo | Notas |
|---|---|---|
| Mês (contexto) | `## JUNHO` | Secção do HTML — define o mês dos eventos que se seguem |
| Data(s) | `10`, `10 a 13`, `10 e 11` | Ver secção de parsing abaixo |
| Nome do evento | `Grupo Motard Srs. da Paciência – Maiorca, Figueira da Foz` | Inclui organizador + local |
| Tipo | `(Aniversário)`, `(Concentração)` | Entre parênteses no final da linha |
| Flag cartaz | `CARTAZ` | Texto no final da linha + link para página de detalhe |
| Flag sem info | `SEM INFO` | Evento sem detalhes adicionais |
| Flag cancelado | `CANCELADO` | Evento cancelado |
| URL detalhe | `https://motardfm.org/concentracoes/...` | Só presente quando há CARTAZ |

**Parsing das datas:**  
O mês é determinado pela secção em que a linha aparece. O dia é extraído da linha com um destes padrões:
- Dia único: `^(\d{1,2}) –`
- Intervalo com "a": `^(\d{1,2}) a (\d{1,2}) –`
- Intervalo com "e": `^(\d{1,2}) e (\d{1,2}) –`
- Intervalo cross-mês: `31 de Julho a 2 de Agosto` (por extenso, casos especiais)

---

### 1.2 MotardFM — Página de detalhe do evento (quando existe)

Fonte: `https://motardfm.org/concentracoes/<slug>/`

| Campo extraído | Exemplo | Notas |
|---|---|---|
| Título completo | `10 a 14 de Junho – São Miguel Moto Fest...` | Incluído no `<title>` e `og:title` |
| Imagem do cartaz | URL da `og:image` | Formato JPEG/PNG |
| Descrição | Free text no `<article>` | Geralmente curto |
| Link de inscrição | URL externo (Google Forms, etc.) | Nem sempre presente |

**Nota importante:** As páginas de detalhe do MotardFM têm estrutura muito variável — algumas têm apenas a imagem do cartaz, outras têm texto descritivo. Não têm campos estruturados para organizador, preço, contacto, GPS. Extrair apenas título, imagem e descrição.

---

### 1.3 FMP — Artigo do calendário

Fonte: `https://www.fmp.pt/noticias/mototurismo/calendario-de-mototurismo-2026/23487/`  
Formato: artigo de texto com listas.

| Campo extraído | Exemplo | Notas |
|---|---|---|
| Data(s) | `12 de abril`, `30 abr. a 3 de maio` | Texto por extenso |
| Organizador/Evento | `28º Dia Nacional do Motociclista – Espinho` | Inclui edição numerada |
| Local | `Espinho`, `Viana do Castelo` | Nem sempre presente explicitamente |
| Categoria FMP | `Eventos FMP`, `Concentrações`, `Troféu Nacional de Moto-Ralis Turísticos` | Determinada pela secção |

**Nota:** A URL do artigo muda a cada ano. Será necessário verificar manualmente a URL do calendário anual.

---

### 1.4 EventoMotor — Página de listagem e detalhe

Fonte listagem: `https://www.eventomotor.com/concentraciones-moteras-2026`  
Fonte detalhe: `https://www.eventomotor.com/evento/<slug>`

| Campo extraído | Exemplo | Notas |
|---|---|---|
| Título | `Artic Quest` | No `<h1>` da página de detalhe |
| Data início | `12 junio de 2026` | Campo "Fecha" na ficha |
| Data fim | `14 junio de 2026` | Implícito no formato "12-14 junio" |
| Localidade | `Canfranc` | Campo "Lugar" |
| Cidade | `Canfranc` | Campo "Ciudad" |
| Província | `Huesca` | Campo "Provincia" |
| Comunidade autónoma | `Aragón` | Campo "Comunidad" |
| Disciplina | `Trail` | Campo "Disciplina" |
| Tipo de veículo | `Moto` | Campo "Tipo de vehículo" |
| Fonte oficial | `Moto-Ocasion` + URL | Campo "Fuente" com link externo |

**Nota:** EventoMotor é a fonte mais estruturada para Espanha. O HTML é limpo e consistente.

---

### 1.5 ConcentracionesDeMotos — Página de detalhe

Fonte: `https://www.concentracionesdemotos.com/<slug>/`

| Campo extraído | Exemplo | Notas |
|---|---|---|
| Título | `23 CONCENTRACIÓN MOTERA LAS ZÁGUILAS` | No `<h1>` |
| Data início | `12/06/2026` | Formato DD/MM/YYYY |
| Data fim | `14/06/2026` | Formato DD/MM/YYYY |
| Localidade | `El Saucejo` | Campo "Lugar del Evento" |
| Província | `Sevilla` | Entre parênteses após localidade |
| Tipo | `Concentración` | Campo "Tipo de Evento" |
| Tipo de motos | `Abierta a todas las motos` | Campo "Tipo de Motos" |
| Organizador | `Las Záguilas` | Campo "Quién Organiza" |
| Preço | `30€ Fin de semana completo / 10€ Domingo` | Campo "Cuánto Cuesta" |
| Telefone | `637208925` | Campo de contacto |
| Email | `alexrosado816@gmail.com` | Campo de contacto |
| Descrição | Free text | Secção "Programa" |
| Ponto de encontro | `Zona recreativa Vado Yeso (Sevilla)` | Campo "Cómo llegar" |
| Google Maps URL | `https://maps.app.goo.gl/...` | Link "Ver ubicación exacta" |
| Imagem cartaz | URL da `og:image` | JPEG |

**Nota:** Esta fonte tem os campos mais ricos por evento, incluindo preço e contactos. No entanto tem menos eventos que o EventoMotor.

---

## 2. Modelo de dados unificado

Schema de um objeto de evento no `data/concentracoes.json`:

```json
{
  "id": "a3f8bc12e7d4",
  "nome": "28º Aniversário Grupo Motard Srs. da Paciência",
  "data_inicio": "2026-06-10",
  "data_fim": "2026-06-10",
  "pais": "PT",
  "localidade": "Maiorca",
  "distrito_provincia": "Coimbra",
  "regiao": "Centro",
  "latitude": 40.0921,
  "longitude": -8.6543,
  "geocoding_uncertain": false,
  "tipo_evento": "aniversario",
  "tier": 2,
  "organizador": "Grupo Motard Srs. da Paciência",
  "tem_cartaz": true,
  "url_cartaz": "https://motardfm.org/wp-content/uploads/.../cartaz.jpg",
  "url_evento": "https://motardfm.org/concentracoes/...",
  "url_fonte_oficial": null,
  "fonte": "motardfm",
  "cancelado": false,
  "sem_info": false,
  "descricao": null,
  "preco": null,
  "contacto_telefone": null,
  "contacto_email": null,
  "url_maps": null,
  "atualizado_em": "2026-06-11T06:00:00"
}
```

### Definição de campos

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `id` | string | ✅ | Hash SHA-256 (12 chars) de `pais+fonte+nome_normalizado+data_inicio` |
| `nome` | string | ✅ | Nome do evento, limpo (sem datas, sem "CARTAZ") |
| `data_inicio` | string (ISO date) | ✅ | Formato `YYYY-MM-DD` |
| `data_fim` | string (ISO date) | — | Igual a `data_inicio` se evento de 1 dia |
| `pais` | string | ✅ | `"PT"` ou `"ES"` |
| `localidade` | string | — | Cidade/vila do evento |
| `distrito_provincia` | string | — | Distrito (PT) ou Província (ES) |
| `regiao` | string | — | Região NUT II (PT) ou Comunidade Autónoma (ES) |
| `latitude` | float | — | Coordenada decimal |
| `longitude` | float | — | Coordenada decimal |
| `geocoding_uncertain` | boolean | ✅ | `true` se a geocodificação pode estar errada |
| `tipo_evento` | string | ✅ | Ver taxonomia (secção 3) |
| `tier` | integer | ✅ | `1` = evento oficial FMP, `2` = evento regular |
| `organizador` | string | — | Nome do clube/grupo organizador |
| `tem_cartaz` | boolean | ✅ | `true` se existe imagem do cartaz |
| `url_cartaz` | string | — | URL da imagem do cartaz |
| `url_evento` | string | — | URL da página do evento na fonte |
| `url_fonte_oficial` | string | — | URL oficial do organizador (quando disponível via EventoMotor) |
| `fonte` | string | ✅ | `"motardfm"`, `"fmp"`, `"eventomotor"`, `"concentracionesdemotos"` |
| `cancelado` | boolean | ✅ | `true` se marcado como cancelado |
| `sem_info` | boolean | ✅ | `true` se fonte marcou como "SEM INFO" (PT) |
| `descricao` | string | — | Texto descritivo (quando disponível) |
| `preco` | string | — | Preço de entrada (ES, texto livre: "30€ / 10€ domingo") |
| `contacto_telefone` | string | — | Número de telefone |
| `contacto_email` | string | — | Email de contacto |
| `url_maps` | string | — | Link Google Maps ou coordenadas |
| `atualizado_em` | string (ISO datetime) | ✅ | Timestamp da última atualização pelo scraper |

### Geração do ID

```python
import hashlib

def gerar_id(pais, fonte, nome, data_inicio):
    nome_norm = nome.lower().strip()
    chave = f"{pais}|{fonte}|{nome_norm}|{data_inicio}"
    return hashlib.sha256(chave.encode()).hexdigest()[:12]
```

O ID é **estável entre execuções** desde que o nome e a data não mudem. Se o MotardFM corrigir uma data ou alterar o nome do evento, o ID muda — o scraper trata isso como remoção + adição nova.

---

## 3. Taxonomia de tipos de evento

Valores possíveis para o campo `tipo_evento`:

| Valor (tipo_evento) | Descrição | Exemplos nas fontes |
|---|---|---|
| `concentracao` | Concentração motard principal | "(Concentração)", "Concentración" |
| `aniversario` | Aniversário de clube/grupo | "(Aniversário)" |
| `motochurrasco` | Evento gastronómico motard | "(Motochurrasco)", "(Churrascada)", "(Feijoada motard)" |
| `convivio` | Convívio, encontro, sardinhada | "(Convívio)", "(Encontro motard)", "(Sardinhada)" |
| `moto_rali` | Moto-rali turístico | "(Moto-Rali)", "Ruta motera" |
| `moto_rali_trofeu` | Troféu Nacional FMP | Troféu Nacional de Moto-Ralis Turísticos |
| `evento_fmp` | Evento oficial FMP | Portugal Lés-a-Lés, Dia Nacional do Motociclista |
| `passeio` | Passeio de motos | "(Passeio)", "(Passeio de motos)", "Rutas moteras" |
| `bencao` | Bênção das motas/capacetes | "(Benção das Motas)", "(Benção dos Capacetes)" |
| `matinal` | Pequeno-almoço, matabicho, motoalmuerzo | "(Pequeno almoço)", "(Matabicho Oeste)", "Motoalmuerzo" |
| `arraial` | Arraial motard | "(Arraial)" |
| `magusto` | Magusto / motomagusto | "(Magusto)", "(Motomagusto)" |
| `halloween` | Evento de Halloween | "(Halloween)" |
| `natal` | Evento de Natal / Pais Natais | "(Pais Natais)", "(Natal solidário)" |
| `solidario` | Evento solidário | "(Festa solidária)", "Bikers Solidarios" |
| `desfile` | Desfile de motos | "(Desfile)", "(Desfile Pais Natais)" |
| `trail` | Evento de trail / off-road | "Trail", "Offroad", "(Off-Road)" |
| `custom` | Evento custom / Harley | "Custom y Harley", "Custom" |
| `classicas` | Encontro de motas clássicas | "Clásicas", "(Motas antigas)", "(Clássicas)" |
| `festival` | Festival motard | "Festival motero", "(Moto Fest)" |
| `run` | Run noturno ou temático | "(Run nocturno)" |
| `outro` | Não classificável | Fallback para tipos não reconhecidos |

### Mapeamento automático de tipos

O scraper usará um dicionário de mapeamento para converter o texto original para o `tipo_evento` normalizado. Exemplos:

```python
MAPA_TIPOS_PT = {
    "concentração": "concentracao",
    "concentracao": "concentracao",
    "aniversário": "aniversario",
    "aniversario": "aniversario",
    "motochurrasco": "motochurrasco",
    "churrascada": "motochurrasco",
    "feijoada": "motochurrasco",
    "convívio": "convivio",
    "convivio": "convivio",
    "encontro motard": "convivio",
    "sardinhada": "convivio",
    "moto-rali": "moto_rali",
    "moto rali": "moto_rali",
    "passeio": "passeio",
    "benção": "bencao",
    "bencao": "bencao",
    "pequeno almoço": "matinal",
    "matabicho": "matinal",
    "arraial": "arraial",
    "magusto": "magusto",
    "motomagusto": "magusto",
    "halloween": "halloween",
    "pais natais": "natal",
    "natal solidário": "natal",
    "solidária": "solidario",
    "desfile": "desfile",
    "run nocturno": "run",
    "motas antigas": "classicas",
    "clássicas": "classicas",
    "moto fest": "festival",
    "off-road": "trail",
}

MAPA_TIPOS_ES = {
    "concentración": "concentracao",
    "concentracion": "concentracao",
    "trail": "trail",
    "custom y harley": "custom",
    "custom": "custom",
    "rutas moteras": "passeio",
    "rutas": "passeio",
    "festival motero": "festival",
    "motoalmuerzo": "matinal",
    "matinal": "matinal",
    "clásicas": "classicas",
    "clasicas": "classicas",
    "offroad": "trail",
    "cross y montaña": "trail",
    "scooter": "outro",
}
```

---

## 4. Estratégia de deduplicação

### Cenários de duplicados

**Dentro de Portugal:** Os eventos do FMP também aparecem no MotardFM (que é mais completo). Não fazemos merge — usamos `fmp` como fonte secundária e definimos `tier: 1` apenas nos eventos FMP. O scraper FMP só adiciona um evento se não existir já no JSON (verificado por nome + data).

**Dentro de Espanha:** EventoMotor e ConcentracionesDeMotos podem ter o mesmo evento. EventoMotor é prioritário. O scraper ConcentracionesDeMotos enriquece eventos já existentes (adiciona preço, contactos) em vez de criar duplicados.

**Entre Portugal e Espanha:** Muito raro, mas possível para eventos perto da fronteira. Não existe deduplicação cross-country — os IDs incluem o `pais` como componente, pelo que nunca colidem.

### Algoritmo de merge (EventoMotor ↔ ConcentracionesDeMotos)

```
Para cada evento de ConcentracionesDeMotos:
  1. Normalizar nome e data_inicio
  2. Procurar no JSON existente: mesmo pais="ES" + data_inicio igual + similaridade(nome) > 0.80
  3. Se encontrado:
       → Enriquecer com campos extras (preco, contacto, url_maps) se estiverem vazios
       → Não criar nova entrada
  4. Se não encontrado:
       → Adicionar como nova entrada com fonte="concentracionesdemotos"
```

A similaridade do nome usa a distância de Levenshtein normalizada (biblioteca `difflib` do Python — sem dependências externas).

### Campos que nunca se sobrescrevem numa atualização

Para preservar correções manuais feitas diretamente no JSON:
- `latitude`, `longitude` — se `geocoding_uncertain: false`
- `url_maps` — se preenchido manualmente
- `descricao` — se mais longo que o que o scraper traria

---

## 5. Notas de parsing para a Fase 1

### MotardFM — casos especiais nas datas

O calendário do MotardFM tem alguns padrões fora do normal que o regex precisa de tratar:

```
# Intervalo cross-mês (por extenso)
"31 de Julho e 1 de Agosto"
"31 de Julho a 2 de Agosto"
"25 a 28 – Moto Clube do Barreiro"  ← dias sem mês explícito = mês da secção

# Datas compostas
"31 de Julho e 1 de Agosto – Motoclube de Nine"
```

Abordagem: processar o texto mês a mês. Dentro de cada secção de mês, assumir que o mês é o da secção, exceto quando há referência explícita a outro mês ("de Julho", "de Agosto", etc.).

### MotardFM — extração do organizador vs. nome do evento

O MotardFM não separa explicitamente o nome do organizador do nome do evento. A maioria das linhas segue o padrão:

```
[Nome do clube/grupo] – [Local] ([Tipo])
```

Mas há variações:
```
"Portugal de Lés-a-Lés"                         ← só evento, sem local na linha
"São Miguel Moto Fest – S. Miguel, Açores"       ← evento + local
"Grupo Motard Lobo & Companhia – Pedroso, V.N. Gaia"  ← grupo + local
```

O campo `organizador` será extraído como tudo antes do ` – ` (se existir). O campo `nome` será a linha completa limpa (sem datas, sem "CARTAZ", sem tipo entre parênteses).

### EventoMotor — scraping da listagem vs. detalhe

A página de listagem do EventoMotor tem todos os eventos com data, título, localidade e tipo — suficiente para o JSON base. As páginas de detalhe acrescentam província, comunidade autónoma e fonte oficial. 

Estratégia: fazer scraping da listagem para obter todos os eventos, depois visitar as páginas de detalhe para eventos novos ou sem `distrito_provincia` preenchido. Evita fazer centenas de pedidos HTTP desnecessários a cada execução.

---

## 6. Estrutura do ficheiro JSON final

```json
{
  "meta": {
    "versao": "1.0",
    "gerado_em": "2026-06-15T06:00:00",
    "total_eventos": 312,
    "por_pais": { "PT": 241, "ES": 71 },
    "fontes": ["motardfm", "fmp", "eventomotor", "concentracionesdemotos"]
  },
  "eventos": [
    { ... },
    { ... }
  ]
}
```

O array `eventos` é ordenado por `data_inicio` ascendente.
