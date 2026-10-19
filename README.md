# Dominis

Application locale de gestion patrimoniale multi-SCI, en Python 3.10 ou ultérieur.

## Lancement

Conserver `Dominis.py` et la base personnelle `data.db` dans le même dossier.
Les chemins sont résolus par rapport au script, pas au dossier du terminal.

- **macOS** : double-cliquer sur `Dominis/Lancer_Dominis.command`.
- **Windows** : double-cliquer sur `Dominis/Lancer_Dominis.bat`.
- **Navigateur** : `python3 Dominis/Dominis.py`.

Les lanceurs préparent un environnement `.venv` et installent pywebview pour la
fenêtre native. Une connexion Internet est nécessaire lors de cette installation.
En cas d'échec, le mode navigateur reste disponible.

### Fermeture sur Mac

Utiliser « Quitter l’application », puis « Enregistrer et quitter », ou le bouton
de fermeture de la fenêtre native. Dominis attend les préférences en cours
d’enregistrement, vérifie SQLite et crée la sauvegarde de fermeture si elle est
activée. Une erreur de sauvegarde empêche la fermeture normale.

Après la sortie normale de Python, le lanceur demande à **Terminal d’Apple** de
fermer la fenêtre correspondant à son propre terminal (TTY), à condition qu’elle
ne contienne qu’un onglet. Les autres fenêtres ne sont pas fermées. Une fenêtre
contenant plusieurs onglets reste ouverte par sécurité. iTerm et les terminaux
intégrés à un éditeur ne sont pas pilotés.

macOS peut demander une autorisation d’automatisation pour contrôler Terminal.
Si elle est refusée, les données restent enregistrées mais la fenêtre du terminal
peut rester ouverte. L’autorisation se gère dans Réglages Système → Confidentialité
et sécurité → Automatisation. Autre possibilité : configurer le profil Terminal
pour fermer la fenêtre lorsque le shell se termine normalement.

En cas d’erreur du programme, le lanceur conserve le message à l’écran jusqu’à
l’appui sur Entrée. En mode navigateur, fermer simplement l’onglet n’arrête pas le
serveur : utiliser le bouton « Quitter l’application ».

La fermeture réelle de Terminal, les autorisations et l’icône du Dock sont à
valider sur macOS ; les tests Linux ne peuvent pas les reproduire.

### Copie hebdomadaire dans `auto-save/`

En plus de la base principale `data.db` et de la sauvegarde existante à la
fermeture dans `sauvegardes/`, Dominis peut créer une copie complète au premier
lancement de chaque semaine ISO (lundi–dimanche). Si l’application n’a pas été
lancée le lundi, la copie est créée lors du prochain lancement de cette semaine.
Le réglage **Sauvegarde hebdomadaire** est distinct de **Sauvegarde à la fermeture**.

Les fichiers sont placés dans `auto-save/`, à côté de `data.db`, sous la forme
`AAAA-MM-JJ-save.db` (par exemple `2026-10-14-save.db`). Au troisième fichier,
Dominis supprime la copie datée la plus ancienne et conserve les deux plus
récentes. Les copies sont des instantanés SQLite complets et vérifiés, y compris
les réglages et pièces jointes. Elles sont créées séparément et **ne sont jamais
sélectionnées comme base active** : Dominis continue à ouvrir `data.db`.

Si `data.db` manque alors que des copies sont présentes, Dominis affiche un
avertissement et ne crée pas de copie hebdomadaire de la nouvelle base vide.
Les fichiers `auto-save/` restent des sauvegardes ; une restauration explicite
copie leur contenu dans le fichier principal `data.db`.

## Identité visuelle et compatibilité

Le logo doré est **recadré depuis l’affiche originale `Dominis/Dominis.jpg`**, sans
redessin. Le PNG est intégré à `Dominis.py` : aucun fichier image supplémentaire
n’est nécessaire au fonctionnement. Il est utilisé dans la navigation et comme
icône du navigateur. Le Dock natif macOS utilise un **second PNG RGBA intégré** :
tuile à coins arrondis, contours anticrénelés et marge transparente sur un canevas
512 × 512. Le logo du site reste inchangé ; Pillow n'est pas requis à l'exécution.
L’affiche originale n’est pas modifiée.

Pour régénérer le logo intégré (outil de développement uniquement) : installer
Pillow, puis exécuter `python tools/embed_logo.py`.

