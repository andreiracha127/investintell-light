---
date: 2026-06-12
topic: semantic-index-lmstudio
---

# Indexador semântico local (LM Studio + pgvector)

## What We're Building

Um **indexador semântico local**, complementar ao Serena (que permanece o indexador
**simbólico**). O Serena responde "onde está o símbolo `X`"; este novo responde
"onde tratamos o conceito Y" — recuperação por **significado**, atravessando
Python/TS e **múltiplos repositórios**.

Necessidades a atender:
1. Achar por **intenção/conceito** sem saber o nome do símbolo.
2. **Brief de arquitetura** enxuto entregue na abertura da sessão.
3. Recuperação **cross-linguagem** (rota Python ↔ chart TS) por significado.
4. **Memória de localização cross-repo** — lembrar que os workers do datalake moram em
   `E:\investintell-datalake-workers` (Railway), não em `investintell-light`.

## Why This Approach

Indexador semântico clássico = **busca vetorial por embeddings**. O LM Studio já serve
modelos de embedding pela API OpenAI-compatível (`/v1/embeddings`), permitindo 100% local
sem custo de API. A sinergia que evita o "chunking burro" (janelas de N linhas que cortam
funções no meio): **usar o Serena para fatiar por símbolo** — cada função/classe vira um
chunk semanticamente coerente, com metadados ricos. Simbólico e semântico se reforçam.

O MCP server é **nosso** (Python); o LM Studio entra apenas como motor de embeddings via
HTTP local. pgvector reaproveita o Postgres `:5436` já em uso, em **schema isolado** para
não poluir as tabelas do app.

## Key Decisions

- **Motor**: embeddings via LM Studio, modelo **Qwen3-Embedding-8B**.
- **Dimensão**: **truncar para 1024 via MRL (Matryoshka) + re-normalizar L2**. Motivo:
  o 8B emite 4096 dims, mas o pgvector só indexa (HNSW/IVFFlat) até 2000 no tipo `vector`
  (4000 no `halfvec`). 1024 é indexável, leve e mantém qualidade. Trocar = reindex full.
- **Chunking**: por símbolo, via `get_symbols_overview`/`find_symbol` do Serena.
- **Vector store**: pgvector no Postgres local `:5436`, **schema `code_index`** isolado.
  - `chunks(id, repo, file_path, symbol_path, kind, language, start_line, end_line,
    content, embedding vector(1024), file_hash, updated_at)`
  - `files(repo, file_path, file_hash, mtime, indexed_at)` → driva o incremental.
  - Índice **HNSW** em `embedding` (cosine).
- **Atualização**: incremental por hash/mtime — reembeda só arquivos alterados. Comando
  manual `/reindex` + checagem leve no SessionStart (índice obsoleto? quantos chunks?).
- **Cobertura cross-repo**: indexar `investintell-light` E
  `investintell-datalake-workers` ao mesmo tempo; cada chunk taggeado com `repo`.
- **Entrega dupla**:
  - Tool MCP `semantic_search(query, k, repo?)` → top-k chunks + caminhos, sob demanda.
  - Tool/`repo_digest()` → brief enxuto (subsistemas + fato "workers em outro dir").
  - Hook `SessionStart` injeta o digest enxuto (curto) e aponta a tool.
- **Digest**: gerado uma vez (LLM) e **cacheado**, com a localização cross-repo dos
  workers como constante curada — barato no SessionStart.

## Open Questions

- **pgvector instalado no `:5436`?** Precisa `CREATE EXTENSION vector`. Verificar no plano.
- **Dimensão final**: 1024 é o default recomendado; confirmar se 1536/2000 vale o custo.
- **Estratégia de chunk para arquivos sem símbolos** (configs, markdown, SQL): fallback
  para chunk por arquivo ou janela? Decidir no plano.
- **Granularidade do digest**: por subsistema (backend/frontend/workers) — definir formato.

## Next Steps

→ `/ce:plan` para detalhar implementação (MCP server, schema/migration, pipeline de
indexação, hook SessionStart, integração com Serena).
