"""Prix des hotels des ventes de WoW Forever pour CraftMaster.

Lance plusieurs fois par heure par GitHub Actions (.github/workflows/prix.yml),
sans qu'aucun PC ne soit allume. Telecharge les hotels du serveur JcJ (PvP)
depuis l'API officielle de Blizzard, garde les prix les plus bas des KEEP_DAYS
derniers jours (state.json), compte les photos recues par jour (couverture :
pour voir les trous) et ecrit Data-PvP.lua, que le compagnon CraftMaster
telecharge, sans identifiant. Tout ce qui est plus vieux que KEEP_DAYS, ou qui
concerne un autre type de serveur, est purge.

Identifiants : secrets du depot BLIZZARD_CLIENT_ID et BLIZZARD_CLIENT_SECRET.
Python 3, bibliotheque standard seulement.
"""
import base64
import email.utils
import gzip
import math
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

REGION = os.environ.get('REGION', 'eu').lower()
RULESETS = [r.strip() for r in os.environ.get('RULESETS', 'PvP').split(',') if r.strip()]
OUT = os.environ.get('OUT', 'out')
KEEP_DAYS = int(os.environ.get('KEEP_DAYS', '14'))
SOURCE = 'github:' + os.environ.get('GITHUB_REPOSITORY', 'craftmaster-prix') + '@data'
RUN_ID = os.environ.get('GITHUB_RUN_ID', 'local')

# Les trois hotels (Alliance, Horde, commune) de chaque type de serveur.
# L'API ne dit pas a quel type appartient un hotel : correspondance relevee par
# la communaute (110/113/116 = JcJ, 111/114/117 = JcE...). CraftMaster la
# verifie en jeu contre les scans du joueur.
HOUSES = {
    'PvP': (110, 113, 116),
    'PvE': (111, 114, 117),
    'RP': (119, 120, 121),
    'RPvP': (123, 124, 125),
}
RULESET_IDS = {'PvP': 1, 'PvE': 2, 'RP': 3, 'RPvP': 15}
SIDES = ('Alliance', 'Horde', 'Neutral')


def log(msg):
    print(time.strftime('%H:%M:%S'), msg, flush=True)


def token(client_id, secret):
    auth = base64.b64encode(('%s:%s' % (client_id, secret)).encode()).decode()
    req = urllib.request.Request('https://oauth.battle.net/token', data=b'grant_type=client_credentials',
                                 headers={'Authorization': 'Basic ' + auth,
                                          'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)['access_token']


def get(path, tok):
    """(objet JSON, heure des donnees) ; leve une exception en cas d'erreur."""
    url = 'https://%s.api.blizzard.com%s?%s' % (REGION, path, urllib.parse.urlencode(
        {'namespace': 'dynamic-forever-' + REGION, 'locale': 'en_GB'}))
    req = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + tok, 'Accept-Encoding': 'gzip'})
    with urllib.request.urlopen(req, timeout=180) as r:
        raw = r.read()
        if r.headers.get('Content-Encoding') == 'gzip':
            raw = gzip.decompress(raw)
        at = int(time.time())
        lm = r.headers.get('Last-Modified')
        if lm:
            try:
                at = int(email.utils.parsedate_to_datetime(lm).timestamp())
            except (TypeError, ValueError):
                pass
        return json.loads(raw), at


TIME_LEFT = {'SHORT': 0, 'MEDIUM': 1, 'LONG': 2, 'VERY_LONG': 3}
# Ce que veut dire chaque tranche (secondes restantes, bornes de l'API Blizzard) ;
# une annonce dure au plus 48 h.
TL_BOUNDS = ((0, 1800), (1800, 7200), (7200, 43200), (43200, 172800))
MAX_DURATION = 172800


