"""Vérifications de bout en bout du lecteur Excel et de l'import.

Chaque cas construit un classeur minimal, exécute le vrai lecteur (ou le vrai
import en base) et compare au résultat attendu. Ce script complète la suite de
tests unitaires : il sert à rejouer l'audit complet après chaque modification.

Usage : python3 tests/verif_import.py
"""
import base64
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dominis import app                                   # noqa: E402
from test_import_xlsx import build_xlsx, MONEY                 # noqa: E402

CHECKS = []


def check(label, ok, detail=''):
    CHECKS.append((label, bool(ok), detail))
    print(('PASS  ' if ok else 'FAIL  ') + label + (('  — ' + str(detail)) if detail else ''))


def analyse(sheets, **kw):
    kw.setdefault('numfmts', {164: '#,##0.00 €'})
    kw.setdefault('cell_xfs', [0, 164])
    data = build_xlsx(sheets, **kw)
    if isinstance(data, bytes): data = base64.b64encode(data).decode()
    return app.parse_import({'format': 'xlsx', 'text': data})


def total(out, name=None):
    for s in out['scis']:
        if name and name not in (s.get('name') or ''): continue
        moves = [r for r in out['records'] if r['sci'] == s['id']]
        signed = sum(r['amount'] * (1 if r['direction'] == 'Recette' else -1) for r in moves)
        return round((s.get('opening') or 0) + signed, 2), s, moves
    return None, None, []


def warns(out, needle):
    return [w for w in out['warnings'] if needle.lower() in w.lower()]


def op(d, label, debit=None, credit=None, solde=None, style=MONEY):
    cells = [(0, 'inline', d), (1, 'inline', label)]
    if debit is not None: cells.append((2, 'n', debit, style))
    if credit is not None: cells.append((3, 'n', credit, style))
    if solde is not None: cells.append((4, 'n', solde, style))
    return cells


HEADER = [(0, 'inline', 'Date'), (1, 'inline', 'Libellé'), (2, 'inline', 'Débit'),
          (3, 'inline', 'Crédit'), (4, 'inline', 'Solde')]


# --------------------------------------------------------------- colonnes (Q1)
out = analyse([('Relevé', [
    [(0, 'inline', 'SCI TEST')],
    [(0, 'inline', 'Date'), (1, 'inline', 'Libellé')],
    [(2, 'inline', 'Débit'), (3, 'inline', 'Crédit'), (4, 'inline', 'Solde')],
    [(4, 'n', 1000.0, MONEY)],
    op('05/01/2025', 'Loyer', credit=1200.0),
])])
tot, _, mv = total(out)
check('Q1 en-tête sur deux lignes', tot == 2200 and len(mv) == 1, 'solde %s, %d mouvement(s)' % (tot, len(mv)))

out = analyse([('Relevé', [
    [(0, 'inline', 'Solde'), (1, 'inline', 'Libellé'), (2, 'inline', 'Date'),
     (3, 'inline', 'Crédit'), (4, 'inline', 'Débit')],
    [(0, 'n', 1000.0, MONEY)],
    [(0, 'n', 2200.0, MONEY), (1, 'inline', 'Loyer'), (2, 'inline', '05/01/2025'), (3, 'n', 1200.0, MONEY)],
])])
tot, _, mv = total(out)
check('Q1 colonnes dans un ordre inhabituel', tot == 2200 and len(mv) == 1, 'solde %s' % tot)

