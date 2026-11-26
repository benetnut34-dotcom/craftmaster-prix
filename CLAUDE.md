# craftmaster-prix : consignes pour Claude

Ce depot collecte, toutes les heures et sans aucun PC allume, les prix de l'hotel des ventes de WoW Forever (serveur JcJ / PvP) depuis l'API Blizzard, et les publie sur la branche `data` pour l'addon **CraftMaster** (depot `benetnut34-dotcom/CraftMaster`). **La donnee est le nerf de la guerre** : un changement ici touche tous les joueurs. Reponds en francais.

## Ce qui ne doit JAMAIS changer sans que le proprietaire l'ait decide
Les tests de `tests/test_fetch.py` les protegent (a lancer avant toute pull request : `python3 tests/test_fetch.py`).
- **Serveur JcJ (PvP) seulement** (`RULESETS`), 3 HV : 110, 113, 116.
- **14 jours** glissants (`KEEP_DAYS`) ; tout ce qui est plus vieux ou d'un autre serveur est purge. L'addon est calibre sur 14 jours.
- **Le workflow se relance lui-meme** (job `relais`) : le cron de GitHub rate environ 9 passages sur 10. On ne supprime ni `relais`, ni `workflow_dispatch`, ni le `push` sur `fetch.py` / `prix.yml`.
- **On ne publie que s'il y a une photo nouvelle** (`changed == '1'`), et la branche `data` est remplacee sans historique git (`push --force` vers `data` SEULEMENT, jamais vers `main`).
- **Le format de `Data-PvP.lua`** est lu par l'addon (`Import.lua`, page Donnees) : en-tete `CraftMasterData = { v = 1, ...`, par HV `id`, `at`, `cov`, `items` (`id:prix:quantite;`), `lows`, `sales`. On peut ajouter des champs, jamais en retirer ni changer le sens d'un existant.
- Les secrets `BLIZZARD_CLIENT_ID` et `BLIZZARD_CLIENT_SECRET` ne sont jamais ecrits dans un fichier, un journal ou une commande. Le job de collecte utilise l'environnement `prix`.
- **La donnee d'abord** : une optimisation n'enleve ni objet, ni annonce, ni jour d'historique ; elle etale, compacte ou accelere, et un test prouve que le resultat est identique.

## Methode (collaboration a deux : pas d'ecrasement, alerte en cas de conflit)
1. `git fetch origin` puis `git status`. Si `origin/main` a avance : `git pull --ff-only`. Si ca echoue (historiques divergents), **arrete-toi et dis-le clairement a ton utilisateur : « CONFLIT : main a avance », sans rien resoudre toi-meme sans son accord**.
2. **Jamais de commit direct sur `main`, jamais de `git push --force` sur `main`** (ni `reset --hard`, ni `checkout -f`, ni `clean`). On travaille sur une branche (`git switch -c nom-court`) et on ouvre une **pull request** ; le proprietaire la relit (CODEOWNERS) et la fusionne.
3. Avant d'ouvrir ou de mettre a jour une PR : `git fetch origin && git rebase origin/main` (ou `merge`), relancer les tests. En cas de conflit de rebase : liste les fichiers a ton utilisateur, garde **les deux** changements quand c'est possible, et demande-lui pour `fetch.py` et `.github/workflows/prix.yml`. Pousse ensuite avec `git push --force-with-lease origin <ta-branche>` (uniquement ta branche).
4. Si GitHub ou le workflow « Alerte conflits » signale un conflit sur ta PR (commentaire, etiquette `conflit`, mail), **dis-le tout de suite a ton utilisateur** et applique l'etape 3.
5. Decris dans la PR ce qui change et pourquoi, avec les chiffres avant / apres si c'est une optimisation. Un test qui echoue parce qu'un choix change volontairement (par exemple `KEEP_DAYS`) se met a jour dans la meme PR, avec l'explication.
6. Apres la fusion, regarde le passage dans l'onglet Actions : il doit rester vert et la branche `data` doit se mettre a jour.

## Fichiers
- `fetch.py` : collecte, etat (`state.json` : prix bas par jour, ventes, couverture), purge, ecriture de `Data-PvP.lua`.
- `.github/workflows/prix.yml` : le passage horaire + `relais` (se relance lui-meme).
- `.github/workflows/garde-fous.yml` (tests) et `conflits.yml` (alerte de conflit sur les PR).
- `tests/test_fetch.py` : les garde-fous.
