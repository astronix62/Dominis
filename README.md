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
n’est nécessaire au fonctionnement. Il est utilisé dans la navigation, comme
icône du navigateur et pour le Dock en mode natif macOS lorsque disponible.
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

Cette mise à jour n’ajoute aucune dépendance d’exécution. Les futures versions
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

### Publier une future version (aucune publication effectuée à cette étape)

Dans les **Releases** de `https://github.com/astronix62/Dominis` :

1. Incrémenter `APP_VERSION` dans le script, par exemple `v0.0.2`.
2. Créer une Release stable, publiée (ni brouillon ni préversion), avec exactement
   le même tag, par exemple `v0.0.2`, et la définir comme dernière Release.
3. Joindre **uniquement le fichier de l’application nommé exactement `Dominis.py`**
   dans les fichiers de la Release. Ne pas joindre `data.db`.

Un simple tag Git ou un fichier sur la branche principale ne suffit pas. Le
programme consulte `/releases/latest`, c’est-à-dire la dernière Release stable
selon GitHub, puis compare les nombres de la version (pas l’ordre alphabétique).
Les archives de sources automatiques de GitHub ne sont jamais installées.

### Préparer le test v0.0.0 → v0.0.1

**Une ancienne copie dépourvue du mécanisme de mise à jour ne peut pas se mettre
à jour toute seule.** Il faut d’abord lui fournir manuellement le nouveau
mécanisme, avec une version inférieure à celle qui sera publiée.

L’outil suivant prépare une copie de test équipée du mécanisme et étiquetée
`v0.0.0`, sans toucher au script `v0.0.1` du dépôt ni copier la base personnelle :

```sh
python3 tools/prepare_update_test.py ~/Desktop/Dominis-test
```

Le dossier cible doit être vide et situé hors du dépôt. Ouvrir son lanceur,
créer quelques sociétés et documents fictifs, puis fermer Dominis. Après la
publication ultérieure de la Release `v0.0.1` avec le script du dépôt en pièce
jointe :

1. Ouvrir la copie de test : une mise à jour doit être proposée.
2. Choisir « Plus tard », quitter, puis rouvrir : la proposition doit revenir.
3. Choisir « Mettre à jour » : laisser l’installation et le redémarrage se faire.
4. Vérifier la version `v0.0.1`, les données, préférences et sauvegardes.
5. Quitter puis rouvrir : aucune nouvelle proposition si `v0.0.1` est toujours la
   dernière Release. Le tableau de bord général doit s’ouvrir.

Aucune publication n’est faite par cet outil. Pour tester avec une base existante,
utiliser **une copie de sauvegarde**, jamais la seule copie de données réelles.

### Tests complémentaires

`python -m unittest discover -s tests -v` inclut un vrai remplacement du script
et un vrai redémarrage `v0.0.0 → v0.0.1` dans un dossier temporaire, avec des
réponses GitHub simulées. Le test vérifie notamment que `data.db` reste identique
octet pour octet pendant cette mise à jour et que les sauvegardes existent.
Les échecs de téléchargement, de sauvegarde et de démarrage sont également testés.

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
Les parcours natifs macOS/Windows restent à confirmer sur les machines cibles :
les tests d’installation et de redémarrage automatisés sont exécutés sous Linux.
