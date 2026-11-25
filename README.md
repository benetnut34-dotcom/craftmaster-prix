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
| `Data-PvP.lua` | JcJ : HV Alliance (110), Horde (113), commune (116) |
| `Data-PvE.lua` | JcE / Normal : 111, 114, 117 |
| `Data-RP.lua` | JdR : 119, 120, 121 |
| `Data-RPvP.lua` | JdR-JcJ : 123, 124, 125 |

Chaque fichier contient la dernière photo de chaque HV (prix unitaire le plus bas et quantité par objet), les prix les plus bas des 14 derniers jours, et les **ventes détectées** sur 14 jours : d'une photo à l'autre, une annonce qui disparaît alors qu'il lui restait plus de 2 h est comptée vendue (un quart seulement si des annonces nettement moins chères restent : plutôt retirée), une quantité qui baisse est un achat partiel, une annonce qui disparaît à moins de 2 h de sa fin a sans doute expiré.

Adresse directe : `https://raw.githubusercontent.com/benetnut34-dotcom/craftmaster-prix/data/Data-PvP.lua`

Les numéros d'HV par type de serveur viennent de relevés de la communauté : l'API ne les donne pas. CraftMaster vérifie en jeu qu'ils correspondent à tes propres scans et te prévient sinon.

## Fonctionnement

- `.github/workflows/prix.yml` lance `fetch.py` à la 17e minute de chaque heure, et aussi à la demande (onglet Actions > Run workflow).
- Les identifiants de l'API sont des **secrets du dépôt** (`BLIZZARD_CLIENT_ID`, `BLIZZARD_CLIENT_SECRET`). Ils ne sont visibles par personne et n'apparaissent dans aucun fichier.
- La branche `data` est remplacée à chaque passage (pas d'historique), avec `state.json` pour garder les 14 jours.
