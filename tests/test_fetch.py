"""Garde-fous du pipeline des prix : ce que l'addon CraftMaster attend, et les choix qu'on a faits.

    python3 tests/test_fetch.py

Si un de ces tests echoue apres un changement VOLONTAIRE (par exemple passer a 30 jours),
on met le test a jour dans la meme modification, en le disant dans la description de la
pull request : c'est le but, que rien ne change sans que ce soit voulu.
"""
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.pop('RULESETS', None)
os.environ.pop('KEEP_DAYS', None)
import fetch  # noqa: E402


def read(path):
    with open(os.path.join(ROOT, path), encoding='utf-8') as f:
        return f.read()


class Choices(unittest.TestCase):
    def test_pvp_only_by_default(self):
        self.assertEqual(fetch.RULESETS, ['PvP'], 'seul le serveur JcJ (PvP) est collecte')

    def test_fourteen_days(self):
        self.assertEqual(fetch.KEEP_DAYS, 14, "l'addon est calibre sur 14 jours (prix habituel, ventes)")

    def test_pvp_houses(self):
        self.assertEqual(fetch.HOUSES['PvP'], (110, 113, 116))

    def test_workflow_keeps_its_guarantees(self):
        wf = read('.github/workflows/prix.yml')
        self.assertIn('environment: prix', wf, 'les secrets Blizzard ne sont lus que par la branche main (environnement prix)')
        self.assertIn('RULESETS: PvP', wf)
        self.assertIn('KEEP_DAYS: 14', wf)
        self.assertIn('workflow_dispatch', wf, 'le bouton Run workflow et le relais en dependent')
        self.assertRegex(wf, r'(?m)^  relais:', "le job 'relais' relance le workflow : le cron de GitHub rate ~9 passages sur 10")
        self.assertIn('gh workflow run prix.yml', wf)
        self.assertIn("changed == '1'", wf, 'on ne publie que quand Blizzard a une photo nouvelle')
        self.assertRegex(wf, r"push -q --force .*data", 'la branche data est remplacee sans historique')


class Pipeline(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        fetch.OUT = self.tmp
        self.t0 = int(time.time())
        self.calls = 0

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def fake(self, rs, hid, tok):
        items = {2589 + i: (100 + i, 5) for i in range(50)}
        listings = {str(i): (2589 + i, 5, 100 + i, 3) for i in range(50)}
        return items, self.t0 + self.calls * 3600, listings

    def run_once(self):
        self.calls += 1
        return fetch.run(fetch=self.fake, tok='x', state_path=os.path.join(self.tmp, 'state.json'))

    def test_format_read_by_the_addon(self):
        self.run_once()
        lua = open(os.path.join(self.tmp, 'Data-PvP.lua'), encoding='utf-8').read()
        self.assertTrue(lua.split('\n')[1].startswith('CraftMasterData = { v = 1,'), 'en-tete lu par Import.lua')
        for key in ('PvP-Alliance', 'PvP-Horde', 'PvP-Neutral'):
            self.assertIn('["%s"] = { id = ' % key, lua)
        for field in ('items = "', 'lows = "', 'sales = "', 'cov = "', 'keep = 14', 'src = "'):
            self.assertIn(field, lua, 'champ attendu par la page Donnees / Import : ' + field)
        self.assertRegex(lua, r'items = "(\d+:\d+:\d+;)+"', 'format id:prix:quantite;')

    def test_other_server_types_are_purged(self):
        for name in ('Data-PvE.lua', 'Data-RP.lua', 'prev-111.json.gz', 'prev-119.json.gz'):
            open(os.path.join(self.tmp, name), 'w').write('x')
        state = {'lows': {'PvE-Horde': {'1': {'20000': 5}}}, 'snap': {'RP-Horde': {'id': 120, 'at': 1, 'items': {}}},
                 'sales': {}, 'since': {}, 'cov': {'PvE-Horde': {'20000': 2}}}
        json.dump(state, open(os.path.join(self.tmp, 'state.json'), 'w'))
        self.run_once()
        left = sorted(os.listdir(self.tmp))
        self.assertEqual(left, ['Data-PvP.lua', 'prev-110.json.gz', 'prev-113.json.gz', 'prev-116.json.gz', 'state.json'])
        st = json.load(open(os.path.join(self.tmp, 'state.json')))
        for table in ('lows', 'snap', 'sales', 'since', 'cov'):
            self.assertTrue(all(k.startswith('PvP-') for k in st[table]), table + ' ne garde que le PvP')

    def test_coverage_counts_new_pictures_only(self):
        ok, new = self.run_once()
        self.assertEqual((ok, new), (3, 3))
        self.run_once()
        st = json.load(open(os.path.join(self.tmp, 'state.json')))
        day = str(self.t0 // 86400)
        total = sum(sum(v.values()) for v in st['cov'].values())
        self.assertEqual(total, 6, 'deux photos par HV, comptees une fois chacune')
        # the same picture again: nothing new, nothing to publish
        self.calls -= 1
        ok, new = self.run_once()
        self.assertEqual(new, 0)

    def test_old_days_are_dropped(self):
        old = str(self.t0 // 86400 - 20)
        state = {'lows': {'PvP-Horde': {'2589': {old: 90}}}, 'snap': {}, 'sales': {}, 'since': {}, 'cov': {'PvP-Horde': {old: 3}}}
        json.dump(state, open(os.path.join(self.tmp, 'state.json'), 'w'))
        self.run_once()
        st = json.load(open(os.path.join(self.tmp, 'state.json')))
        self.assertNotIn(old, st['lows'].get('PvP-Horde', {}).get('2589', {}))
        self.assertNotIn(old, st['cov']['PvP-Horde'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