Les nouveaux exports portent le nom Dominis. Les anciens exports JSON Auréa au
format version 1 restent importables ; les sauvegardes SQLite existantes restent
compatibles. Le numéro de format de données n’est pas un numéro de version de
l’application. Aucun changement de schéma ni remplacement de `data.db` n’est
nécessaire pour le changement de nom.

## Import de données

Paramètres → **Importer** accepte trois formats, avec aperçu des sources, des
destinations et des contrôles avant toute écriture :

- **JSON Dominis** (ou ancien export Auréa v1) : fiches SCI et enregistrements
  complets, réimportables à l’identique.
- **CSV** : mouvements de trésorerie `date;label;direction;category;amount`,
  colonne facultative « sci » pour le regroupement multi-sociétés.
- **Excel (.xlsx)** : lecture native du format, sans dépendance supplémentaire.

### Tableaux Excel pris en charge

Un même classeur peut contenir **plusieurs tableaux**, sur une ou plusieurs
feuilles, volumineux ou non, au format :

```
Date | Libellé | Débit | Crédit | Solde
```

- Les titres placés au-dessus de chaque en-tête (nom de la SCI, banque, année)
  regroupent les mouvements par source ; un tableau sans titre rejoint le groupe
  précédent de la même feuille, sinon il reçoit un nom dédié.
- Les lignes **avec libellé** deviennent des opérations : la colonne **Débit**
  est une **Dépense**, la colonne **Crédit** est une **Recette** ; un montant
  négatif est inversé et signalé.
- Les lignes **sans libellé** (solde d’ouverture, clôtures mensuelles, lignes de
  totaux) ne sont pas importées : elles servent de **contrôles de cohérence**.
  Chaque écart entre le solde attendu et le solde trouvé, ou entre les totaux
  annoncés et les mouvements calculés, est listé dans l’aperçu avant validation.
- Dates françaises JJ/MM/AA(A) et ISO, séries et formats de date Excel natives ;
  montants français (`32 155,66 €`, espaces insécables, virgule décimale,
  parenthèses négatives) et cellules numériques.
- En-têtes reconnus même avec variantes (casse, accents, « Débit (€) »,
  colonnes supplémentaires ignorées ; en-tête répété au milieu d’un tableau
  accepté). Une ligne de données sans en-tête, une date ou un montant illisible
  provoquent une erreur explicite indiquant la feuille et la ligne : aucune
  donnée n’est perdue silencieusement.
- À la création d’une nouvelle SCI depuis un titre de tableau, le premier solde
  du fichier devient le solde d’ouverture. Vers une SCI existante, rien n’est
  écrasé. Limite : 200 000 opérations par import ; un même fichier vers les
  mêmes destinations est refusé.

## Filtres, dossiers et aperçu des documents

- **Photo d’un bien** : dans la fiche d’un bien, une image peut être importée et
  **recadrée librement** (glisser, zoom, recentrer, flèches du clavier). Le format
  pris en compte est affiché et appliqué à l’enregistrement : **16:5, 1600 × 500 px**.
  La carte du bien reprend exactement ce cadrage. **Sans photo, la carte garde
  son apparence d’origine** ; retirer la photo y revient.
- **Dossiers de documents propres à chaque SCI** : chaque société possède sa
  propre liste de dossiers. **Créer, renommer, supprimer ou réordonner** un
  dossier ne modifie jamais une autre SCI. Les six dossiers proposés par défaut
  peuvent être renommés ou supprimés société par société ; le bouton
  **« Dossiers par défaut »** de la page Documents rétablit ceux qui manquent.
  Les dossiers se rangent avec les flèches de chaque carte (ou dans la fenêtre
  « Modifier le dossier », qui propose aussi la suppression). La carte
  **« Tous les documents » reste toujours à droite**. Un document sans dossier
  est rangé automatiquement selon sa catégorie (statuts, baux, comptabilité,
  assurances, diagnostics) ; supprimer un dossier ne supprime aucun document.
  Sur la page Documents de toutes les SCI, la barre affiche l’union des dossiers
  et les compteurs suivent le filtre **Société**.
- **Aperçu d’un document** : un clic sur la ligne ouvre l’aperçu avec un **zoom
  réglable, par défaut ×1** (document entier visible) : images, PDF, classeurs
  Excel (un onglet par feuille), CSV, texte et Word. Un document sans pièce
  jointe l’indique explicitement. L’aperçu est servi par `/api/document-view`
  avec le **MIME exact** et `Content-Disposition: inline`, ce qui affiche le
  document au lieu de le télécharger (page blanche et téléchargement forcé sur
  macOS corrigés). Le bouton **Télécharger** passe toujours par
  `/api/document`, qui reste en `attachment`. L’HTML et le SVG ne sont jamais
  rendus en ligne : un fichier importé ne peut pas exécuter de script dans
  l’origine qui porte le jeton de session.
