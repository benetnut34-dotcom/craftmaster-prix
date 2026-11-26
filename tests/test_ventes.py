"""Tests hors ligne de fetch.py (detection des ventes, profondeur). Lancer : python3 tests/test_ventes.py"""
import gzip
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import fetch  # noqa: E402

H = 3600
T0 = 1_800_000_000
fails = 0


def check(cond, msg):
    global fails
    print(('ok    ' if cond else 'ECHEC ') + msg)
    if not cond:
        fails += 1


def snap(prev, raw, at):
    """raw : {id annonce: (objet, qte, prix, tranche, commodite)} -> annonces avec fenetre"""
    return fetch.with_windows(prev, raw, at)


def day(sales, iid):
    d = sales.get(str(iid), {})
    return next(iter(d.values())) if d else {'n': 0, 'u': 0, 'x': 0, 'p': []}


# --- fenetre de fin : resserree par les photos successives
p1 = snap(None, {'a': (1, 1, 100, 3, 0)}, T0)                   # plus de 12 h
check(p1['a'][5] == T0 + 12 * H and p1['a'][6] == T0 + 48 * H, 'premiere photo : fin entre 12 h et 48 h')
p2 = snap(p1, {'a': (1, 1, 100, 2, 0)}, T0 + H)                  # passee sous 12 h
check(p2['a'][5] == T0 + 12 * H and p2['a'][6] == T0 + 13 * H, 'passage a LONG : fin entre 12 h et 13 h (%s)' % ((p2['a'][5] - T0) / H, ))
check(fetch.norm_listing((1, 1, 100, 1), T0)[5:] == (T0 + 1800, T0 + 7200, T0), 'ancien format de photo accepte')

# --- expiration ou vente selon la fenetre
s = {}
prev = snap(None, {'x': (1, 1, 100, 0, 0), 'y': (2, 1, 100, 2, 0), 'z': (3, 1, 100, 1, 0)}, T0)
r = fetch.track_sales(prev, T0, snap(prev, {}, T0 + H), T0 + H, s)
check(day(s, 1)['x'] == 1 and day(s, 1)['n'] == 0, 'moins de 30 min restantes, disparue : expiree')
check(day(s, 2)['n'] == 1, '2 a 12 h restantes, disparue : vendue')
check(0 < day(s, 3)['n'] < 1, '30 min a 2 h, photo 1 h apres : vente au poids reduit (%s)' % day(s, 3)['n'])

# --- commodites : l'achat prend les moins cheres d'abord
s = {}
prev = snap(None, {'c1': (10, 20, 50, 3, 1), 'c2': (10, 20, 80, 3, 1)}, T0)
cur = snap(prev, {'c1': (10, 20, 50, 3, 1)}, T0 + H)
r = fetch.track_sales(prev, T0, cur, T0 + H, s)
check(day(s, 10)['n'] == 0 and r[2] == 1, 'commodite chere disparue alors que la moins chere reste : retiree')
s = {}
cur = snap(prev, {'c2': (10, 20, 80, 3, 1)}, T0 + H)
fetch.track_sales(prev, T0, cur, T0 + H, s)
check(day(s, 10)['n'] == 1, 'la moins chere disparue : vendue')

# --- objets : moins cheres restees, remise en vente
s = {}
raw = {'o%d' % i: (20, 1, 100, 3, 0) for i in range(4)}
raw['cher'] = (20, 1, 500, 3, 0)
prev = snap(None, raw, T0)
cur = snap(prev, {k: v for k, v in raw.items() if k != 'cher'}, T0 + H)
fetch.track_sales(prev, T0, cur, T0 + H, s)
check(abs(day(s, 20)['n'] - 0.15) < 1e-9, 'objet cher disparu, 4 moins chers restent : poids 0,15 (%s)' % day(s, 20)['n'])
s = {}
prev = snap(None, {'u': (30, 5, 300, 3, 0)}, T0)
cur = snap(prev, {'v': (30, 5, 250, 3, 0)}, T0 + H)
fetch.track_sales(prev, T0, cur, T0 + H, s)
check(day(s, 30)['n'] == 0.5, 'retiree et remise moins cher (meme quantite) : poids divise par deux (%s)' % day(s, 30)['n'])
s = {}
prev = snap(None, {'w': (40, 10, 70, 3, 1)}, T0)
fetch.track_sales(prev, T0, snap(prev, {'w': (40, 4, 70, 3, 1)}, T0 + H), T0 + H, s)
check(day(s, 40)['u'] == 6 and day(s, 40)['n'] == 1, 'achat partiel : 6 unites vendues')

