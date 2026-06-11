"""F2 phase gate: statistics verified against hand-computed values.

The expected literals below were derived by hand (full arithmetic shown in
comments), NOT by calling numpy/pandas in the test. This guards against the
implementation and the test sharing a common bug.
"""

import pandas as pd

from app.analytics import annualized_volatility, historical_var


def _dated(values: list[float]) -> pd.Series:
    return pd.Series(values, index=pd.date_range("2024-01-01", periods=len(values), freq="B"))


def test_annualized_volatility_hand_computed() -> None:
    # Input returns: [0.01, -0.02, 0.015, -0.005, 0.02]
    #
    # mean = (0.01 - 0.02 + 0.015 - 0.005 + 0.02) / 5 = 0.02 / 5 = 0.004
    #
    # deviations from mean:
    #   0.01  - 0.004 =  0.006
    #  -0.02  - 0.004 = -0.024
    #   0.015 - 0.004 =  0.011
    #  -0.005 - 0.004 = -0.009
    #   0.02  - 0.004 =  0.016
    #
    # squared deviations:
    #   0.006^2  = 0.000036
    #   0.024^2  = 0.000576
    #   0.011^2  = 0.000121
    #   0.009^2  = 0.000081
    #   0.016^2  = 0.000256
    #   sum      = 0.001070
    #
    # sample variance (ddof=1) = 0.001070 / 4 = 0.0002675
    # annualized variance      = 0.0002675 * 252 = 0.06741
    # annualized volatility    = sqrt(0.06741)
    #
    # sqrt(0.06741) by hand (Newton refinement):
    #   0.25963^2 = 0.0674077369            (25963^2 = 674,077,369)
    #   residual  = 0.06741 - 0.0674077369 = 0.0000022631
    #   delta     = 0.0000022631 / (2 * 0.25963) = 0.0000043583
    #   sqrt      = 0.25963 + 0.0000043583 = 0.2596343583
    # (next-order correction is ~4e-11, far below the 1e-9 tolerance)
    returns = _dated([0.01, -0.02, 0.015, -0.005, 0.02])
    result = annualized_volatility(returns, periods_per_year=252)
    assert abs(result - 0.2596343583) < 1e-9


def test_historical_var_95_hand_computed() -> None:
    # 20 ascending returns:
    #   x0..x5  : -0.05, -0.04, -0.03, -0.02, -0.01, 0.0
    #   x6..x19 : 0.001, 0.002, 0.003, ..., 0.014  (14 values, step 0.001)
    #
    # historical_var(returns, 0.95) = -quantile(returns, 0.05) with numpy's
    # default linear interpolation on the sorted sample:
    #   position = 0.05 * (n - 1) = 0.05 * 19 = 0.95
    #   -> between x0 and x1, fractional part 0.95
    #   quantile = x0 + 0.95 * (x1 - x0)
    #            = -0.05 + 0.95 * (-0.04 - (-0.05))
    #            = -0.05 + 0.95 * 0.01
    #            = -0.05 + 0.0095
    #            = -0.0405
    #   VaR 95   = -(-0.0405) = 0.0405  (positive loss convention)
    values = [-0.05, -0.04, -0.03, -0.02, -0.01, 0.0] + [
        round(0.001 * i, 3) for i in range(1, 15)
    ]
    assert len(values) == 20
    result = historical_var(_dated(values), confidence=0.95)
    assert abs(result - 0.0405) < 1e-12
