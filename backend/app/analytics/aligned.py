"""Aligned-returns + cached Ledoit-Wolf covariance (E1 ingredient).

Centraliza dois ingredientes reusados por Grupos C/E e pelo optimizer:
  * align_return_matrix — inner-join de séries de retorno num frame T×N (NaN-drop),
    apoiado em app.analytics.returns.align_returns para o caso de 2 séries.
  * ledoit_wolf_cov_cached — covariância LW anualizada IDÊNTICA a
    engine.sigma_ledoit_wolf, com cache in-process keyed por {asset_set, window}.

O cache LW é por-processo (functools, não Redis): a covariância é uma função pura
da matriz de retornos, sem I/O nem dado de usuário — então não precisa do Redis
compartilhado (E2 cacheia respostas de endpoint, este cacheia o ingrediente).
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from app.optimizer.engine import sigma_ledoit_wolf

_LW_CACHE_MAX = 256
_lw_cache: OrderedDict[str, np.ndarray] = OrderedDict()


def asset_set_key(labels: Sequence[str], window_days: int | None) -> str:
    """Deterministic order-invariant key for a {asset set, window} pair."""
    canonical = "|".join(sorted(labels)) + f"#w={window_days}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def align_return_matrix(series_by_label: Mapping[str, pd.Series]) -> pd.DataFrame:
    """Inner-join return series on their common dates (NaN rows dropped).

    Columns are ordered by the mapping's key order. Mirrors the dropna semantics
    of app.optimizer.data.load_aligned_returns without the DB I/O.
    """
    frame = pd.DataFrame(dict(series_by_label)).dropna()
    return frame


def ledoit_wolf_cov_cached(
    returns: np.ndarray, *, cache_key: str | None = None
) -> np.ndarray:
    """Annualized (×252) Ledoit-Wolf covariance, identical to
    engine.sigma_ledoit_wolf, with optional in-process caching by cache_key.

    When cache_key is provided and present, the cached array is returned WITHOUT
    recomputation (the caller guarantees the key uniquely identifies the inputs
    via asset_set_key). When cache_key is None, no caching is applied.
    """
    if cache_key is not None and cache_key in _lw_cache:
        _lw_cache.move_to_end(cache_key)
        return _lw_cache[cache_key]
    cov = sigma_ledoit_wolf(returns)
    if cache_key is not None:
        _lw_cache[cache_key] = cov
        _lw_cache.move_to_end(cache_key)
        if len(_lw_cache) > _LW_CACHE_MAX:
            _lw_cache.popitem(last=False)
    return cov


def clear_lw_cache() -> None:
    """Drop all cached LW covariances (used by tests)."""
    _lw_cache.clear()
