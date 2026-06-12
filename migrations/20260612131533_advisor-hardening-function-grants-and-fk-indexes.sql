-- Hardening apontado pelo InsForge Backend Advisor (2026-06-12).
--
-- Issues 1-6 (security/dangerous-function): as funcoes JA sao SECURITY
-- DEFINER de proposito (helpers recursion-safe de RLS + triggers que
-- escrevem em organization_members) e JA pinam search_path em
-- "pg_catalog, public, pg_temp". O problema real era o ACL default
-- (proacl = NULL), que da EXECUTE implicito a PUBLIC. Aqui o EXECUTE e
-- restringido ao minimo:
--   - helpers is_org_*  -> so authenticated (policies rodam como o caller)
--   - funcoes de trigger -> ninguem (EXECUTE de trigger function so e
--     checado no CREATE TRIGGER, pelo dono; nao no disparo)
-- NAO converter para SECURITY INVOKER: reintroduziria recursao de RLS
-- (policy de organization_members chama helper que le a propria tabela).
--
-- Issues 7-9 (performance): indices ausentes em FKs/coluna de policy.
-- Sem BEGIN/COMMIT: o backend envolve cada migration na propria transacao.

-- ===========================================================================
-- Helpers de RLS: EXECUTE apenas para authenticated
-- ===========================================================================
REVOKE EXECUTE ON FUNCTION public.is_org_member(uuid) FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.is_org_admin(uuid)  FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.is_org_owner(uuid)  FROM PUBLIC, anon;

GRANT EXECUTE ON FUNCTION public.is_org_member(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_org_admin(uuid)  TO authenticated;
GRANT EXECUTE ON FUNCTION public.is_org_owner(uuid)  TO authenticated;

-- ===========================================================================
-- Funcoes de trigger: nenhum role de runtime precisa de EXECUTE
-- ===========================================================================
REVOKE EXECUTE ON FUNCTION public.org_bootstrap_owner()
  FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.protect_last_org_owner()
  FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.set_position_org()
  FROM PUBLIC, anon, authenticated;
-- Nao flagadas (SECURITY INVOKER), mas mesma higiene:
REVOKE EXECUTE ON FUNCTION public.prevent_org_creator_change()
  FROM PUBLIC, anon, authenticated;
REVOKE EXECUTE ON FUNCTION public.prevent_portfolio_tenant_change()
  FROM PUBLIC, anon, authenticated;

-- ===========================================================================
-- Indices em FKs / coluna de policy (issues 7-9).
-- CREATE INDEX simples (nao CONCURRENTLY): migration roda em transacao e
-- as tabelas ainda sao pequenas.
-- ===========================================================================
CREATE INDEX IF NOT EXISTS ix_organizations_created_by
  ON public.organizations (created_by);
CREATE INDEX IF NOT EXISTS ix_portfolios_created_by
  ON public.portfolios (created_by);