def add_auctions(auctions, items, commodity, listings=None):
    """Prix unitaire le plus bas et quantite totale par objet ;
    listings[id annonce] = (objet, qte, prix unitaire, duree restante, commodite 0/1)."""
    for a in auctions or ():
        item = a.get('item') or {}
        iid, qty = item.get('id'), a.get('quantity') or 0
        if not iid or qty <= 0:
            continue
        if commodity:
            unit = a.get('unit_price') or 0
        else:
            unit = (a['buyout'] / qty) if a.get('buyout') else 0
        cur = items.setdefault(iid, [0, 0])
        if unit > 0 and (cur[0] == 0 or unit < cur[0]):
            cur[0] = int(unit)
        cur[1] += qty
        if listings is not None and unit > 0 and a.get('id'):
            listings[str(a['id'])] = (iid, qty, int(unit), TIME_LEFT.get(a.get('time_left'), 3), 1 if commodity else 0)


def fetch_house(rs, hid, tok):
    """(prix par objet, heure des donnees, annonces)"""
    rsid = RULESET_IDS[rs]
    items, at, listings = {}, 0, {}
    for suffix, commodity in (('', False), ('/commodities', True)):
        data, t = get('/data/wow/ruleset/%d/auctions/%d%s' % (rsid, hid, suffix), tok)
        add_auctions(data.get('auctions'), items, commodity, listings)
        at = max(at, t)
    return {k: v for k, v in items.items() if v[0] > 0}, at, listings


# ---------------------------------------------------------------------------
# Ventes : d'une photo a l'autre, chaque annonce garde son numero.
#
# Fin de vie : chaque photo dit dans quelle tranche de duree restante est
# l'annonce (moins de 30 min, 30 min a 2 h, 2 h a 12 h, plus de 12 h). En
# croisant les photos successives, on resserre la fenetre ou elle expire
# [lo, hi] (une annonce dure au plus 48 h depuis sa premiere apparition).
# Une annonce disparue :
#   - dont la fenetre est passee : expiree ;
#   - qui ne pouvait pas encore expirer : vendue ou retiree, selon :
#       * commodite (minerai, herbes, tissu...) : l'achat prend toujours les
#         moins cheres d'abord ; s'il reste des annonces plus anciennes et
#         moins cheres, elle n'a pas ete achetee : retiree ;
#       * objet : l'acheteur choisit ; des annonces moins cheres qui restent
#         rendent la vente moins probable (poids 0,4 puis 0,15) ;
#       * une nouvelle annonce du meme objet, de la meme quantite et moins
#         chere apparait en meme temps : sans doute retiree puis remise en
#         vente (poids divise par deux) ;
#   - dont la fenetre chevauche la photo : vendue avec un poids reduit d'autant.
# Meme numero, quantite en baisse : achat partiel (vente sure).
# Par objet et par jour : poids des ventes, unites, unites expirees, derniere
# vente, et les prix (pour les quartiles).
# ---------------------------------------------------------------------------
MAX_GAP = 3 * 3600
MAX_PRICES = 40
MIN_WEIGHT = 0.05


def norm_listing(v, at):
    """Une annonce gardee : (objet, qte, prix, tranche, commodite, lo, hi, premiere vue).
    Accepte l'ancien format (objet, qte, prix, tranche)."""
    v = tuple(v)
    if len(v) >= 8:
        return v[:8]
    iid, qty, unit, tl = v[:4]
    c = v[4] if len(v) > 4 else 0
    lo, hi = TL_BOUNDS[tl]
    return (iid, qty, unit, tl, c, at + lo, at + hi, at)


def with_windows(prev, cur, at):
    """Ajoute a chaque annonce de cur sa fenetre de fin [lo, hi] et sa premiere vue."""
    out = {}
    for aid, v in cur.items():
        iid, qty, unit, tl = v[:4]
        c = v[4] if len(v) > 4 else 0   # annonce sans drapeau commodite : traitee comme un objet
        lo, hi = at + TL_BOUNDS[tl][0], at + TL_BOUNDS[tl][1]
        first = at
        p = prev.get(aid) if prev else None
        if p and p[0] == iid:
            first = p[7]
            plo, phi = max(lo, p[5]), min(hi, p[6])
            if plo <= phi:              # sinon les photos se contredisent : on garde la tranche du moment
                lo, hi = plo, phi
        hi = max(lo, min(hi, first + MAX_DURATION))
        out[aid] = (iid, qty, unit, tl, c, lo, hi, first)
    return out