- **Filtre d’année global** : un seul état d’année pour toute l’application,
  avec l’option **« Toutes les années »** plus chaque année disponible. Il
  filtre réellement la liste de trésorerie (et les appels de loyers), pas
  seulement les indicateurs : la vue d’ensemble et le tableau affichent donc les
  mêmes mouvements. Quand plusieurs filtres d’année sont visibles sur une même
  page (en-tête de SCI + barre d’outils de la trésorerie), **modifier l’un met
  l’autre à jour immédiatement**. Après un import couvrant plusieurs exercices,
  le filtre bascule sur « Toutes les années » pour que les données importées
  soient visibles partout. Les échéances ne sont pas filtrées par année : une
  tâche en retard d’un exercice précédent reste visible.
- **Synchronisation après chaque écriture** : ajout, modification, suppression,
  classement d’un document, changement de dossier, appel de loyers, import,
  restauration et réglages rechargent l’état complet depuis `data.db`
  (`/api/state`) avant de réafficher l’interface. Aucune vue ne peut rester
  décalée de la base, y compris après un redémarrage.
- **Limites larges** : pièce jointe jusqu’à **500 Mo**, import jusqu’à **500 Mo**,
  restauration jusqu’à **500 Mo**, jusqu’à **30 rappels** datés par échéance
  (365 acceptés par la base).
- **Interrupteurs identiques quelle que soit la longueur du texte** : un
  interrupteur (notifications style macOS, rappels, réglages) ne peut plus être
  écrasé par sa propre description. Le texte absorbe la largeur disponible et
  l’interrupteur conserve exactement ses **41 × 23 px** ; auparavant, une
  description longue comprimait le bouton jusqu’à environ 17 px de large alors
  qu’une description courte l’affichait correctement.

## Vérifications

```sh
python -m unittest discover -s tests -v
python -m py_compile Dominis/Dominis.py
bash -n Dominis/Lancer_Dominis.command
```

Les tests utilisent exclusivement des bases temporaires. Pour un aperçu avec des
données fictives, sans toucher à la base personnelle :

```sh
python Dominis/Dominis.py --preview --demo --host 0.0.0.0 --no-browser --db .cache/preview.db
```

Le mode aperçu accepte les hôtes du proxy et doit rester limité aux environnements
de démonstration avec des données fictives. En usage personnel, conserver l’écoute
locale par défaut.

## Mises à jour intégrées — v0.0.5

La version est déclarée dans `Dominis.py` par `APP_VERSION = 'v0.0.5'` et affichée
sous **Paramètres → Version**, avec les mêmes panneaux et thèmes que le reste de
l’application. Chaque ouverture affiche le **tableau de bord général de toutes
les SCI**, indépendamment de la dernière page consultée.

### Comportement

- Vérification en arrière-plan à chaque lancement auprès de l’API publique
  GitHub, sans transmission des données patrimoniales.
- Si une version stable plus récente existe : proposition **« Mettre à jour » /
  « Plus tard »**. Le report dure jusqu’à la fin du processus, pas au-delà : la
  proposition revient au prochain lancement. Fermer la proposition avec la croix
  ou Échap a le même effet que « Plus tard ».
- Si la version est identique ou plus ancienne : aucune notification spontanée.
- Sans réseau, en cas de limite GitHub, de Release invalide ou inaccessible :
  aucune fenêtre intempestive. L’état « Vérification impossible » et son motif
  apparaissent dans l’onglet Version. Ne pas confondre cet état avec « À jour ».
- « Vérifier maintenant » permet une nouvelle vérification ; une mise à jour
  reportée peut toujours être lancée depuis l’onglet Version.
- Les installations sont désactivées en mode `--preview`, y compris forcées.

### Forcer la mise à jour

Le bouton **« Forcer la mise à jour »** de l’onglet Version installe la dernière
Release stable **quelle que soit sa version**, y compris identique ou plus
ancienne que celle installée. Il prépare la Release, puis ouvre toujours une
fenêtre de confirmation avant d’écrire quoi que ce soit :

