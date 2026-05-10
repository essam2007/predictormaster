"""FastAPI inference service. Wires the meta-ensemble + simulator behind a
versioned /forecast endpoint. Uvicorn is the dev server; production serves
through Triton (see infra/triton).
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..models.dixon_coles import DixonColesFit
from ..simulation.monte_carlo import simulate_poisson


def make_forecast(
    *, model: DixonColesFit, home: str, away: str, n_sims: int = 50_000
) -> dict[str, object]:
    lam, mu = model.intensities(home, away)
    sim = simulate_poisson(lam_home=lam, lam_away=mu, n_sims=n_sims)
    return {
        "produced_utc": datetime.now(timezone.utc).isoformat(),
        "home": home,
        "away": away,
        "p_home": sim.p_home,
        "p_draw": sim.p_draw,
        "p_away": sim.p_away,
        "expected_score_home": sim.expected_score_home,
        "expected_score_away": sim.expected_score_away,
    }


def build_app():  # pragma: no cover - integration
    from fastapi import FastAPI, HTTPException
    from pydantic import BaseModel

    app = FastAPI(title="predictormaster", version="0.1.0")

    class ForecastRequest(BaseModel):
        home: str
        away: str
        n_sims: int = 50_000

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/forecast")
    def forecast(req: ForecastRequest) -> dict[str, object]:
        from .. import _model_singleton  # type: ignore[attr-defined]

        if _model_singleton is None:
            raise HTTPException(status_code=503, detail="model not loaded")
        return make_forecast(
            model=_model_singleton, home=req.home, away=req.away, n_sims=req.n_sims
        )

    return app
