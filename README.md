# craftmaster-prix

Prix des hôtels des ventes de **WoW Forever** (Europe), mis à jour toutes les heures depuis l'API officielle de Blizzard, pour l'addon **CraftMaster**.

## Pour les joueurs

Rien à créer : le compagnon de CraftMaster télécharge ces fichiers tout seul.

1. Installe les addons `CraftMaster` et `CraftMaster_Data` dans `_forever_\Interface\AddOns`.
2. Double-clique sur `CraftMaster_Data\Companion\Installer.cmd`, choisis **1 (prix partagés)** et ton type de serveur.
3. En jeu : `/reload`, puis `/craftmaster diag`.

Le compagnon recopie le fichier de ton type de serveur toutes les heures. Fais `/reload` pour voir les nouveaux prix.

## Les fichiers (branche `data`)

| Fichier | Contenu |
|---|---|
| `Data-PvP.lua` | JcJ : HV Alliance (110), Horde (113), commune (116) — **seul type de serveur suivi** |
| `state.json` | L'historique glissant (prix bas par jour, ventes, couverture), repris à chaque passage |
| `prev-110/113/116.json.gz` | Dernière photo complète des annonces, pour détecter les ventes |

Les autres types de serveur (JcE, JdR, JdR-JcJ) ne sont plus collectés et leurs données ont été purgées. Pour en rajouter un : variable `RULESETS` du workflow.

Le fichier contient la dernière photo de chaque HV (prix unitaire le plus bas et quantité par objet), les prix les plus bas des **14 derniers jours** (`KEEP_DAYS` ; tout ce qui est plus vieux est supprimé), la **couverture** (`cov` : combien de photos de l'API ont été reçues chaque jour, pour repérer les trous), l'origine (`src`, `gen` = numéro du passage GitHub) et les **ventes détectées** sur 14 jours. D'une photo à l'autre, chaque annonce garde son numéro et sa tranche de durée restante (WoW Forever propose des ventes de 2, 8 et 24 h, comme Classic : moins de 30 min, 30 min à 2 h, 2 h à 8 h, 8 h à 24 h) ; en croisant les photos, `fetch.py` resserre la fenêtre où elle expire. Disparue après cette fenêtre, elle a expiré ; avant, elle est vendue ou retirée : une commodité (l'achat prend toujours les moins chères) disparue alors que des annonces plus anciennes et moins chères restent a été retirée ; pour un objet, des annonces moins chères restées ou une remise en vente moins chère de la même quantité réduisent le poids de la vente. Une quantité qui baisse est un achat partiel. Pour les objets qui se vendent, le fichier donne aussi les 6 prix les plus bas en vente (`depth`), pour mesurer la concurrence en jeu.

Tests hors ligne, a lancer a la main avant de pousser : `python3 tests/test_fetch.py` (les choix du pipeline) et `python3 tests/test_ventes.py` (ventes, profondeur).

Adresse directe : `https://raw.githubusercontent.com/benetnut34-dotcom/craftmaster-prix/data/Data-PvP.lua`

Les numéros d'HV par type de serveur viennent de relevés de la communauté : l'API ne les donne pas. CraftMaster vérifie en jeu qu'ils correspondent à tes propres scans et te prévient sinon.

## Fonctionnement

- `.github/workflows/prix.yml` lance `fetch.py` **toutes les heures à h32** sur les serveurs de GitHub : aucun PC n'a besoin d'être allumé. Le déclencheur planifié de GitHub (`cron`) est « au mieux » et a raté environ 9 passages sur 10 ici : le workflow **se relance lui-même** (job `relais` : attend la prochaine h32 puis relance le workflow ; un relais plus récent annule l'ancien, donc une seule chaîne). Le `cron` (minutes 12, 32 et 52) ne sert plus que de filet de sécurité, et un `push` sur `fetch.py` ou le workflow relance la chaîne. Blizzard ne publie qu'une photo par heure (vers la 21e minute), et un passage sans photo nouvelle ne publie rien.
- Si la chaîne s'arrête quand même : onglet Actions > Run workflow la relance.
- Un « keep-alive » en fin de passage empêche GitHub de couper la planification après 60 jours d'inactivité.
- On peut aussi le lancer à la demande (onglet Actions > Run workflow).
- Les identifiants de l'API sont des **secrets** (`BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET`), dans l'environnement `prix` limité à la branche `main` (Settings > Environments). Ils n'apparaissent dans aucun fichier. Attention : quiconque peut écrire sur le dépôt peut faire lire ces secrets par un workflow ; on pousse directement sur `main`, il n'y a plus de relecture obligatoire : la confiance entre les deux contributeurs est la seule barrière.
- La branche `data` est remplacée à chaque passage (pas d'historique git), avec `state.json` pour garder les 14 jours ; tout ce qui dépasse est purgé.

## Contribuer

- On pousse directement sur `main`. Avant : `git fetch origin` puis `git pull --ff-only` ; si ça échoue, c'est un conflit : on s'arrête et on en parle, jamais de `push --force`.
- `python3 tests/test_fetch.py` et `python3 tests/test_ventes.py` se lancent à la main : ils protègent les choix du pipeline (serveur PvP seul, 14 jours, relais automatique, format lu par l'addon) et la détection des ventes.
- Voir `CLAUDE.md` pour les consignes détaillées.