out = analyse([('Relevé', [
    [(0, 'inline', 'Date'), (1, 'inline', 'Libellé'), (2, 'inline', 'Montant'), (3, 'inline', 'Sens')],
    [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'), (2, 'n', 1200.0, MONEY), (3, 'inline', 'Crédit')],
    [(0, 'inline', '10/01/2025'), (1, 'inline', 'Travaux'), (2, 'n', 200.0, MONEY), (3, 'inline', 'Débit')],
])])
tot, _, mv = total(out)
dep = [r for r in mv if r['direction'] == 'Dépense']
check('Q1 colonne Montant + Sens', tot == 1000 and len(mv) == 2 and dep and dep[0]['amount'] == 200,
      'solde %s, %d mouvement(s)' % (tot, len(mv)))

try:
    analyse([('Relevé', [
        [(0, 'inline', 'Date'), (1, 'inline', 'Libellé'), (2, 'inline', 'Montant'), (3, 'inline', 'Sens')],
        [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'), (2, 'n', 1200.0, MONEY), (3, 'inline', 'peut-être')],
    ])])
    check('Q1 sens illisible refusé', False, 'aucune erreur')
except ValueError as e:
    check('Q1 sens illisible refusé', 'sens illisible' in str(e).lower(), str(e)[:80])

out = analyse([('Relevé', [
    [(1, 'inline', 'Date'), (2, 'inline', 'Libellé'), (3, 'inline', 'Débit'),
     (4, 'inline', 'Crédit'), (5, 'inline', 'Solde')],
    [(5, 'n', 1000.0, MONEY)],
    [(1, 'inline', '05/01/2025'), (2, 'inline', 'Loyer'), (4, 'n', 1200.0, MONEY)],
])])
tot, _, mv = total(out)
check('Q1 tableau décalé', tot == 2200 and len(mv) == 1, 'solde %s' % tot)

# ------------------------------------------------------------- hors tableau (Q2)
out = analyse([('Relevé', [
    [(0, 'inline', 'SCI THEMA IMMOBILIER')],
    [(0, 'inline', 'Compte courant · exercice 2025')],
    HEADER,
    [(4, 'n', 1000.0, MONEY)],
    op('05/01/2025', 'Loyer', credit=1200.0),
    op('10/01/2025', 'Travaux', debit=200.0),
    [(1, 'inline', 'Total des dépenses'), (2, 'n', 200.0, MONEY)],
    [(1, 'inline', 'Total des recettes'), (3, 'n', 1200.0, MONEY)],
    [(0, 'inline', 'Document non contractuel, arrêté au 31/12/2025.')],
])])
tot, _, mv = total(out)
check('Q2 totaux et notes hors tableau', tot == 2000 and len(mv) == 2, 'solde %s, %d mouvement(s)' % (tot, len(mv)))
check('Q2 synthèses comptées et nommées', bool(warns(out, 'ligne(s) de synthèse')),
      (warns(out, 'ligne(s) de synthèse') or ['aucun message'])[0][:90])

out = analyse([('Relevé', [
    HEADER,
    [(4, 'n', 1000.0, MONEY)],
    op('05/01/2025', 'Loyer', credit=1200.0),
    op('31/12/2025', 'Cumul annuel', credit=1200.0),
])])
tot, _, mv = total(out)
check('Q2 récapitulatif daté non importé', tot == 2200 and len(mv) == 1, 'solde %s' % tot)

# ----------------------------------------------------------------- formules (Q3)
out = analyse([('Relevé', [HEADER, [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'),
                                    (3, 'f', '1000+200', MONEY)]])])
tot, _, mv = total(out)
check('Q3 formule sans cache recalculée', tot == 1200 and len(mv) == 1, 'solde %s' % tot)
check('Q3 recalcul signalé', bool(warns(out, 'recalculées')), (warns(out, 'recalculées') or [''])[0][:70])

out = analyse([('Relevé', [
    HEADER,
    [(4, 'n', 1000.0, MONEY)],
    [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'), (2, 'f', 'VLOOKUP(A1,B:C,2,0)', MONEY)],
    op('06/01/2025', 'Travaux', debit=100.0),
])])
_, _, mv = total(out)
msg = (warns(out, 'non') + warns(out, 'recalculée') or ['aucun message'])[0]
check('Q3 formule illisible signalée', bool(warns(out, 'Ouvrez le classeur dans Excel')) and len(mv) == 1, msg[:100])

out = analyse([('Relevé', [
    HEADER,
    [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'), (3, 'f', 'D2+1', MONEY)],
    op('06/01/2025', 'Travaux', debit=100.0),
])])
check('Q3 référence circulaire sans plantage', bool(warns(out, 'Ouvrez le classeur dans Excel')),
      (out['warnings'] or ['aucun message'])[0][:80])

# ------------------------------------------------------------------ bordures (Q4)
def boxed(cells):
    return [(c[0], c[1], c[2], 4) + tuple(c[4:]) for c in cells]


BOX_KW = dict(numfmts={164: '#,##0.00 €'}, cell_xfs=[0, 164, 164, 164, 164],
              borders=[[], ['left', 'right', 'top', 'bottom']],
              border_xfs={1: 1, 2: 1, 3: 1, 4: 1})
rows = [boxed(HEADER), boxed([(4, 'n', 1000.0, 164)]),
        boxed(op('05/01/2025', 'Loyer', credit=1200.0, style=164)),
        boxed(op('06/01/2025', 'Travaux', debit=200.0, style=164)),
        boxed(op('07/01/2025', 'Charges', debit=100.0, style=164)),
        None,
        op('31/12/2025', 'Frais de dossier', debit=293.05, style=164)]
out = analyse([('Relevé', rows)], **BOX_KW)
tot, _, mv = total(out)
check('Q4 bordures : fin du tableau', tot == 1900 and len(mv) == 3, 'solde %s, %d mvt' % (tot, len(mv)))
check('Q4 lignes hors tableau listées', bool(warns(out, 'hors du tableau')) and bool(warns(out, 'Frais de dossier')),
      (warns(out, 'hors du tableau') or [''])[0][:90])

rows = [boxed(HEADER), [(4, 'n', 1000.0, 164)],
        op('05/01/2025', 'Loyer', credit=1200.0, style=164),
        op('06/01/2025', 'Travaux', debit=200.0, style=164),
        boxed(op('07/01/2025', 'Charges', debit=100.0, style=164))]
out = analyse([('Relevé', rows)], **BOX_KW)
tot, _, mv = total(out)
check('Q4 encadrement partiel sans perte', tot == 1900 and len(mv) == 3, 'solde %s' % tot)

# --------------------------------------------------------------- multi-feuilles (Q5)
out = analyse([
    ('SCI ALPHA', [HEADER, [(4, 'n', 1000.0, MONEY)], op('05/01/2025', 'Loyer', credit=1200.0)]),
    ('SCI BETA', [HEADER, [(4, 'n', 5000.0, MONEY)], op('05/01/2025', 'Travaux', debit=500.0)]),
])
tot_a, _, _ = total(out, 'ALPHA')
tot_b, _, _ = total(out, 'BETA')
check('Q5 deux SCI dans un classeur', tot_a == 2200 and tot_b == 4500, 'ALPHA %s, BETA %s' % (tot_a, tot_b))

out = analyse([
    ('Relevé', [HEADER, [(4, 'n', 1000.0, MONEY)], op('05/01/2025', 'Loyer', credit=1200.0)]),
    ('Notes', [[(0, 'inline', 'Aucun tableau ici')]]),
])
tot, _, mv = total(out)
check('Q5 feuille sans tableau tolérée', tot == 2200 and len(mv) == 1, 'solde %s' % tot)

# ------------------------------------------------------------------ corrélés (Q6)
out = analyse([('Relevé', [HEADER, [(0, 'inline', '05/01/2025'), (1, 'inline', 'Loyer'), (3, 'inline', '1.234')]])])
mv = out['records']
check('Q6 « 1.234 » lu comme 1 234 €', mv and mv[0]['amount'] == 1234.0, [r['amount'] for r in mv])
check('Q6 lecture des milliers signalée', bool(warns(out, 'milliers')), (warns(out, 'milliers') or [''])[0][:70])

try:
    analyse([('Relevé', [HEADER, [(4, 'n', 1000.0, MONEY)]])])
    check('Q6 tableau sans opération refusé', False, 'aucune erreur')
except ValueError as e:
    check('Q6 tableau sans opération refusé', 'Aucune opération importable' in str(e), str(e)[:80])

# ----------------------------------------- A. feuilles et titres de synthèse
out = analyse([
    ('SCI THEMA', [HEADER, op('05/03/2025', 'Loyer', credit=1000.0)]),
    ('Synthèse', [[(0, 'inline', 'SCI THEMA')], HEADER,
                  op('31/12/2024', 'Loyers encaissés', credit=12000.0)]),
])
tot, _, mv = total(out)
check('A feuille « Synthèse » jamais fusionnée dans la SCI', tot == 1000 and len(mv) == 1,
      'solde %s, %d mouvement(s)' % (tot, len(mv)))
check('A feuille de synthèse signalée', bool(warns(out, 'tableau de synthèse')),
      (warns(out, 'tableau de synthèse') or [''])[0][:90])
check('A aucune SCI fantôme', len(out['scis']) == 1, [s['name'] for s in out['scis']])

try:
    out = analyse([('Feuil1', [[(0, 'inline', 'Récapitulatif général')], HEADER,
                               op('31/12/2024', 'Loyers encaissés', credit=12000.0),
                               op('31/12/2024', 'Charges payées', debit=4000.0)])])
    check('A tableau « Récapitulatif général » non importé', not out['records'], len(out['records']))
except ValueError as e:
    check('A tableau « Récapitulatif général » non importé',
          'tableau de synthèse' in str(e).lower() and 'Pistes' in str(e), str(e)[:120])

try:
    analyse([('Synthèse', [HEADER, op('31/12/2024', 'Loyers encaissés', credit=12000.0)])])
    check('A classeur de synthèse seule refusé', False, 'aucune erreur')
except ValueError as e:
    check('A classeur de synthèse seule refusé', 'feuille' in str(e).lower() and 'relevé' in str(e).lower(),
          str(e)[:100])

# ------------------------------------------------------- C. titres avec préfixe
out = analyse([('Feuil1', [[(0, 'inline', 'Bilan 2024 · SCI THEMA')], HEADER,
                           op('05/03/2025', 'Loyer', credit=1000.0)])])
check('C titre « Bilan 2024 · SCI THEMA » conservé', out['scis'][0]['name'] == 'SCI THEMA',
      out['scis'][0]['name'])

out = analyse([
    ('2024', [[(0, 'inline', 'Bilan 2024 · SCI THEMA')], HEADER, op('05/03/2024', 'Loyer', credit=1000.0)]),
    ('2025', [[(0, 'inline', 'Bilan 2025 · SCI THEMA')], HEADER, op('05/03/2025', 'Loyer', credit=1100.0)]),
])
check('C deux exercices = une seule SCI', len(out['scis']) == 1 and len(out['records']) == 2,
      [s['name'] for s in out['scis']])

# --------------------------------------------------- B. doublons et raccordement
HDR = HEADER


def book(opening, rows, title='SCI TEST'):
    return build_xlsx([('Relevé', [[(0, 'inline', title)], HDR, [(4, 'n', opening, MONEY)]] + rows)],
                      numfmts={164: '#,##0.00 €'}, cell_xfs=[0, 164])


def state(c):
    scis = [dict(json.loads(r['data']), id=r['id']) for r in c.execute('select id,data from scis')]
    ent = [json.loads(r['data']) for r in c.execute("select data from records where kind='entries'")]
    net = sum(r['amount'] * (1 if r['direction'] == 'Recette' else -1) for r in ent)
    return scis, ent, round((scis[0].get('opening') or 0) + net, 2)


f2024 = book(1000.0, [op('05/03/2024', 'Loyer', credit=1200.0, solde=2200.0)])
f2025 = book(2200.0, [op('05/03/2025', 'Loyer', credit=1200.0, solde=3400.0)])
f_overlap = book(1000.0, [op('05/03/2024', 'Loyer', credit=1200.0, solde=2200.0),
                          op('05/03/2025', 'Loyer', credit=1200.0, solde=3400.0)])

with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DB', Path(tmp) / 'd.db'):
    app.init_db()
    with app.connect() as c:
        dest = 'new'
        for data in (f2024, f2025):
            b = app.parse_import({'format': 'xlsx', 'text': base64.b64encode(data).decode()})
            app.import_bundle(c, {'format': 'xlsx', 'text': base64.b64encode(data).decode(),
                                  'mapping': {b['scis'][0]['id']: dest}})
            c.commit()
            dest = state(c)[0][0]['id']
        scis, ent, cash = state(c)
        check('B deux exercices enchaînés', len(ent) == 2 and cash == 3400.0,
              '%d mouvement(s), solde %s' % (len(ent), cash))

        b = app.parse_import({'format': 'xlsx', 'text': base64.b64encode(f_overlap).decode()})
        res = app.import_bundle(c, {'format': 'xlsx', 'text': base64.b64encode(f_overlap).decode(),
                                    'mapping': {b['scis'][0]['id']: dest}})
        c.commit()
        scis, ent, cash = state(c)
        check('B recouvrement de fichiers sans double comptage', res['count'] == 0 and res['skipped'] == 2
              and cash == 3400.0, 'importés %s, ignorés %s, solde %s' % (res['count'], res['skipped'], cash))
        check('B doublons annoncés', any('déjà présente' in w for w in res['warnings']),
              res['warnings'][0][:90] if res['warnings'] else 'aucun message')

        f_bad = book(2250.0, [op('05/03/2025', 'Loyer bis', credit=1200.0, solde=3450.0)])
        b = app.parse_import({'format': 'xlsx', 'text': base64.b64encode(f_bad).decode()})
        res = app.import_bundle(c, {'format': 'xlsx', 'text': base64.b64encode(f_bad).decode(),
                                    'mapping': {b['scis'][0]['id']: dest}})
        c.commit()
        scis, ent, cash = state(c)
        check('B écart de raccordement refusé en silence', cash == 4600.0,
              'solde après import %s (le fichier annonce 3450)' % cash)
        check('B raccordement signalé', any('ne correspond pas au solde' in w for w in res['warnings']),
              [w for w in res['warnings'] if 'ne correspond pas' in w][0][:110] if res['warnings'] else 'aucun')

print()
failed = [c for c in CHECKS if not c[1]]
print('%d vérification(s) — %d échec(s)' % (len(CHECKS), len(failed)))
sys.exit(0 if not failed else 1)
