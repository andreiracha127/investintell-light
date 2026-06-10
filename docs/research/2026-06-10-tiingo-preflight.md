# Preflight Tiingo API — Relatório (F0, 2026-06-10)

**Contexto:** verificação pré-flight (§6 do dispatch de bootstrap) executada na F0, antes de qualquer código de data layer (F1). Páginas do tiingo.com são SPA; conteúdo extraído das páginas oficiais renderizadas. Cada afirmação cita a URL-fonte. Itens sem número oficial estão marcados como **não documentado publicamente**.

---

## A. Limites do plano pago individual

### A1. Nome oficial e preço
- O plano pago individual atual chama-se **"Power"** — **US$ 30/mês ou US$ 300/ano**. O plano gratuito chama-se **"Starter"**. **Não existe plano individual chamado "Pro".**
- Para empresas/organizações existe o plano **"Commercial"** — **US$ 50/mês ou US$ 499/ano**.
- Fontes: https://www.tiingo.com/pricing ; https://www.tiingo.com/about/pricing

### A2. Requests por hora e por dia
| Limite | Starter (free) | Power ($30) | Commercial ($50) |
|---|---|---|---|
| Max Requests Per Hour | 50 | **10.000** | 20.000 |
| Max Requests Per Day | 1.000 | **100.000** | 150.000 |

- Reset: horário a cada hora; diário à meia-noite EST; bandwidth no dia 1º de cada mês à meia-noite EST. **Não há rate limit por minuto/segundo** ("We do not rate limit to minute or second").
- Fontes: https://www.tiingo.com/pricing ; https://www.tiingo.com/documentation/general/overview (§1.1.3) ; https://www.tiingo.com/products/iex-api

