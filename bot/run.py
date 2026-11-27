"""Lancement : télécharge, simule, met à jour le tableau de bord, envoie les notifications.

Usage :  python -m bot.run            (lancement normal)
         python -m bot.run --test     (envoie juste une notification de test)
Variables : TELEGRAM_TOKEN et TELEGRAM_CHAT_ID (secrets GitHub), DASHBOARD_URL (facultatif), START (date de début, défaut dans config)
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import time
from pathlib import Path

import requests

from . import data, sim

ROOT = Path(__file__).resolve().parent.parent
CONFIG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
STATE = ROOT / "state" / "state.json"
OUT = ROOT / "docs" / "data.json"


HINTS = {
    401: "clé TELEGRAM_TOKEN fausse ou révoquée : recopie-la depuis BotFather dans le secret GitHub",
    404: "clé TELEGRAM_TOKEN mal recopiée (espace, caractère manquant ?)",
    400: "TELEGRAM_CHAT_ID faux, ou tu n'as pas encore envoyé /start à ton bot",
    403: "tu as bloqué le bot ou ne lui as jamais écrit : ouvre-le dans Telegram et envoie /start",
}


def configured() -> bool:
    return bool(os.environ.get("TELEGRAM_TOKEN", "").strip() and os.environ.get("TELEGRAM_CHAT_ID", "").strip())


def notify(title: str, msg: str, tags=(), session=requests) -> bool:
    """Envoie un message Telegram. La clé et l'identifiant viennent des secrets GitHub, jamais du code."""
    token = os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not (token and chat):
        print("[notif] secrets TELEGRAM_TOKEN / TELEGRAM_CHAT_ID absents : message non envoyé\n", title, "\n", msg)
        return False
    esc = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = f"<b>{esc(title)}</b>\n{esc(msg)}"
    url = os.environ.get("DASHBOARD_URL", "").strip()
    if url:
        text += f'\n\n<a href="{esc(url)}">Tableau de bord</a>'
    body = {"chat_id": chat, "text": text[:4000], "parse_mode": "HTML", "disable_web_page_preview": True}
    api = os.environ.get("TELEGRAM_API", "https://api.telegram.org")
    for k in range(3):
        try:
            r = session.post(f"{api}/bot{token}/sendMessage", json=body, timeout=20)
            if r.status_code == 200:
                print("[notif] Telegram : message envoyé")
                return True
            if r.status_code == 429:                       # trop de messages : Telegram dit combien attendre
                try: time.sleep(min(30, int(r.json()["parameters"]["retry_after"])))
                except Exception: time.sleep(5)
                continue
            # jamais afficher la clé : seulement le code et l'explication
            print(f"[notif] Telegram a refusé (code {r.status_code}) : {HINTS.get(r.status_code, 'erreur inconnue')}")
            if r.status_code in HINTS:
                return False                               # inutile de réessayer
        except Exception as e:
            print("[notif] Telegram injoignable :", type(e).__name__)
        time.sleep(2 * (k + 1))
    return False


def load_state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {"notified": [], "alerts": []}       # fichier absent ou abîmé : on repart proprement


def save_state(st: dict):
    STATE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(STATE)                                # écriture atomique : jamais de fichier à moitié écrit


def week_message(w: dict, res: dict) -> tuple[str, str]:
    st = {k: sim.stats(res["curve"], k) for k in ("bot", "mix", "btc")}
    act = sim.NAMES[w["actif"]]
    if w["change"]:
        title = f"Rotation : {sim.NAMES.get(w['ancien'], w['ancien'])} -> {act}"
    else:
        title = f"Rotation : on garde {act}"
    lines = [sim.reason(w),
             f"Exécution simulée le {w['execution']} (frais simulés {w['frais_eur']:.2f} €).",
             "",
             "Depuis le début (1000 € fictifs) :",
             f"Bot {st['bot']['valeur']:.0f} € ({st['bot']['gain']:+.1%}, pire baisse {st['bot']['pire_baisse']:.0%})",
             f"Mélange fixe {st['mix']['valeur']:.0f} € ({st['mix']['gain']:+.1%}, pire baisse {st['mix']['pire_baisse']:.0%})",
             f"BTC seul {st['btc']['valeur']:.0f} € ({st['btc']['gain']:+.1%}, pire baisse {st['btc']['pire_baisse']:.0%})",
             "Simulation : aucun argent réel."]
    return title, "\n".join(lines)


def build_dashboard(res: dict, sources: dict, problems: list[str], now: dt.datetime):
    payload = {"mis_a_jour": now.strftime("%Y-%m-%d %H:%M UTC"), "debut": CONFIG["start"],
               "sources": sources, "problemes": problems, "started": res.get("started", False)}
    if res.get("started"):
        payload.update(curve=res["curve"], trades=res["trades"], weeks=res["weeks"][-12:],
                       holding=res["holding"], last_data=res["last_data"],
                       stats={k: sim.stats(res["curve"], k) for k in ("bot", "mix", "btc")},
                       raison=sim.reason(res["weeks"][-1]) if res["weeks"] else "")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def main(argv=None, today: dt.date | None = None, session=requests) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args(argv)
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    today = today or now.date()
    if a.test:
        ok = notify("Rotation : test", "Si tu lis ceci, les messages Telegram marchent. ✅", session=session)
        return 0 if ok else 1

    st = load_state()
    start = os.environ.get("START") or CONFIG["start"]
    since = dt.date.fromisoformat(start) - dt.timedelta(days=500)     # 12 mois de bourse de recul + marge
    problems, sources = [], {}
    try:
        eq = data.equity(session)
        sources["ACTIONS"] = "FRED (Nasdaq Developed Markets, dividendes inclus)"
        btc, sources["BTC"] = data.crypto("BTC", since, session)
        eth, sources["ETH"] = data.crypto("ETH", since, session)
        px = sim.align(eq.loc[eq.index >= str(since)], btc, eth)
        problems = data.check(px, today)
    except data.DataError as e:
        problems = [f"téléchargement impossible : {e}"]
        px = None

    if problems:
        if str(today) not in st["alerts"]:      # au plus une alerte par jour
            notify("Rotation : donnée manquante", "Pas de décision aujourd'hui :\n- " + "\n- ".join(problems)
                   + "\nLe bot réessaie au prochain lancement. Position simulée inchangée.", ("warning",), session)
            st["alerts"] = (st["alerts"] + [str(today)])[-30:]
        save_state(st)
        old = json.loads(OUT.read_text(encoding="utf-8")) if OUT.exists() else {}
        old.update(problemes=problems, mis_a_jour=now.strftime("%Y-%m-%d %H:%M UTC"))
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        print("PROBLÈMES :", problems)
        return 0     # pas une panne : on réessaiera

    res = sim.simulate(px, start)
    build_dashboard(res, sources, [], now)
    new = [w for w in res.get("weeks", []) if w["decision"] not in st["notified"]]
    ok = True
    for w in new[-3:]:                          # rattrapage : au plus 3 messages d'un coup
        title, msg = week_message(w, res)
        ok = notify(title, msg, session=session) and ok
    if ok or not configured():  # si l'envoi rate, on réessaie au prochain lancement
        st["notified"] = sorted(set(st["notified"]) | {w["decision"] for w in new})
    save_state(st)
    print(f"OK : {len(res.get('weeks', []))} semaines simulées, {len(new)} nouvelle(s), position {res.get('holding')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
