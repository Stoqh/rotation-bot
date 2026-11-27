"""Moteur de simulation : rotation hebdomadaire 1 actif / 12 mois, mélange fixe 1/3, BTC seul.

Tout est recalculé depuis l'historique complet à chaque lancement : si le bot s'arrête
ou rate une semaine, il rattrape tout seul au lancement suivant, sans état fragile.
Aucun argent réel : aucune clé de plateforme, aucun ordre.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

ASSETS = ["BTC", "ETH", "ACTIONS"]
LOOKBACK = 252                     # 12 mois de bourse
COST = {"BTC": 0.0050, "ETH": 0.0050, "ACTIONS": 0.0025}   # par côté : frais + glissement (Kraken / courtier)
CAPITAL = 1000.0                   # capital fictif (€)
NAMES = {"BTC": "Bitcoin", "ETH": "Ether", "ACTIONS": "Actions mondiales", "LIQUIDE": "Liquide"}


def align(equity: pd.Series, btc: pd.Series, eth: pd.Series) -> pd.DataFrame:
    """Calendrier = jours de bourse des actions. Crypto : dernier prix connu (3 jours max)."""
    cal = equity.dropna().index
    df = pd.DataFrame({"ACTIONS": equity.loc[cal]})
    df["BTC"] = btc.sort_index().reindex(cal, method="ffill", tolerance=pd.Timedelta("3D"))
    df["ETH"] = eth.sort_index().reindex(cal, method="ffill", tolerance=pd.Timedelta("3D"))
    return df[ASSETS].dropna()


def decide(px: pd.DataFrame, i: int):
    """Décision avec les clôtures jusqu'au jour i inclus. Renvoie (actif, rendements 12 mois)."""
    if i < LOOKBACK:
        return None, {}
    sc = {a: float(px[a].iloc[i] / px[a].iloc[i - LOOKBACK] - 1) for a in ASSETS}
    best = max(sc, key=sc.get)
    return (best if sc[best] > 0 else "LIQUIDE"), sc


def week_ends(idx: pd.DatetimeIndex) -> list[int]:
    """Positions du dernier jour de bourse de chaque semaine COMPLÈTE (le jour suivant est connu)."""
    s = pd.Series(np.arange(len(idx)), index=idx)
    last = s.groupby(idx.to_period("W")).max().values
    return [int(i) for i in last if i + 1 < len(idx)]


def _drift(w: np.ndarray, r: np.ndarray):
    g = float(w @ r)
    w2 = w * (1 + r) / (1 + g) if (1 + g) > 0 else w
    return g, w2


def simulate(px: pd.DataFrame, start: str) -> dict:
    """Simule les 3 portefeuilles à partir de la première décision prise le jour `start` ou après."""
    idx = px.index
    rets = px.pct_change().fillna(0).values
    col = {a: k for k, a in enumerate(ASSETS)}
    wends = [i for i in week_ends(idx) if idx[i] >= pd.Timestamp(start) and i >= LOOKBACK]
    if not wends:
        return {"started": False, "trades": [], "weeks": []}

    fills = {i + 1: i for i in wends}          # jour d'exécution -> jour de décision
    first = wends[0] + 1
    w_bot = np.zeros(3); w_mix = np.zeros(3); w_btc = np.zeros(3)
    v = {"bot": CAPITAL, "mix": CAPITAL, "btc": CAPITAL}
    holding = "LIQUIDE"
    curve, trades, weeks = [], [], []
    for t in range(first, len(idx)):
        r = rets[t]
        if t > first:                                    # rendement du jour sur la position de la veille
            for name, w in (("bot", w_bot), ("mix", w_mix), ("btc", w_btc)):
                g, w2 = _drift(w, r); v[name] *= 1 + g
                if name == "bot": w_bot = w2
                elif name == "mix": w_mix = w2
                else: w_btc = w2
        # ---- mélange fixe : achat le 1er jour, puis rééquilibrage au 1er jour de bourse de chaque année
        if t == first or idx[t].year != idx[t - 1].year:
            tgt = np.ones(3) / 3
            cost = sum(abs(tgt[k] - w_mix[k]) * COST[a] for a, k in col.items())
            v["mix"] *= 1 - cost; w_mix = tgt
        # ---- BTC seul : achat le 1er jour
        if t == first:
            v["btc"] *= 1 - COST["BTC"]; w_btc = np.array([1.0, 0, 0])
        # ---- bot : exécution à la clôture du jour suivant la décision
        if t in fills:
            i = fills[t]
            choice, sc = decide(px, i)
            tgt = np.zeros(3)
            if choice != "LIQUIDE": tgt[col[choice]] = 1.0
            cost = sum(abs(tgt[k] - w_bot[k]) * COST[a] for a, k in col.items())
            changed = choice != holding
            before = v["bot"]
            v["bot"] *= 1 - cost; w_bot = tgt
            wk = {"decision": str(idx[i].date()), "execution": str(idx[t].date()), "actif": choice,
                  "ancien": holding, "change": changed, "scores": {a: round(x, 4) for a, x in sc.items()},
                  "frais_eur": round(before - v["bot"], 2)}
            weeks.append(wk)
            if changed:
                trades.append({**wk, "prix": {a: float(px[a].iloc[t]) for a in ASSETS}})
            holding = choice
        curve.append({"date": str(idx[t].date()), **{k: round(x, 2) for k, x in v.items()}})
    return {"started": True, "curve": curve, "trades": trades, "weeks": weeks, "holding": holding,
            "values": {k: round(x, 2) for k, x in v.items()}, "last_data": str(idx[-1].date())}


def stats(curve: list[dict], key: str) -> dict:
    if not curve:
        return {"gain": 0.0, "pire_baisse": 0.0}
    s = pd.Series([c[key] for c in curve])
    return {"gain": float(s.iloc[-1] / CAPITAL - 1), "pire_baisse": float((s / s.cummax() - 1).min()),
            "valeur": float(s.iloc[-1])}


def reason(week: dict) -> str:
    sc = week["scores"]
    parts = ", ".join(f"{NAMES[a]} {sc[a]:+.0%}" for a in sorted(sc, key=lambda a: -sc[a]))
    if week["actif"] == "LIQUIDE":
        return f"Sur 12 mois : {parts}. Tout baisse, donc liquide."
    return f"Sur 12 mois : {parts}. {NAMES[week['actif']]} est le plus fort et en hausse."
