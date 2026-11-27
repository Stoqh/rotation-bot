"""Téléchargement des prix (gratuit, sans compte) + contrôles de qualité."""
from __future__ import annotations

import datetime as dt
import io
import time

import pandas as pd
import requests

UA = {"User-Agent": "rotation-bot-simulation (github.com)"}
FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=NASDAQNQDMT"   # actions pays développés, dividendes inclus
COINBASE = "https://api.exchange.coinbase.com/products/{p}/candles"
KRAKEN = "https://api.kraken.com/0/public/OHLC?pair={p}&interval=1440"


class DataError(Exception):
    pass


def _get(url, params=None, tries=3, session=requests):
    last = None
    for k in range(tries):
        try:
            r = session.get(url, params=params, headers=UA, timeout=30)
            if r.status_code == 200:
                return r
            last = f"HTTP {r.status_code}"
        except Exception as e:  # coupure réseau, délai dépassé…
            last = str(e)
        time.sleep(3 * (k + 1))
    raise DataError(f"{url} : {last}")


def equity(session=requests) -> pd.Series:
    df = pd.read_csv(io.StringIO(_get(FRED, session=session).text))
    df.columns = ["d", "v"]
    s = pd.Series(pd.to_numeric(df["v"], errors="coerce").values, index=pd.to_datetime(df["d"])).dropna()
    if len(s) < 300:
        raise DataError("historique actions trop court")
    return s


def coinbase(product: str, since: dt.date, session=requests) -> pd.Series:
    out = {}
    s = dt.datetime.combine(since, dt.time())
    end = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    while s < end:
        e = min(s + dt.timedelta(days=299), end)
        r = _get(COINBASE.format(p=product), {"granularity": 86400, "start": s.strftime("%Y-%m-%dT00:00:00Z"),
                                              "end": e.strftime("%Y-%m-%dT00:00:00Z")}, session=session)
        for t, lo, hi, o, c, vol in r.json():
            out[pd.Timestamp(t, unit="s")] = float(c)
        s = e
        time.sleep(0.35)
    if not out:
        raise DataError(f"Coinbase {product} vide")
    return pd.Series(out).sort_index()


def kraken(pair: str, session=requests) -> pd.Series:
    j = _get(KRAKEN.format(p=pair), session=session).json()
    if j.get("error"):
        raise DataError(f"Kraken {pair} : {j['error']}")
    rows = next(v for k, v in j["result"].items() if k != "last")
    return pd.Series({pd.Timestamp(int(r[0]), unit="s"): float(r[4]) for r in rows}).sort_index()


def crypto(name: str, since: dt.date, session=requests):
    """Coinbase d'abord, Kraken en secours (720 jours max, assez pour 12 mois)."""
    try:
        return coinbase(f"{name}-USD", since, session), "Coinbase"
    except DataError as e1:
        try:
            return kraken({"BTC": "XBTUSD", "ETH": "ETHUSD"}[name], session), "Kraken (secours)"
        except DataError as e2:
            raise DataError(f"{name} introuvable : {e1} / {e2}")


def check(px: pd.DataFrame, today: dt.date) -> list[str]:
    """Problèmes bloquants : données en retard, trous, sauts absurdes."""
    probs = []
    if px.empty:
        return ["aucune donnée commune"]
    age = (pd.Timestamp(today) - px.index[-1]).days
    if age > 6:
        probs.append(f"données en retard : dernier jour commun {px.index[-1].date()} ({age} jours)")
    jump = px.pct_change().abs().iloc[-30:].max()
    for a, x in jump.items():
        if x > 0.6:
            probs.append(f"saut suspect sur {a} ({x:.0%} en un jour)")
    if (px.iloc[-30:] <= 0).any().any():
        probs.append("prix nul ou négatif")
    gaps = px.index.to_series().diff().dt.days.iloc[-60:]
    if (gaps > 6).any():
        probs.append("trou de plus de 6 jours dans les 60 derniers jours")
    return probs
