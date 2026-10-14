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

## Mises à jour intégrées — v0.0.1

La version est déclarée dans `Dominis.py` par `APP_VERSION = 'v0.0.1'` et affichée
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
- Si la version est identique ou plus ancienne : aucune notification.
- Sans réseau, en cas de limite GitHub, de Release invalide ou inaccessible :
  aucune fenêtre intempestive. L’état « Vérification impossible » et son motif
  apparaissent dans l’onglet Version. Ne pas confondre cet état avec « À jour ».
- « Vérifier maintenant » permet une nouvelle vérification ; une mise à jour
  reportée peut toujours être lancée depuis l’onglet Version.
- Les installations sont désactivées en mode `--preview`.

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
   même mode de fenêtre. Le processus précédent surveille le redémarrage et
   garde le lanceur Terminal actif jusqu’à la fermeture de la nouvelle instance.
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
APP_VERSION = 'v0.0.1'  # À incrémenter pour chaque nouvelle Release.
UPDATE_PROTOCOL = 1
DB_SCHEMA_VERSION = 1
MIN_PYTHON = (3, 10)
```

Les contrôles reposent sur la confiance dans le dépôt officiel et dans HTTPS.
L’empreinte GitHub n’est pas une signature indépendante de l’éditeur. Protéger
l’accès au compte et au dépôt qui publient le code. Les Releases doivent être
publiquement accessibles ; aucun secret GitHub n’est embarqué.

### Préparer le scénario demandé : v0.0.0 → v0.0.1

Le fichier principal `Dominis/Dominis.py` est **v0.0.1**, avec les correctifs TLS
et l'icône du Dock arrondie. L'outil de test copie exactement ce code en changeant
**uniquement la déclaration `APP_VERSION` en `v0.0.0`**. Le fichier principal reste
inchangé ; les certificats et l'icône sont donc déjà corrigés dans la copie de test.

#### 1. Actualiser la pièce jointe de la Release avant le test réel

**Une pull request, même fusionnée, ne modifie pas les fichiers joints d'une
Release déjà publiée.** La Release v0.0.1 initiale contient encore l'ancien code.
Si sa pièce jointe n'est pas remplacée, la copie v0.0.0 téléchargera ce vieux code
et perdra les correctifs après redémarrage.

Lorsque le code aura été validé et intégré :

1. Dans `https://github.com/astronix62/Dominis/releases`, éditer la Release stable
   **v0.0.1**, publiée, non brouillon, non préversion et définie comme « latest ».
2. Remplacer sa pièce jointe `Dominis.py` par **`Dominis/Dominis.py` du dépôt
   corrigé**, déclaré en v0.0.1. Ne pas joindre la copie v0.0.0, `data.db`, ni un ZIP.
3. Garder exactement le nom `Dominis.py`. Le numéro dans le code et le tag doivent
   être identiques. Une archive de sources automatique ne remplace pas cet asset.
4. Exécuter le contrôle ci-dessous pour vérifier le fichier réellement distribué.

Aucune publication, modification de Release ou pull request n'est effectuée par
l'outil. Le remplacement de l'asset v0.0.1 est ici spécifique à ce scénario initial.
Pour les vraies mises à jour suivantes, **incrémenter la version** (v0.0.2, etc.)
et publier une nouvelle Release : deux fichiers différents étiquetés v0.0.1 ne
sont pas distingués par la comparaison de versions des clients déjà en v0.0.1.

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

**Ni `data.db`, ni sauvegardes, ni `.venv` personnels ne sont copiés.** Au premier
lancement, une base vide sera créée dans le dossier de test. Le lanceur prépare
son environnement natif habituel (Python 3.10+ installé, accès Internet pour
installer pywebview). Aucun paquet supplémentaire n'est nécessaire au correctif TLS.

#### 3. Effectuer le test

1. Fermer toute autre instance Dominis pour libérer le port 8765.
2. Ouvrir le lanceur du **dossier de test** : `.command` sur Mac, `.bat` sur Windows.
3. Vérifier que la version installée est v0.0.0 et que **v0.0.1 est proposée**.
4. Choisir « Plus tard », créer quelques sociétés/documents fictifs, puis quitter.
5. Rouvrir : la proposition doit revenir. Choisir « Mettre à jour ».
6. Attendre le redémarrage automatique et le message de réussite. Vérifier la
   version v0.0.1, les données, les préférences, la sauvegarde et l'icône du Dock.
7. Quitter et rouvrir : aucune nouvelle proposition si v0.0.1 reste la dernière
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
et Linux**, avec Python **3.10 et 3.13**, lors des push et pull requests. Elle
installe les dépendances de test, vérifie TLS et exécute le remplacement réel du
script avec redémarrage et restauration. Elle ne remplace pas le contrôle visuel
du Dock ni les parcours de fenêtre native sur les machines cibles. Lors du
développement de ce correctif, les tests ont été exécutés localement sous Linux ;
les résultats de la matrice native restent à obtenir après envoi sur GitHub.

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
