# Composants tiers intégrés

## Autorités de certification Mozilla / certifi

`Dominis/Dominis.py` contient une copie **non modifiée** du fichier `cacert.pem`
distribué avec **certifi 2026.7.22** (version Python déclarée : `2026.07.22`).
Elle est simplement compressée avec gzip et encodée en base64, entre les marqueurs
`BEGIN EMBEDDED CERTIFICATES` et `END EMBEDDED CERTIFICATES`.
Ce sont des certificats publics d'autorités racines, pas des clés privées.

- Projet : https://github.com/certifi/python-certifi
- Distribution source exacte : https://pypi.org/project/certifi/2026.7.22/#files
- Licence : **Mozilla Public License 2.0**, notice fournie par certifi reproduite
  dans [`licenses/certifi-MPL-2.0.txt`](licenses/certifi-MPL-2.0.txt).
- La version et l'empreinte SHA-256 de la copie sont inscrites dans
  `TLS_CA_VERSION` et `TLS_CA_SHA256` du script.

Le contenu PEM peut être récupéré sans modification après import du script :
`module.TLS_CA_PEM.encode('ascii')`. L'import n'ouvre aucune base de données et
n'effectue aucune connexion réseau. L'outil `tools/embed_certificates.py` permet
de reproduire ou d'actualiser l'intégration à partir du paquet certifi.

Le code Python de certifi n'est pas nécessaire à l'exécution de Dominis.
Pillow et trustme ne servent qu'aux outils de développement et aux tests ; ils
ne sont pas intégrés au programme distribué.
