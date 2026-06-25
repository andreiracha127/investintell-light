import inspect

from app.services import fund_analysis, series_sql, stock_analysis
from app.services import fund_dossier_tier_b as tb


def test_sql_assemblers_call_series_sql_helpers():
    # The SQL-path assemblers reference the fn_* helpers by name (source check).
    for src_fn, names in [
        (fund_analysis.assemble_fund_analysis_sql,
         ("drawdown_points", "rolling_metrics_points", "histogram_out", "var_cvar")),
        (stock_analysis.assemble_analysis_sql,
         ("rolling_metrics_points", "rolling_beta_corr_points", "histogram_out", "var_cvar")),
        (tb.assemble_entity_analytics_sql,
         ("drawdown_points", "var_cvar")),
    ]:
        src = inspect.getsource(src_fn)
        for n in names:
            assert n in src, (src_fn.__name__, n)


def test_sql_helpers_have_no_pandas_or_numpy():
    src = inspect.getsource(series_sql)
    assert "import pandas" not in src
    assert "import numpy" not in src
    assert ".rolling(" not in src
    assert "np.histogram" not in src
    assert "np.quantile" not in src
