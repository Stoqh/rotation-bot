"""Tests : décision, pas de données du futur, frais, notifications, redémarrage, données manquantes."""
import datetime as dt
import json

import numpy as np
import pandas as pd
import pytest

from bot import data, run, sim


# ---------------------------------------------------------------- données synthétiques
def make_px(days=700, seed=0, drift=None, end="2026-11-25"):
    idx = pd.bdate_range(end=end, periods=days)
    rng = np.random.default_rng(seed)
    drift = drift or {"BTC": 0.002, "ETH": 0.0005, "ACTIONS": 0.0003}
    df = pd.DataFrame({a: 100 * np.exp(np.cumsum(rng.normal(drift[a], 0.02, days))) for a in sim.ASSETS}, index=idx)
    return df


class FakeResp:
    def __init__(self, code=200, text="", js=None):
        self.status_code, self.text, self._js = code, text, js
    def json(self):
        return self._js


class FakeSession:
    """Imite FRED, Coinbase, Kraken et Telegram. Peut simuler des pannes."""
    def __init__(self, px, fail=(), tg_code=200):
        self.px, self.fail, self.tg_code, self.posts, self.urls = px, set(fail), tg_code, [], []
    def get(self, url, params=None, headers=None, timeout=None):
        if "fred" in url:
            if "fred" in self.fail: return FakeResp(500)
            s = self.px["ACTIONS"]
            return FakeResp(text="observation_date,X\n" + "\n".join(f"{d.date()},{v}" for d, v in s.items()))
        if "coinbase" in url:
            if "coinbase" in self.fail: return FakeResp(503)
            a = "BTC" if "BTC" in url else "ETH"
            s0, e0 = pd.Timestamp(params["start"][:10]), pd.Timestamp(params["end"][:10])
            ser = self.px[a].asfreq("D").ffill()       # crypto : tous les jours
            ser = ser[(ser.index >= s0) & (ser.index < e0)]
            return FakeResp(js=[[int(d.timestamp()), 0, 0, 0, float(v), 0] for d, v in ser.items()][::-1])
        if "kraken" in url:
            if "kraken" in self.fail: return FakeResp(500)
            a = "BTC" if "XBT" in url else "ETH"
            ser = self.px[a].asfreq("D").ffill().iloc[-720:]
            return FakeResp(js={"error": [], "result": {"X": [[int(d.timestamp()), 0, 0, 0, str(v), 0, 0, 0] for d, v in ser.items()], "last": 0}})
        return FakeResp(404)
    def post(self, url, json=None, timeout=None):
        self.urls.append(url)
        code = self.tg_code if isinstance(self.tg_code, int) else self.tg_code.pop(0)
        if code == 200:
            self.posts.append({"title": json["text"].split("\n")[0], "message": json["text"], **json})
        return FakeResp(code, js={"ok": code == 200, "parameters": {"retry_after": 1}})


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(run, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(run, "OUT", tmp_path / "data.json")
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:SECRET-TOKEN-XYZ")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "987654321")
    monkeypatch.setattr(run.time, "sleep", lambda s: None)
    monkeypatch.setenv("START", "2026-08-01")
    monkeypatch.setattr(data.time, "sleep", lambda s: None)
    return tmp_path


# ---------------------------------------------------------------- décision
def test_decision_plus_fort_et_positif():
    px = make_px()
    i = len(px) - 1
    choice, sc = sim.decide(px, i)
    assert choice == max(sc, key=sc.get) and sc[choice] > 0


def test_tout_baisse_donne_liquide():
    px = make_px(drift={"BTC": -0.003, "ETH": -0.003, "ACTIONS": -0.003})
    choice, sc = sim.decide(px, len(px) - 1)
    assert choice == "LIQUIDE" and all(v < 0 for v in sc.values())


def test_pas_de_donnees_du_futur():
    px = make_px()
    i = len(px) - 50
    before = sim.decide(px, i)
    px2 = px.copy(); px2.iloc[i + 1:] *= 50       # le futur change énormément
    assert sim.decide(px2, i) == before


def test_semaine_incomplete_ignoree():
    px = make_px()
    ends = sim.week_ends(px.index)
    assert all(i + 1 < len(px) for i in ends)
    # la dernière semaine dont le jour suivant n'existe pas encore n'est pas décidée
    assert len(px) - 1 not in ends


def test_execution_jour_suivant_et_frais():
    px = make_px()
    res = sim.simulate(px, str(px.index[-120].date()))
    for w in res["weeks"]:
        d, e = pd.Timestamp(w["decision"]), pd.Timestamp(w["execution"])
        assert px.index.get_loc(e) == px.index.get_loc(d) + 1
        assert (w["frais_eur"] > 0) == w["change"]           # frais seulement quand on change


def test_btc_seul_suit_le_prix():
    px = make_px()
    res = sim.simulate(px, str(px.index[-200].date()))
    first = pd.Timestamp(res["curve"][0]["date"])
    expect = sim.CAPITAL * (1 - sim.COST["BTC"]) * px["BTC"].iloc[-1] / px.loc[first, "BTC"]
    assert res["values"]["btc"] == pytest.approx(expect, abs=0.01)


def test_melange_reequilibre_une_fois_par_an():
    px = make_px(days=900)
    res = sim.simulate(px, str(px.index[300].date()))
    years = {c["date"][:4] for c in res["curve"]}
    assert len(years) >= 2 and res["values"]["mix"] > 0


def test_meme_resultat_si_relance():
    px = make_px()
    a = sim.simulate(px, "2026-06-01"); b = sim.simulate(px, "2026-06-01")
    assert a == b


# ---------------------------------------------------------------- lancement complet
def test_notification_une_seule_fois_et_redemarrage(env):
    px = make_px()
    s = FakeSession(px)
    assert run.main([], today=dt.date(2026, 11, 26), session=s) == 0
    n1 = len(s.posts)
    assert n1 >= 1 and "Rotation" in s.posts[-1]["title"] and "Bot" in s.posts[-1]["message"]
    # redémarrage (nouveau lancement, mêmes données) : aucun doublon
    run.main([], today=dt.date(2026, 11, 26), session=s)
    assert len(s.posts) == n1
    d = json.loads(run.OUT.read_text(encoding="utf-8"))
    assert d["started"] and len(d["curve"]) > 10 and set(d["stats"]) == {"bot", "mix", "btc"}


def test_nouvelle_semaine_notifiee(env):
    px = make_px()
    s = FakeSession(px.iloc[:-5])
    run.main([], today=px.index[-6].date(), session=s)
    n1 = len(s.posts)
    s.px = px                                     # une semaine de plus arrive
    run.main([], today=px.index[-1].date(), session=s)
    assert len(s.posts) == n1 + 1


def test_etat_abime_ne_bloque_pas(env):
    px = make_px()
    run.STATE.write_text("{pas du json", encoding="utf-8")
    assert run.main([], today=dt.date(2026, 11, 26), session=FakeSession(px)) == 0
    json.loads(run.STATE.read_text(encoding="utf-8"))   # réparé


def test_donnees_en_retard_alerte_une_fois(env):
    px = make_px(end="2026-11-02")
    s = FakeSession(px)
    run.main([], today=dt.date(2026, 11, 26), session=s)
    run.main([], today=dt.date(2026, 11, 26), session=s)
    alerts = [p for p in s.posts if "manquante" in p["title"]]
    assert len(alerts) == 1 and "retard" in alerts[0]["message"]
    assert not [p for p in s.posts if "manquante" not in p["title"]]   # aucune décision


def test_source_actions_en_panne(env):
    s = FakeSession(make_px(), fail={"fred"})
    assert run.main([], today=dt.date(2026, 11, 26), session=s) == 0
    assert "manquante" in s.posts[0]["title"]


def test_secours_kraken_si_coinbase_en_panne(env):
    s = FakeSession(make_px(), fail={"coinbase"})
    run.main([], today=dt.date(2026, 11, 26), session=s)
    d = json.loads(run.OUT.read_text(encoding="utf-8"))
    assert d["started"] and "Kraken" in d["sources"]["BTC"]


def test_saut_absurde_detecte():
    px = make_px(); px.iloc[-3, 0] *= 5
    assert any("saut" in p for p in data.check(px, px.index[-1].date()))


def test_telegram_en_panne_reessaie(env):
    px = make_px()
    s = FakeSession(px, tg_code=502)
    run.main([], today=dt.date(2026, 11, 26), session=s)
    assert s.posts == []
    s.tg_code = 200
    run.main([], today=dt.date(2026, 11, 26), session=s)
    assert len(s.posts) >= 1                        # renvoyé une fois Telegram revenu


def test_format_telegram(env):
    s = FakeSession(make_px())
    run.main(["--test"], session=s)
    p = s.posts[0]
    assert s.urls[0] == "https://api.telegram.org/bot123456:SECRET-TOKEN-XYZ/sendMessage"
    assert p["chat_id"] == "987654321" and p["parse_mode"] == "HTML" and p["text"].startswith("<b>Rotation : test</b>")


def test_cle_jamais_affichee(env, capsys):
    s = FakeSession(make_px(), tg_code=401)
    assert run.main(["--test"], session=s) == 1
    out = capsys.readouterr().out
    assert "SECRET-TOKEN" not in out and "BotFather" in out
    assert len(s.urls) == 1                         # clé refusée : on n'insiste pas


def test_trop_de_messages_attend_et_renvoie(env):
    s = FakeSession(make_px(), tg_code=[429, 200])
    assert run.main(["--test"], session=s) == 0 and len(s.posts) == 1


def test_secrets_absents_echec_visible(env, monkeypatch):
    monkeypatch.delenv("TELEGRAM_TOKEN")
    assert run.main(["--test"], session=FakeSession(make_px())) == 1


def test_caracteres_speciaux_echappes(env):
    s = FakeSession(make_px())
    assert run.notify("A < B & C", "x > y", session=s)
    assert "A &lt; B &amp; C" in s.posts[0]["text"] and "x &gt; y" in s.posts[0]["text"]


def test_notification_de_test(env):
    s = FakeSession(make_px())
    assert run.main(["--test"], session=s) == 0 and "test" in s.posts[0]["title"]
