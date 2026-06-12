-- F8.6b paridade: o schema publicado espelha a migration local 0007.
-- positions: basis (reference|executed) + commission + trade_date;
-- portfolios: origin (manual|builder). Mesma semantica do backend Python:
-- preco de referencia (spot/NAV) dimensiona a proposta; fills executados
-- com comissao definem o cost basis real.
-- Sem BEGIN/COMMIT: o backend envolve cada migration na propria transacao.

ALTER TABLE public.positions
  ADD COLUMN basis TEXT NOT NULL DEFAULT 'reference'
    CHECK (basis IN ('reference', 'executed')),
  ADD COLUMN commission NUMERIC
    CHECK (commission IS NULL OR commission >= 0),
  ADD COLUMN trade_date DATE;

ALTER TABLE public.portfolios
  ADD COLUMN origin TEXT NOT NULL DEFAULT 'manual'
    CHECK (origin IN ('manual', 'builder'));