# --- profondeur publiee
ds = fetch.depth_string({'a': (5, 2, 90, 3, 0), 'b': (5, 3, 90, 3, 0), 'c': (5, 1, 80, 3, 0), 'd': (6, 1, 10, 3, 0)}, {'5': {}})
check(ds == '5=80:1,90:5;', 'profondeur : prix les plus bas, unites cumulees, objets vendus seulement (%s)' % ds)

# --- passage complet (deux photos, fichier Lua)
tmp = tempfile.mkdtemp()
try:
    fetch.OUT = tmp
    shots = [{'s1': (2589, 20, 30, 3, 1), 's2': (2589, 20, 60, 3, 1)}, {'s2': (2589, 20, 60, 3, 1)}]
    at = [T0, T0 + H]

    def fake(rs, hid, tok, k=[0]):
        if hid != 113:
            raise RuntimeError('hors test')
        i = min(k[0], 1)
        items = {}
        for iid, q, u, tl, c in shots[i].values():
            e = items.setdefault(iid, [0, 0])
            e[0] = u if not e[0] or u < e[0] else e[0]
            e[1] += q
        return items, at[i], dict(shots[i])

    fake.__defaults__ = ([0],)
    counter = fake.__defaults__[0]
    fetch.run(fetch=fake)
    counter[0] = 1
    fetch.run(fetch=fake)
    with open(os.path.join(tmp, 'Data-PvP.lua')) as f:
        lua = f.read()
    check('sales = "2589=1,20,0,' in lua, 'Data-PvP.lua : la commodite la moins chere vendue')
    check('depth = "2589=60:20;"' in lua, 'Data-PvP.lua : profondeur publiee')
    with gzip.open(os.path.join(tmp, 'prev-113.json.gz'), 'rt') as f:
        check(len(json.load(f)['l']['s2']) == 8, 'photo gardee avec sa fenetre de fin')
finally:
    shutil.rmtree(tmp)


# --- profil horaire : l'indice du marche par heure et jour de la semaine (UTC)
at = 1_800_000_000 + 5 * 86400
dnow = at // 86400
lw = {str(i): {str(dnow - k): 1000 for k in (1, 2, 3)} for i in range(1, 301)}
mi = fetch.market_index({i: (900, 5) for i in range(1, 301)}, lw, at)
check(mi and abs(mi[0] - 0.9) < 1e-9 and mi[1] == 300, "indice du marche : 900 / habituel 1000 = 0,90 sur 300 objets")
check(fetch.market_index({i: (900, 5) for i in range(1, 50)}, lw, at) is None, 'trop peu d objets : pas d indice')
check(fetch.market_index({i: (900, 5) for i in range(1, 301)}, {k: {str(dnow - 1): 1000} for k in lw}, at) is None, 'moins de 3 jours de prix : pas d habituel')
pf = {}
for k, v in ((0, 0.90), (7, 0.92), (14, 1.30)):          # meme jour de la semaine et meme heure, 3 semaines
    fetch.prof_note(pf, v, at - k * 86400)
check(len(pf) == 1, 'trois semaines au meme creneau : un seul creneau')
check(fetch.prof_string(pf, dnow).endswith(':3;') or ':2;' in fetch.prof_string(pf, dnow), 'chaine de profil : creneau:indice:nombre')
fetch.prof_note(pf, 0.5, at)
ps = fetch.prof_string(pf, dnow)
check(ps.count(';') == 1 and ps.split(':')[2] == '710', 'la meme heure du meme jour : la derniere ecrase, mediane de deux = moyenne (%s)' % ps)

print('TOUT EST BON' if not fails else '%d ECHEC(S)' % fails)
raise SystemExit(1 if fails else 0)
