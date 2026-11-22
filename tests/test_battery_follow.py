"""battery_follow: varning när husbatteriet inte gör det det blir tillsagt (önskemål på Discord), och
notify_prefs: alla notiser går att stänga av."""
import battery_follow as bf
import notify_prefs


def test_laddar_trots_order_om_urladdning_blir_varning_efter_fem_minuter():
    w = bf.FollowWatch()
    assert w.step("discharge", 812, 2300, 40, 10, 0)[0] == "checking"
    st, txt, new = w.step("discharge", 812, 2300, 40, 10, 4 * 60)
    assert st == "checking" and not new
    st, txt, new = w.step("discharge", 812, 2300, 40, 10, 5 * 60)
    assert st == "not_following" and new and "urladdning 812 W" in txt and "laddar 2.3 kW" in txt
    assert w.step("discharge", 812, 2300, 40, 10, 6 * 60)[2] is False          # bara en notis per avvikelse
    assert w.step("discharge", 812, -800, 40, 10, 7 * 60)[0] == "following"     # i fas igen


def test_naturliga_forklaringar_ger_ingen_varning():
    assert bf.mismatch("charge", 3000, 0, 99, 10) is None          # fullt
    assert bf.mismatch("discharge", 2000, 0, 11, 10) is None       # vid reserven
    assert bf.mismatch("hold", None, 1500, 50, 10) is None         # sparas men tar emot sol
    assert bf.mismatch("auto", None, -3000, 50, 10) is None
    assert bf.mismatch("hold", None, -1500, 50, 10)                 # sparas men laddar ur


def test_alla_notiser_har_en_kategori_som_kan_stangas_av(monkeypatch, tmp_path):
    import ew_settings
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "s.json"))
    ew_settings._cache.update(mtime=None, data={})
    assert notify_prefs.enabled(title="🚨 Värmepump i läge 0!")
    notify_prefs.set_disabled(["varmepump", "ovrigt"])
    assert not notify_prefs.enabled(title="🚨 Värmepump i läge 0!")
    assert not notify_prefs.enabled(title="🧺 Tvättmaskinen startad")             # okänt -> Övrigt, också avstängbart
    assert notify_prefs.enabled(key="batteri", title="x")
    assert {c["key"] for c in notify_prefs.listing() if not c["on"]} == {"varmepump", "ovrigt"}


def test_notifier_skickar_inte_avstangd_kategori(monkeypatch, tmp_path):
    import ew_settings
    import notifier
    monkeypatch.setattr(ew_settings, "PATH", str(tmp_path / "s.json"))
    ew_settings._cache.update(mtime=None, data={})
    notify_prefs.set_disabled(["batteri"])
    sent = []
    monkeypatch.setattr(notifier, "target", lambda: "mobile_app_x")
    monkeypatch.setattr(notifier, "_send", lambda *a, **k: sent.append(a) or True)
    assert notifier.send_emil("🔋 Husbatteriet gör inte som det blir tillsagt", "x", key="batteri") is False
    assert notifier.send_emil("🚗 Bilen laddar", "x") is True and len(sent) == 1


def test_batteriets_egen_gransvarde_forklarar_att_det_star_still():
    # drivrutinen säger att batteriet just nu inte kan ge/ta emot effekt -> ingen varning
    assert bf.mismatch("discharge", 2000, 0, 50, 10, avail_discharge_w=0) is None
    assert bf.mismatch("charge", 3000, 0, 50, 10, avail_charge_w=100) is None
    # fel riktning: laddar fast det skulle ladda ur varnar alltid, hur låg gränsen än är
    assert bf.mismatch("discharge", 2000, 1500, 50, 10, avail_discharge_w=0)
    # drivrutinen säger att det kan ge effekt men det står still -> varnar som förut
    assert bf.mismatch("discharge", 2000, 0, 50, 10, avail_discharge_w=4000)
    assert bf.mismatch("charge", 3000, 0, 50, 10, avail_charge_w=4000)
    # gränsen i fel riktning förklarar inget
    assert bf.mismatch("discharge", 2000, 0, 50, 10, avail_charge_w=0)


def test_okanda_eller_ogiltiga_gransvarden_raknas_aldrig_som_begransning():
    for bad in (None, "0", True, -5, float("nan")):
        assert bf.mismatch("discharge", 2000, 0, 50, 10, avail_discharge_w=bad), bad


def test_gransvarde_genom_followwatch_ger_following_och_ingen_notis():
    w = bf.FollowWatch()
    for t in (0, 5 * 60, 10 * 60):
        st, txt, new = w.step("discharge", 2000, 0, 50, 10, t, None, 0)
        assert st == "following" and txt is None and not new


def test_gransen_forklarar_bara_stillastaende_inte_fel_riktning():
    assert bf.mismatch("charge", 3000, -1500, 50, 10, avail_charge_w=0)      # laddar ur fast det skulle ladda
    assert bf.mismatch("discharge", 2000, 1500, 50, 10, avail_discharge_w=0)  # laddar fast det skulle ladda ur
