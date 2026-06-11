-- F-deploy: fundacao multi-tenant org-scoped (InsForge).
-- organizations + organization_members + helpers de RLS recursion-safe.
-- Decisao do dono (2026-06-11): dados do app publicado sao escopados por
-- ORGANIZACAO (asset management e colaborativo), nao por usuario individual.
-- Sem BEGIN/COMMIT: o backend envolve cada migration na propria transacao.

-- ===========================================================================
-- organizations
-- ===========================================================================
CREATE TABLE public.organizations (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name        TEXT NOT NULL,
  slug        TEXT NOT NULL UNIQUE
              CHECK (slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'),
  created_by  UUID NOT NULL DEFAULT auth.uid() REFERENCES auth.users(id),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ===========================================================================
-- organization_members (role: owner > admin > member)
-- ===========================================================================
CREATE TABLE public.organization_members (
  org_id      UUID NOT NULL REFERENCES public.organizations(id) ON DELETE CASCADE,
  user_id     UUID NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
  role        TEXT NOT NULL DEFAULT 'member'
              CHECK (role IN ('owner', 'admin', 'member')),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (org_id, user_id)
);

CREATE INDEX ix_org_members_user_id ON public.organization_members (user_id);

-- ===========================================================================
-- Helpers de RLS — SECURITY DEFINER (recursion-safe), search_path pinado.
-- Toda policy que consulta organization_members passa por aqui.
-- ===========================================================================
CREATE OR REPLACE FUNCTION public.is_org_member(org UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members m
    WHERE m.org_id = org AND m.user_id = auth.uid()
  );
$$;

CREATE OR REPLACE FUNCTION public.is_org_admin(org UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members m
    WHERE m.org_id = org
      AND m.user_id = auth.uid()
      AND m.role IN ('owner', 'admin')
  );
$$;

CREATE OR REPLACE FUNCTION public.is_org_owner(org UUID)
RETURNS BOOLEAN
LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.organization_members m
    WHERE m.org_id = org AND m.user_id = auth.uid() AND m.role = 'owner'
  );
$$;

-- ===========================================================================
-- Triggers de integridade
-- ===========================================================================

-- Criador vira membro 'owner' automaticamente (bootstrap; SECURITY DEFINER
-- porque roda no INSERT do usuario comum e escreve em organization_members).
CREATE OR REPLACE FUNCTION public.org_bootstrap_owner()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
  INSERT INTO public.organization_members (org_id, user_id, role)
  VALUES (NEW.id, NEW.created_by, 'owner');
  RETURN NEW;
END;
$$;

CREATE TRIGGER organizations_bootstrap_owner
  AFTER INSERT ON public.organizations
  FOR EACH ROW
  EXECUTE FUNCTION public.org_bootstrap_owner();

-- created_by imutavel.
CREATE OR REPLACE FUNCTION public.prevent_org_creator_change()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = pg_catalog, public, pg_temp
AS $$
BEGIN
  IF NEW.created_by IS DISTINCT FROM OLD.created_by THEN
    RAISE EXCEPTION 'organizations.created_by is immutable';
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER organizations_lock_creator
  BEFORE UPDATE ON public.organizations
  FOR EACH ROW
  EXECUTE FUNCTION public.prevent_org_creator_change();

CREATE TRIGGER organizations_updated_at
  BEFORE UPDATE ON public.organizations
  FOR EACH ROW
  EXECUTE FUNCTION system.update_updated_at();

-- Nunca remover/demover o ULTIMO owner de uma org (lockout guard).
CREATE OR REPLACE FUNCTION public.protect_last_org_owner()
RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, public, pg_temp
AS $$
DECLARE
  owners INTEGER;
BEGIN
  IF OLD.role = 'owner'
     AND (TG_OP = 'DELETE' OR NEW.role IS DISTINCT FROM 'owner') THEN
    SELECT count(*) INTO owners
    FROM public.organization_members
    WHERE org_id = OLD.org_id AND role = 'owner';
    IF owners <= 1 THEN
      RAISE EXCEPTION 'cannot remove or demote the last owner of organization %',
        OLD.org_id;
    END IF;
  END IF;
  IF TG_OP = 'DELETE' THEN
    RETURN OLD;
  END IF;
  RETURN NEW;
END;
$$;

CREATE TRIGGER org_members_protect_last_owner
  BEFORE UPDATE OR DELETE ON public.organization_members
  FOR EACH ROW
  EXECUTE FUNCTION public.protect_last_org_owner();

-- ===========================================================================
-- RLS
-- ===========================================================================
ALTER TABLE public.organizations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.organization_members ENABLE ROW LEVEL SECURITY;

-- organizations: membro ve; qualquer autenticado cria (vira owner via
-- trigger); admin edita; owner deleta.
CREATE POLICY "orgs member select" ON public.organizations
  FOR SELECT TO authenticated
  USING (public.is_org_member(id));

CREATE POLICY "orgs authenticated insert" ON public.organizations
  FOR INSERT TO authenticated
  WITH CHECK (created_by = (SELECT auth.uid()));

CREATE POLICY "orgs admin update" ON public.organizations
  FOR UPDATE TO authenticated
  USING (public.is_org_admin(id))
  WITH CHECK (public.is_org_admin(id));

CREATE POLICY "orgs owner delete" ON public.organizations
  FOR DELETE TO authenticated
  USING (public.is_org_owner(id));

-- organization_members: membros veem o quadro da propria org; admin
-- adiciona/edita; admin remove OU o proprio usuario sai (self-leave).
CREATE POLICY "org members select" ON public.organization_members
  FOR SELECT TO authenticated
  USING (public.is_org_member(org_id));

CREATE POLICY "org members admin insert" ON public.organization_members
  FOR INSERT TO authenticated
  WITH CHECK (public.is_org_admin(org_id));

CREATE POLICY "org members admin update" ON public.organization_members
  FOR UPDATE TO authenticated
  USING (public.is_org_admin(org_id))
  WITH CHECK (public.is_org_admin(org_id));

CREATE POLICY "org members admin delete or self leave" ON public.organization_members
  FOR DELETE TO authenticated
  USING (public.is_org_admin(org_id) OR user_id = (SELECT auth.uid()));

-- ===========================================================================
-- Privilegios (policies decidem QUAIS linhas; grants liberam a OPERACAO).
-- anon nao acessa nada da fundacao multi-tenant.
-- ===========================================================================
GRANT USAGE ON SCHEMA public TO authenticated;
REVOKE ALL ON public.organizations FROM anon;
REVOKE ALL ON public.organization_members FROM anon;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organizations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.organization_members TO authenticated;
