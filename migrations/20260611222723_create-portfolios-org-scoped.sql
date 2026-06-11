-- F-deploy: portfolios + positions ORG-SCOPED (substitui o rascunho
-- per-user de 2026-06-11, nunca aplicado). Espelha o schema single-tenant
-- do backend Python (app/models/portfolio.py) com upgrades p/ publicacao:
--   1. PK UUID                  — IDs nao-enumeraveis entre tenants
--   2. UNIQUE(org_id, name)     — nome unico por organizacao
--   3. NUMERIC p/ dinheiro      — sem drift de ponto flutuante
--   4. org_id denormalizado em positions (performance de RLS), DERIVADO
--      do portfolio pai por trigger — impossivel anexar posicao a
--      portfolio de outra org.
-- Sem BEGIN/COMMIT: o backend envolve cada migration na propria transacao.

-- ===========================================================================
-- portfolios
-- ===========================================================================
CREATE TABLE public.portfolios (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  org_id      UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  created_by  UUID NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
  name        TEXT NOT NULL,
  cash        NUMERIC NOT NULL DEFAULT 0,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_portfolios_org_id_name UNIQUE (org_id, name)
);

CREATE INDEX ix_portfolios_org_id ON public.portfolios (org_id);

-- ===========================================================================
-- positions
-- ===========================================================================
CREATE TABLE public.positions (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  portfolio_id  UUID NOT NULL REFERENCES public.portfolios(id) ON DELETE CASCADE,
  org_id        UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  ticker        TEXT NOT NULL,
  quantity      NUMERIC NOT NULL CHECK (quantity > 0),
  acq_price     NUMERIC CHECK (acq_price IS NULL OR acq_price > 0),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_positions_portfolio_id_ticker UNIQUE (portfolio_id, ticker)
);

CREATE INDEX ix_positions_portfolio_id ON public.positions (portfolio_id);
CREATE INDEX ix_positions_org_id ON public.positions (org_id);

-- ===========================================================================
-- Triggers de integridade
-- ===========================================================================

-- positions.org_id e DERIVADO do portfolio pai (nunca confiar no cliente).
CREATE OR REPLACE FUNCTION public.set_position_org()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  parent_org UUID;
BEGIN
  SELECT org_id INTO parent_org FROM public.portfolios WHERE id = NEW.portfolio_id;
  IF parent_org IS NULL THEN
    RAISE EXCEPTION 'portfolio % not found', NEW.portfolio_id;
  END IF;
  NEW.org_id := parent_org;
  RETURN NEW;
END;
$$;

CREATE TRIGGER positions_set_org
  BEFORE INSERT OR UPDATE ON public.positions
  FOR EACH ROW
  EXECUTE FUNCTION public.set_position_org();

-- portfolios.org_id e created_by imutaveis (tenant/identidade protegidos).
CREATE OR REPLACE FUNCTION public.prevent_portfolio_tenant_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
  IF NEW.org_id IS DISTINCT FROM OLD.org_id THEN
    RAISE EXCEPTION 'portfolios.org_id is immutable';
  END IF;
  IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
    RAISE EXCEPTION 'portfolios.created_by is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER portfolios_lock_tenant
  BEFORE UPDATE ON public.portfolios
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_portfolio_tenant_change();

CREATE TRIGGER portfolios_updated_at
  BEFORE UPDATE ON public.portfolios
  FOR EACH ROW
  EXECUTE FUNCTION system.update_updated_at();

CREATE TRIGGER positions_updated_at
  BEFORE UPDATE ON public.positions
  FOR EACH ROW
  EXECUTE FUNCTION system.update_updated_at();

-- ===========================================================================
-- RLS — membro da org le/escreve; delete de portfolio exige admin OU autor.
-- Helpers SECURITY DEFINER vem da migration anterior (is_org_member/admin).
-- ===========================================================================
ALTER TABLE public.portfolios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.positions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "portfolios org select" ON public.portfolios
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

CREATE POLICY "portfolios org insert" ON public.portfolios
  FOR INSERT TO authenticated
  WITH CHECK (
    public.is_org_member(org_id)
    AND created_by = (SELECT auth.uid())
  );

CREATE POLICY "portfolios org update" ON public.portfolios
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

CREATE POLICY "portfolios admin or author delete" ON public.portfolios
  FOR DELETE TO authenticated
  USING (
    public.is_org_admin(org_id)
    OR created_by = (SELECT auth.uid())
  );

CREATE POLICY "positions org select" ON public.positions
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

CREATE POLICY "positions org insert" ON public.positions
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_member(org_id));

CREATE POLICY "positions org update" ON public.positions
  FOR UPDATE TO authenticated
  USING (public.is_org_member(org_id))
  WITH CHECK (public.is_org_member(org_id));

CREATE POLICY "positions org delete" ON public.positions
  FOR DELETE TO authenticated
  USING (public.is_org_member(org_id));

-- ===========================================================================
-- Privilegios
-- ===========================================================================
REVOKE ALL ON public.portfolios FROM anon;
REVOKE ALL ON public.positions  FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.portfolios TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.positions  TO authenticated;