| Release trouvée | Fenêtre ouverte | Libellé de confirmation |
| --- | --- | --- |
| plus récente | « Forcer la mise à jour » | « Installer maintenant » |
| identique | « Réinstaller la même version ? » | « Réinstaller cette version » |
| plus ancienne | **« Avertissement : retour à une version antérieure »**, encadré rouge et bouton en style danger | « Je comprends, forcer le retour arrière » |

La ligne « Dernière Release vérifiée » affiche la relation détectée (plus
récente, identique, plus ancienne) et teinte la pastille en conséquence. Les
mêmes contrôles d’intégrité, la même sauvegarde obligatoire de `data.db` et le
même retour arrière automatique en cas d’échec du démarrage s’appliquent ; le
forçage ne contourne que la comparaison de version, jamais la validation du
fichier. Sans Release préparée, l’installation forcée est refusée. Si une
vérification est déjà en cours, la demande de forçage est mémorisée et rejouée
par la vérification en cours plutôt que perdue.

### Installation et redémarrage

1. Télécharger uniquement le fichier joint `Dominis.py`, via HTTPS, depuis la
   Release officielle. Limite de taille et délais réseau ; redirections limitées
   aux hôtes GitHub de téléchargement.
2. Vérifier la taille, l’empreinte SHA-256 **si GitHub la fournit**, la syntaxe
   Python, la correspondance entre `APP_VERSION` et le tag, la version minimale
   de Python et les marqueurs de compatibilité. Le code n’est pas exécuté lors
   de cette validation.
3. Suspendre les nouvelles écritures, vérifier SQLite et créer obligatoirement
   une sauvegarde complète dans `sauvegardes/`, même si la sauvegarde habituelle
   à la fermeture est désactivée. Tout échec annule l’installation.
4. Fermer proprement la fenêtre et le serveur, puis remplacer atomiquement
   `Dominis.py` avec le fichier temporaire situé sur le même disque. **Ne jamais
   télécharger, remplacer, effacer ou recréer `data.db` dans l’installateur.**
5. Relancer avec le même Python, la même base (chemin absolu), le même port et le
   même mode de fenêtre. Le superviseur garde le contrôle jusqu’à l’accusé de
   démarrage et peut restaurer le script précédent en cas d’échec. Sur macOS en
   fenêtre native, l’enfant est détaché du Terminal et le processus graphique
   précédent se termine après confirmation, afin de ne pas laisser une ancienne
   instance dans le Dock. Sur les autres modes, le comportement du lanceur est
   conservé.
6. Attendre l’accusé de démarrage de la nouvelle version (60 secondes maximum).
   En cas d’échec, rétablir le script précédent et le relancer. En cas de succès,
   supprimer les fichiers temporaires : il ne reste qu’un seul `Dominis.py`.
   La nouvelle interface indique **« Mise à jour réussie »** et ouvre le tableau
   de bord général. En mode navigateur, l’onglet existant se recharge tout seul.

Le dossier `.dominis-update-*` est temporaire et privé. Après une interruption
brutale ou si le disque empêche la récupération, des fichiers `.tmp` peuvent y
rester pour permettre une récupération manuelle ; le terminal indique le chemin
en cas d’échec de restauration. Ne pas supprimer `data.db`. Le fichier de verrou
`.dominis-instance.lock` empêche deux instances locales du même dossier de
fonctionner simultanément. Il peut rester présent après fermeture : c’est le
verrou système, et non sa présence, qui indique si l’application est ouverte.

Cette mise à jour n’ajoute aucune dépendance d’exécution. Un magasin de certificats
Mozilla est intégré au script, en complément des certificats système, pour les
installations Python/macOS dont le magasin racine n'a pas été initialisé. Le même
contexte HTTPS vérifié est utilisé sous Windows, macOS et Linux, pour l'API et
pour le téléchargement. La validation de la chaîne et du nom d'hôte n'est jamais
désactivée. Aucun téléchargement de certificat ni appel à pip au démarrage.

Les futures versions
nécessitant un changement de schéma SQLite, de dépendances ou de lanceurs devront
prévoir une procédure adaptée. Les marqueurs à conserver dans le script sont :

```python
APP_VERSION = 'v0.0.5'  # À incrémenter pour chaque nouvelle Release.
UPDATE_PROTOCOL = 1
DB_SCHEMA_VERSION = 1
MIN_PYTHON = (3, 10)
```