### A3. Símbolos únicos por mês
- **Starter: 500 / Power: 108.111** (no Power equivale ao universo inteiro — na prática, sem limite).
- O limite aparece sob o bloco "Tiingo API" na pricing page (EOD, Crypto, IEX Feed e News juntos); **a alocação exata por endpoint não é documentada publicamente**. Evidência empírica de estouro: mensagem "You have run over your 500 symbol look up for this month" (https://github.com/hydrosquall/tiingo-python/issues/45).
- Fonte: https://www.tiingo.com/pricing

### A4. Bandwidth mensal
- Starter: **1 GB/mês** · Power: **40 GB/mês** · Commercial: **100 GB/mês**. Reset dia 1º, meia-noite EST.
- Fontes: https://www.tiingo.com/pricing ; https://www.tiingo.com/documentation/general/overview

### A5. Websocket IEX
- **Endpoint:** `wss://api.tiingo.com/iex`. O firehose (Crypto & IEX) vem em todos os planos.
- **Conexões simultâneas:** **não documentado publicamente.**
- **Símbolos por subscrição:** via `eventData.tickers: ['spy','uso']` (específicos) ou `['*']` (firehose). **Nenhum limite numérico documentado.** Add/remove dinâmico via `subscriptionId` retornado na primeira mensagem (`messageType: "I"`).
- **thresholdLevel:**
  - `0` — todos os updates Top-of-Book E Last Trade ("A LOT of data");
  - `5` — todos os trades + quotes "major";
  - `6` — **Tiingo Reference Price** (derivado pela Tiingo; mensagens só quando o reference price muda).
  - **Mudança de 01/02/2025:** thresholdLevel 0 e 5 (TOPS completo) **exigem market data agreement assinado com a IEX Exchange**. Sem o acordo, usar `thresholdLevel: 6` (sem custo adicional, "compliant-friendly").
- Fonte: https://www.tiingo.com/documentation/websockets/iex

### A6. News API
- **Incluída no Power** (✗ no Starter). A exigência histórica de licença à parte não aparece mais. Restrição vigente: **3 meses de histórico consultável** + todos os dados dali em diante (histórico maior = contato comercial). Bulk download só para institucionais.
- Fontes: https://www.tiingo.com/pricing ; https://www.tiingo.com/documentation/news

## B. ToS / Licença — ⚠️ ACHADOS CRÍTICOS

### B1. Uso comercial / equipe interna no plano individual
- **NÃO coberto pelo Power.** Licença do Power é "Internal Use Only", definida como: *"you may only use the data for your own personal use and you may not display or share the data with another person or organization."* Documentação §1.1.6: *"For Basic and Power accounts, data is for internal and personal use only."*
- **Equipe interna → plano Commercial (US$ 50/mês, até 2 desenvolvedores).**
- Fontes: https://www.tiingo.com/pricing (tooltip + nota ***) ; https://www.tiingo.com/documentation/general/overview (§1.1.6) ; https://app.tiingo.com/tos/ (cláusula 1.4)

### B2. Redistribuição a terceiros
- **Proibida em todos os planos self-service** (Starter, Power E Commercial): "You may not redistribute the data in any form."
- Licença específica: **"EOD + IEX Redistribution"** (Display Redistribution) — **US$ 250/mês (startups <5 pessoas) / US$ 500/mês (≥5)**, com 80.000 req/h, 1.200.000 req/dia, 1 TB/mês. Contratação via sales@tiingo.com.
- Exceção (Developer Program): software em que **cada usuário final fornece o próprio token Tiingo** não precisa de licença de redistribuição (§1.1.6).
- Fontes: https://www.tiingo.com/products/iex-api ; https://www.tiingo.com/documentation/general/overview (§1.1.6)

## C. Contratos técnicos (resumo para o data layer)

### C1. End-of-Day
- Histórico: `GET https://api.tiingo.com/tiingo/daily/<ticker>/prices?startDate=YYYY-MM-DD&endDate=YYYY-MM-DD&resampleFreq=daily&format=json`
- Parâmetros: `startDate`/`endDate` (inclusivos), `resampleFreq` (`daily|weekly|monthly|annually`), `sort` (`-date`), `format` (`json|csv` — CSV 4-5× mais rápido), `columns`.
- Campos: `date, open, high, low, close, volume, adjOpen, adjHigh, adjLow, adjClose, adjVolume, divCash, splitFactor` (ajuste CRSP). Preços US ~17h30 EST; correções até 20h EST.
- Fonte: https://www.tiingo.com/documentation/end-of-day

### C2. IEX websocket
- URL: `wss://api.tiingo.com/iex`. Subscribe: `{"eventName":"subscribe","authorization":"<TOKEN>","eventData":{"thresholdLevel":6,"tickers":["spy","uso"]}}`.
- Dados: `messageType:"A"`, `data` = array posicional. Com threshold 6: `[datetime ISO, ticker, referencePrice]`. Com 0/5 (exige acordo IEX): 16 posições (tipo T/Q/B, datetime, epoch ns, ticker, bidSize, bidPrice, mid, askPrice, askSize, lastPrice, lastSize, halted, afterHours, ISO order, oddlot, NMS 611).
- Heartbeats `messageType:"H"` a cada **30 s**. messageTypes: A/U/D/I/E/H.
- Fontes: https://www.tiingo.com/documentation/websockets/iex ; https://www.tiingo.com/documentation/general/connecting

### C3. Metadados de ticker
- `GET https://api.tiingo.com/tiingo/daily/<ticker>` → `ticker, name, exchangeCode, description, startDate, endDate`.

### C4. Lista de tickers suportados
- `https://apimedia.tiingo.com/docs/tiingo/daily/supported_tickers.zip` (atualizado diariamente).
- Busca (beta, não recomendado para produção): `GET /tiingo/utilities/search?query=`.
- Simbologia: classes com hífen (`BRK-A`).

### C5. Autenticação
- Query `?token=` ou header `Authorization: Token <TOKEN>`. Websocket: campo `authorization` no JSON. Teste: `GET https://api.tiingo.com/api/test/`.

### C6. Rate limit — códigos de erro
- **Não documentado publicamente** (sem menção a 429/`X-RateLimit-*`/`Retry-After`). Evidência histórica: estouro retornou **HTTP 200 com corpo texto puro** ("You have run over your...") — quebra parsers JSON. Tratar 429 E respostas 200 não-JSON como rate-limit, com backoff.

## Recomendações de parametrização (premissa: plano Power)

1. **Token bucket REST:** refill **2,0 req/s** (≈7.200/h, 72% do teto) com burst **10**; guard-rails: hard-stop deslizante em 9.000/h e 90.000/dia (reset 0h EST); circuit breaker para HTTP 429 **e** resposta 200 não-JSON; contabilidade local de requests e bytes (bandwidth 40 GB/mês é a dimensão menos visível).
2. **Websocket:** 1 conexão com subscrição explícita de ~600 tickers (sem `['*']`); **thresholdLevel 6** salvo acordo IEX assinado; watchdog de heartbeat (reconectar se >90 s sem `H`); add/remove via `subscriptionId`.
3. **Universo F6 (~600 tickers S&P500+Nasdaq100 × 2 anos EOD):** ~600–1.200 requests no backfill (1/ticker, range completo em 1 request) → **~5–10 min a 2 req/s**; ~60–150 MB; atualização diária incremental = 600 req/dia (0,6% do limite). Cabe com folga no Power. (Não caberia no Starter: limite de 500 símbolos/mês.)
