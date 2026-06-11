"""Portfolio optimization engine (F8.3) + Black-Litterman layer (F8.4).

Layering (dispatch F8 §3):
- ``data``             — DB → aligned daily return matrix (funds + equities).
- ``engine``           — pure numpy/cvxpy solvers. μ-FREE by design (gate G5):
                         no objective consumes a historical mean of returns.
- ``black_litterman``  — the ONLY module where expected returns exist:
                         equilibrium (reverse optimization), user views,
                         posterior, scenario re-centering, BL max-utility.
"""