Les contrôles reposent sur la confiance dans le dépôt officiel et dans HTTPS.
L’empreinte GitHub n’est pas une signature indépendante de l’éditeur. Protéger
l’accès au compte et au dépôt qui publient le code. Les Releases doivent être
publiquement accessibles ; aucun secret GitHub n’est embarqué.

### Préparer un scénario de mise à jour vers v0.0.5

Le fichier principal `Dominis/Dominis.py` est déclaré en **v0.0.5**. L’outil de
test copie le code actuel en ne changeant que `APP_VERSION`, pour obtenir une
copie isolée en v0.0.0. Le fichier principal, `data.db` et les sauvegardes restent
inchangés ; aucune donnée personnelle n’est copiée.

#### 1. Publier et vérifier la Release v0.0.5 avant un test réel

Une pull request fusionnée ne met pas à jour les pièces jointes d’une Release.
Avant un test réel, la dernière Release stable doit donc être **v0.0.5** et
contenir exactement le fichier corrigé `Dominis.py` correspondant au tag.

1. Publier la Release stable **v0.0.5** sur le dépôt officiel, sans brouillon ni
   préversion, et la définir comme « latest ».
2. Joindre `Dominis/Dominis.py` avec le nom exact `Dominis.py`. Ne pas joindre la
   copie de test v0.0.0, `data.db`, les dossiers `auto-save/` ou `sauvegardes/`,
   ni un ZIP à la place de cet asset.
3. Exécuter le contrôle `--check-release` ci-dessous. Il vérifie que les octets
   réellement publiés correspondent au script local et à la version v0.0.5.

L’outil de préparation ne publie rien et ne modifie pas les Releases. Pour toute
version ultérieure, incrémenter `APP_VERSION`, créer une Release portant le même
tag et joindre le script correspondant.
#### 2. Créer le dossier Dominis de test

Depuis le dossier du dépôt, sur macOS :

```sh
python3 tools/prepare_update_test.py --check-release
```

Sur Windows (PowerShell ou Invite de commandes) :

```powershell
py -3 tools/prepare_update_test.py --check-release
```

Sans chemin explicite, le dossier créé est **`~/Dominis-test/Dominis`** (dans le
dossier utilisateur, également sous Windows). Le contrôle `--check-release`
vérifie le tag, la présence de l'asset, la taille, l'empreinte si disponible,
puis télécharge le script avec les mêmes protections HTTPS que l'application.
Il exige une **égalité octet pour octet** avec le script local. En cas d'erreur ou
de différence, il s'arrête **avant de créer la copie** et indique le problème.

Pour préparer simplement la copie sans réseau, omettre `--check-release` :

```sh
python3 tools/prepare_update_test.py
```

Dans ce mode, la préparation fonctionne hors ligne, mais un avertissement précise
que la Release n'a pas été vérifiée. On peut choisir un autre dossier final :

```sh
python3 tools/prepare_update_test.py ~/Desktop/Test-Dominis/Dominis --check-release
```

Le dossier final doit être vide et hors du dépôt. L'outil refuse de remplacer un
dossier non vide, y compris une copie de test déjà utilisée. Pour recommencer,
choisir un nouvel emplacement plutôt que risquer d'effacer des données.

Le dossier contient :

- `Dominis.py` : code actuel avec **seulement** `APP_VERSION = 'v0.0.0'` ;
- `Lancer_Dominis.command` et `Lancer_Dominis.bat` : lanceurs actuels inchangés ;
- `Dominis.jpg` : affiche originale inchangée (les icônes sont déjà dans le script).

**Ni `data.db`, ni les dossiers `sauvegardes/` ou `auto-save/`, ni `.venv` personnels ne sont copiés.** Au premier
lancement, une base vide sera créée dans le dossier de test. Le lanceur prépare
son environnement natif habituel (Python 3.10+ installé, accès Internet pour
installer pywebview). Aucun paquet supplémentaire n'est nécessaire au correctif TLS.

#### 3. Effectuer le test

1. Fermer toute autre instance Dominis pour libérer le port 8765.
2. Ouvrir le lanceur du **dossier de test** : `.command` sur Mac, `.bat` sur Windows.
3. Vérifier que la version installée est v0.0.0 et que **v0.0.5 est proposée**.
4. Choisir « Plus tard », créer quelques sociétés/documents fictifs, puis quitter.
5. Rouvrir : la proposition doit revenir. Choisir « Mettre à jour ».
6. Attendre le redémarrage automatique et le message de réussite. Vérifier la
   version v0.0.5, les données, les préférences, les sauvegardes et l'icône du Dock.
