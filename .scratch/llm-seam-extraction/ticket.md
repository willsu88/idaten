# Ticket: extract the LLM provider seam into its own public repo

Filed 2026-07-27. Status: ready. Supersedes the "parked" scope of `agent-eval-library/ticket.md` for the seam half only: the decision (revisited 2026-07-27) is seam-extraction yes, harness-extraction no.

## Scope

Extract from `backend/app/llm/__init__.py` into a new public GitHub repo:

- the `LLMClient` Protocol (`complete`, `stream`, `complete_structured`),
- the `Response` / `ToolCall` types and the OpenAI-shaped neutral wire format,
- both concrete clients (`OpenAIClient`, `AnthropicClient`) with lazy imports,
- `make_client` as the single provider chooser.

Idaten then consumes the library pinned to a SHA.
The eval harness does NOT extract (see agent-eval-library ticket: conventions ship as docs/TESTING.md + a skill; code waits for a second consumer).

## Known obstacles (recorded in ADR 0005)

Both couplings must become injected dependencies before the code moves:

1. Clients read `config.*` directly - becomes constructor args.
2. Clients call `usage.record()`, which writes an app-DB row - becomes an injected callback (idaten passes its recorder; the library defaults to a no-op). The `user_id` + `call_site` binding in `make_client` stays app-side.

## Acceptance

- Full `./start.sh` test gate stays green with idaten consuming the extracted library.
- Library repo has a polished README: design decisions (why a hand-written seam, why OpenAI shapes as neutral format - distilled from ADR 0005), plus the paragraph-level echo of the five-layer testing map linking to idaten's docs/TESTING.md as the worked example.
- README voice matches the redesigned idaten README (see readme-redesign ticket).