def track_sales(prev, prev_at, cur, cur_at, sales):
    """Ajoute a sales[objet][jour] les ventes entre deux photos (annonces au format
    norm_listing). Renvoie (ventes, expirations, retraits)."""
    if not prev or not prev_at or not (60 < cur_at - prev_at <= MAX_GAP):
        return None
    day = str(cur_at // 86400)
    survivors, fresh = {}, {}         # par objet : prix des annonces restees ; nouvelles annonces
    for aid, v in cur.items():
        if aid in prev:
            survivors.setdefault(v[0], []).append(v[2])
        else:
            fresh.setdefault(v[0], []).append([v[1], v[2], False])
    found = expired = cancelled = 0

    def add(iid, unit, qty, w):
        d = sales.setdefault(str(iid), {}).setdefault(day, {'n': 0, 'u': 0, 'x': 0, 'l': 0, 'p': []})
        if w < 0:
            d['x'] += qty
            return
        d['n'] = round(d['n'] + w, 2)
        d['u'] = round(d['u'] + qty * w, 2)
        d['l'] = max(d['l'], cur_at)
        for e in d['p']:
            if e[0] == unit:
                e[1] = round(e[1] + w, 2)
                break
        else:
            d['p'].append([unit, w])
            if len(d['p']) > MAX_PRICES:
                d['p'].sort(key=lambda e: e[1])
                del d['p'][0]

    for aid, (iid, qty, unit, tl, c, lo, hi, first) in prev.items():
        now = cur.get(aid)
        if now:
            if now[1] < qty:
                add(iid, unit, qty - now[1], 1)
                found += 1
            continue
        # 1) a-t-elle pu expirer avant cette photo ?
        if hi <= cur_at:
            add(iid, unit, qty, -1)
            expired += 1
            continue
        p_exp = 0.0 if lo >= cur_at else (cur_at - lo) / float(hi - lo)
        if p_exp >= 0.5:
            add(iid, unit, qty, -1)
            expired += 1
            continue
        w = 1.0 - p_exp
        # 2) des annonces plus anciennes et moins cheres sont restees
        cheaper = sum(1 for u in survivors.get(iid, ()) if u < unit * (1.0 if c else 0.95))
        if c and cheaper:
            w = 0.0
        elif cheaper:
            w *= 0.4 if cheaper <= 2 else 0.15
        # 3) remise en vente moins cher : nouvelle annonce, meme objet, meme quantite,
        #    prix plus bas (une coincidence reste possible : poids divise par deux)
        if w > 0:
            for f in fresh.get(iid, ()):
                if not f[2] and f[0] == qty and f[1] < unit:
                    f[2] = True
                    w *= 0.5
                    break
        if w < MIN_WEIGHT:
            cancelled += 1
            continue
        add(iid, unit, qty, round(w, 2))
        found += 1
    return found, expired, cancelled


DEPTH_LEVELS = 6


def depth_string(listings, wanted):
    """'id=prix:unites,prix:unites;' : les DEPTH_LEVELS prix les plus bas en vente
    (unites cumulees par prix), pour les objets de wanted (ceux qui ont des ventes)."""
    ladders = {}
    for iid, qty, unit, *_ in listings.values():
        if str(iid) in wanted and unit > 0:
            lv = ladders.setdefault(iid, {})
            lv[unit] = lv.get(unit, 0) + qty
    out = []
    for iid in sorted(ladders):
        lv = sorted(ladders[iid].items())[:DEPTH_LEVELS]
        out.append('%d=%s;' % (iid, ','.join('%d:%d' % pq for pq in lv)))
    return ''.join(out)


def sales_string(sales, since, now):
    """'id=n,unites,expirees,jours,p25,p50,p75,derniere,duree;' sur 14 jours."""
    day = now // 86400
    span = max(1.0, min(KEEP_DAYS, (now - since) / 86400)) if since else 1.0
    out = []
    for iid in sorted(sales, key=int):
        n = u = x = 0
        last, days, prices = 0, 0, {}
        for d, e in sales[iid].items():
            if int(d) <= day - KEEP_DAYS:
                continue
            n += e['n']; u += e['u']; x += e['x']
            last = max(last, e['l'])
            if e['n'] > 0:
                days += 1
            for p, w in e['p']:
                prices[p] = prices.get(p, 0) + w
        if n <= 0 and x <= 0:
            continue
        q = [0, 0, 0]
        if prices:
            pts = sorted(prices.items())
            total = sum(w for _, w in pts)
            for k, pct in enumerate((0.25, 0.5, 0.75)):
                acc, target = 0, total * pct
                for p, w in pts:
                    acc += w
                    if acc >= target:
                        q[k] = p
                        break
        out.append('%s=%g,%d,%d,%d,%d,%d,%d,%d,%.1f;' % (iid, round(n, 2), round(u), x, days, q[0], q[1], q[2], last, span))
    return ''.join(out)


def prune_sales(sales, day):
    for iid in list(sales):
        for d in list(sales[iid]):
            if int(d) <= day - KEEP_DAYS:
                del sales[iid][d]
        if not sales[iid]:
            del sales[iid]


def cov_string(cov, day):
    """'jour:photos,jour:photos' : combien de photos de l'API ont ete recues chaque jour."""
    return ','.join('%d:%d' % (int(d), n) for d, n in sorted(cov.items(), key=lambda kv: int(kv[0]))
                    if int(d) > day - KEEP_DAYS)


def lua_file(rs, houses, lows, now, sales=None, since=None, cov=None):
    """Le meme format que le compagnon PowerShell (CraftMasterData), plus l'origine
    (src, gen), la duree gardee (keep) et la couverture par jour (cov)."""
    day = now // 86400
    out = ['-- Prix publies par craftmaster-prix (API Blizzard). Ne pas modifier.',
           'CraftMasterData = { v = 1, at = %d, region = "%s", ruleset = "%s", keep = %d, src = "%s", gen = "%s", houses = {'
           % (now, REGION, rs, KEEP_DAYS, SOURCE, RUN_ID)]
    for key, h in sorted(houses.items()):
        snap = ''.join('%d:%d:%d;' % (iid, e[0], e[1]) for iid, e in sorted(h['items'].items()))
        lw = []
        for iid, days in sorted(lows.get(key, {}).items(), key=lambda kv: int(kv[0])):
            kept = sorted((int(d), p) for d, p in days.items() if int(d) > day - KEEP_DAYS)
            if kept:
                lw.append('%s=%s;' % (iid, ','.join('%d:%d' % dp for dp in kept)))
        out.append('["%s"] = { id = %d, at = %d,' % (key, h['id'], h['at']))
        out.append('cov = "%s",' % cov_string((cov or {}).get(key, {}), day))
        out.append('items = "%s",' % snap)
        out.append('lows = "%s",' % ''.join(lw))
        out.append('depth = "%s",' % h.get('depth', ''))
        out.append('sales = "%s" },' % sales_string((sales or {}).get(key, {}), (since or {}).get(key), now))
    out.append('} }')
    return '\n'.join(out) + '\n'


def run(fetch=fetch_house, tok=None, state_path=None):
    now = int(time.time())
    day = now // 86400
    state_path = state_path or os.path.join(OUT, 'state.json')
    state = {'lows': {}, 'snap': {}}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
    lows, snaps = state.setdefault('lows', {}), state.setdefault('snap', {})
    sales_all, since = state.setdefault('sales', {}), state.setdefault('since', {})
    cov = state.setdefault('cov', {})
    ok = new = 0
    for rs in RULESETS:
        for side, hid in zip(SIDES, HOUSES[rs]):
            key = '%s-%s' % (rs, side)
            try:
                items, at, listings = fetch(rs, hid, tok)
            except Exception as e:  # une HV en panne ne bloque pas les autres
                log('%s (hotel %d) : erreur : %s' % (key, hid, e))
                continue
            if not items:
                log('%s (hotel %d) : vide' % (key, hid))
                continue
            ok += 1
            # ventes depuis la photo precedente (annonces gardees a part, compressees)
            prev_path = os.path.join(OUT, 'prev-%d.json.gz' % hid)
            prev, prev_at = None, None
            if os.path.exists(prev_path):
                try:
                    with gzip.open(prev_path, 'rt') as f:
                        pv = json.load(f)
                    prev_at = pv['at']
                    prev = {k: norm_listing(v, prev_at) for k, v in pv['l'].items()}
                except (OSError, ValueError, KeyError):
                    prev = None
            depth = (snaps.get(key) or {}).get('depth', '')
            if prev_at != at:
                new += 1
                cur = with_windows(prev, listings, at)
                hc = cov.setdefault(key, {})
                hc[str(at // 86400)] = hc.get(str(at // 86400), 0) + 1
                hs = sales_all.setdefault(key, {})
                r = track_sales(prev, prev_at, cur, at, hs)
                since.setdefault(key, at)
                if r:
                    log('%s : %d vente(s), %d expiration(s), %d retrait(s) depuis %d min' % (key, r[0], r[1], r[2], (at - prev_at) // 60))
                with gzip.open(prev_path, 'wt') as f:
                    json.dump({'at': at, 'l': cur}, f, separators=(',', ':'))
                depth = depth_string(listings, hs)
            snaps[key] = {'id': hid, 'at': at, 'items': {str(k): v for k, v in items.items()}, 'depth': depth}
            d = str(at // 86400)
            hl = lows.setdefault(key, {})
            for iid, (price, _) in items.items():
                days = hl.setdefault(str(iid), {})
                if d not in days or price < days[d]:
                    days[d] = price
            log('%s (hotel %d) : %d objets' % (key, hid, len(items)))
    # purge : les jours trop vieux...
    for hs in sales_all.values():
        prune_sales(hs, day)
    for hl in lows.values():
        for iid in list(hl):
            hl[iid] = {d: p for d, p in hl[iid].items() if int(d) > day - KEEP_DAYS}
            if not hl[iid]:
                del hl[iid]
    for hc in cov.values():
        for d in [d for d in hc if int(d) <= day - KEEP_DAYS]:
            del hc[d]
    # ... et tout ce qui concerne un autre type de serveur
    active = {'%s-%s' % (rs, side): HOUSES[rs][i] for rs in RULESETS for i, side in enumerate(SIDES)}
    for table in (lows, snaps, sales_all, since, cov):
        for k in [k for k in table if k not in active]:
            del table[k]
    os.makedirs(OUT, exist_ok=True)
    for name in os.listdir(OUT):
        prev_m = re.match(r'^prev-(\d+)\.json\.gz$', name)
        data_m = re.match(r'^Data-(\w+)\.lua$', name)
        stale = (prev_m and int(prev_m.group(1)) not in active.values()) or (data_m and data_m.group(1) not in RULESETS)
        if stale:
            os.remove(os.path.join(OUT, name))
            log('purge : %s' % name)
    for rs in RULESETS:
        houses = {k: {'id': s['id'], 'at': s['at'], 'items': {int(i): e for i, e in s['items'].items()}, 'depth': s.get('depth', '')}
                  for k, s in snaps.items() if k.startswith(rs + '-')}
        if houses:
            path = os.path.join(OUT, 'Data-%s.lua' % rs)
            with open(path, 'w') as f:
                f.write(lua_file(rs, houses, lows, now, sales_all, since, cov))
            log('ecrit %s (%d Ko)' % (path, os.path.getsize(path) // 1024))
    with open(state_path, 'w') as f:
        json.dump(state, f, separators=(',', ':'))
    log('%d photo(s) nouvelle(s), couverture : %s' % (new, {k: sum(v.values()) for k, v in cov.items()}))
    return ok, new


if __name__ == '__main__':
    cid, sec = os.environ.get('BLIZZARD_CLIENT_ID', '').strip(), os.environ.get('BLIZZARD_CLIENT_SECRET', '').strip()
    if not cid or not sec:
        sys.exit('Secrets BLIZZARD_CLIENT_ID / BLIZZARD_CLIENT_SECRET absents (Settings > Secrets and variables > Actions).')
    try:
        tok = token(cid, sec)
    except urllib.error.HTTPError as e:
        sys.exit('Blizzard refuse les identifiants (HTTP %d) : verifie les secrets du depot.' % e.code)
    n, new = run(tok=tok)
    # le workflow ne publie que s'il y a une photo nouvelle (Blizzard en produit une par heure)
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a') as f:
            f.write('changed=%d\n' % (1 if new else 0))
    sys.exit(0 if n else 1)