7. Quitter et rouvrir : aucune nouvelle proposition si v0.0.5 reste la dernière
   Release ; « Vérifier maintenant » doit afficher « À jour » sans erreur SSL.

Ne pas utiliser la seule copie de ses données réelles pour un test de mise à jour.
Une simulation automatisée de ce scénario, ainsi que d'une future mise à jour
v0.0.1 → v0.0.2, fait partie des tests ci-dessous.

### Débloquer une ancienne installation affectée par l'erreur SSL

Une ancienne copie dépourvue du correctif, bloquée par
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`, ne peut pas
télécharger son propre correctif. **La copie produite par l'outil ci-dessus n'a
pas cette limitation : elle contient déjà le correctif, avec le numéro v0.0.0.**

Pour une ancienne installation réelle, quitter complètement Dominis, sauvegarder
son dossier, puis remplacer **uniquement `Dominis.py`** par le script corrigé.
Ne pas remplacer `data.db` ni supprimer ses sauvegardes ou son environnement.
Relancer avec le lanceur habituel, puis vérifier la version et la connexion.

Si l'erreur SSL persiste avec le correctif, vérifier l'horloge et les certificats
d'un éventuel proxy/antivirus qui intercepte HTTPS. Les CA privées d'un réseau
doivent être correctement configurées pour Python par l'administrateur ; elles
ne sont pas incluses dans Mozilla. Ne jamais contourner le problème avec
`CERT_NONE`, un contexte non vérifié ou une désactivation globale de HTTPS.

### Tests complémentaires

`python -m unittest discover -s tests -v` inclut un vrai remplacement du script
et un vrai redémarrage `v0.0.0 → v0.0.1` et `v0.0.1 → v0.0.2` dans un dossier temporaire, avec des
réponses GitHub simulées. Les tests vérifient notamment que `data.db` reste identique
octet pour octet pendant cette mise à jour et que les sauvegardes existent.
Les échecs de téléchargement, de sauvegarde et de démarrage sont également testés.
Le parcours v0.0.0 commence par une vraie exécution de `prepare_update_test.py` et
vérifie l'identité des fichiers avant de simuler le transport GitHub. Les deux
parcours vérifient aussi l'absence de nouvelle proposition après installation et
après une nouvelle fermeture/réouverture. Les tests de préparation couvrent une
ancienne pièce jointe, un tag incorrect, un téléchargement différent, l'absence
d'empreinte GitHub, les erreurs réseau et la protection des dossiers existants.

Contrôles navigateur facultatifs (installer Playwright et son Chromium dans un
environnement de développement, pas dans l’application distribuée) :

```sh
# Avec le serveur --preview et la base fictive décrits plus haut :
python tests/check_update_ui.py
# Démarre ses propres copies temporaires, sans toucher au dépôt ni à ses données :
python tests/check_upgrade_browser.py
```

`CHROMIUM_PATH` peut préciser un exécutable Chromium existant ;
`DOMINIS_TEST_URL` peut préciser l’URL du serveur d’aperçu pour le premier test.
Les captures de contrôle sont enregistrées dans `.cache/`, ignoré par Git.
La matrice `.github/workflows/tests.yml` exécute les tests sous **Windows, macOS
et Linux**, avec Python **3.10 et 3.13**, à chaque push et pull request. Elle
compile le script et teste notamment les sauvegardes, TLS, remplacements,
redémarrages et restaurations. Avant de publier v0.0.5, les six jobs de la matrice
doivent être verts. Ils ne remplacent pas la validation visuelle de la fenêtre et
du Dock sur macOS ; le scénario de mise à jour native doit aussi être vérifié sur
une machine Mac cible.

Pour exécuter aussi les tests TLS locaux et les contrôles des pixels de l'icône :

```sh
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

### Entretenir le magasin de certificats intégré

Avant les prochaines publications, vérifier les mises à jour de certifi/Mozilla.
Les certificats doivent évoluer avec les autorités publiques : aucun magasin
figé ne peut garantir HTTPS indéfiniment. Dans un environnement de développement :

```sh
python -m pip install --upgrade certifi
python tools/embed_certificates.py
python -m unittest discover -s tests -v
```

Mettre à jour la version fixée dans `requirements-dev.txt` et la provenance dans
`THIRD_PARTY_NOTICES.md` si certifi change. L'outil intègre le PEM compressé, sa
version, son empreinte et la notice de licence. Aucune installation de certifi
n'est demandée aux utilisateurs de l'application.
