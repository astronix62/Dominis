"""Calculs de la vue d'ensemble (trésorerie, flux, patrimoine).

Les indicateurs sont calculés dans l'interface. Ces tests exécutent réellement
le bloc de calcul extrait de `Dominis.py` avec Node.js : ils reproduisent le
cas signalé d'un « solde calculé à ce jour » bloqué à 0 € malgré des mouvements.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from test_dominis import app


def calculation_block():
    start = app.HTML.index('function paid(c){')
    end = app.HTML.index('async function api(', start)
    return app.HTML[start:end]


def entry(ident, sci, date, amount, direction='Recette', **extra):
    return {'id': ident, 'sci': sci, 'kind': 'entries', 'date': date,
            'amount': amount, 'direction': direction, 'label': 'Mouvement ' + ident,
            **extra}


def sci(ident, name, opening=0, opening_date='2026-01-01', **extra):
    return {'id': ident, 'name': name, 'opening': opening,
            'opening_date': opening_date, **extra}


@unittest.skipUnless(shutil.which('node'), 'Node.js est nécessaire pour exécuter les calculs de l’interface')
class CalculationTests(unittest.TestCase):
    def metrics(self, scis, records, calls=()):
        source = """
const S = %s;
const rows=(kind,sci)=>S.records.filter(r=>r.kind===kind&&(!sci||r.sci===sci));
const today=()=>'2026-10-20';
const yr=()=>true;
%s
const out={total:metrics(),pers:S.scis.map(s=>metrics(s.id))};
console.log(JSON.stringify(out));
""" % (json.dumps({'scis': scis, 'records': list(records) + list(calls)}, ensure_ascii=False),
       calculation_block())
        with tempfile.NamedTemporaryFile('w', suffix='.js', delete=False, encoding='utf-8') as f:
            f.write(source)
            path = f.name
        try:
            result = subprocess.run(['node', path], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_zero_opening_still_counts_imported_history(self):
        # SCI créée le jour même (solde initial 0) puis historique importé :
        # le solde affichait 0 € quel que soit le nombre de mouvements.
        out = self.metrics(
            [sci('a', 'SCI Test 0', opening=0, opening_date='2026-10-20')],
            [entry('e1', 'a', '2025-03-05', 1000),
             entry('e2', 'a', '2025-04-05', 1000),
             entry('e3', 'a', '2026-02-05', 1000)])
        metrics = out['total']
        self.assertEqual(metrics['cash'], 3000)
        self.assertEqual(metrics['cashSkipped'], 0)
        self.assertEqual(metrics['income'], 3000)
        self.assertEqual(metrics['expense'], 0)

    def test_declared_opening_anchors_the_balance(self):
        out = self.metrics(
            [sci('b', 'SCI Horizon', opening=500, opening_date='2026-01-10')],
            [entry('e1', 'b', '2026-01-05', 100),      # déjà compris dans le solde initial
             entry('e2', 'b', '2026-01-15', 200),
             entry('e3', 'b', '2027-01-01', 999),      # postérieur à ce jour
             entry('e4', 'b', '2026-02-01', 50, direction='Dépense')])
        metrics = out['total']
        self.assertEqual(metrics['cash'], 650)          # 500 + 200 - 50
        self.assertEqual(metrics['cashSkipped'], 1)
        self.assertEqual(metrics['income'], 1299)
        self.assertEqual(metrics['expense'], 50)

    def test_cash_is_rounded_to_cents(self):
        out = self.metrics(
            [sci('c', 'SCI Cents', opening=0, opening_date='2026-01-01')],
            [entry('e1', 'c', '2026-01-02', 0.1), entry('e2', 'c', '2026-01-03', 0.2)])
        self.assertEqual(out['total']['cash'], 0.3)

    def test_overview_totals_match_their_details(self):
        scis = [sci('d', 'SCI A', opening=100), sci('e', 'SCI B', opening=0, opening_date='2026-10-20')]
        records = [
            entry('e1', 'd', '2026-01-02', 1000),
            entry('e2', 'd', '2026-01-03', 400, direction='Dépense'),
            entry('e3', 'e', '2025-12-31', 250),
            {'id': 'p1', 'sci': 'd', 'kind': 'properties', 'name': 'Bien 1', 'value': 300000, 'status': 'Loué'},
            {'id': 'p2', 'sci': 'e', 'kind': 'properties', 'name': 'Bien 2', 'value': 200000, 'status': 'Vacant'},
            {'id': 'l1', 'sci': 'd', 'kind': 'loans', 'name': 'Prêt', 'balance': 125000},
        ]
        out = self.metrics(scis, records)
        total = out['total']
        self.assertEqual(total['value'], 500000)
        self.assertEqual(total['properties'], 2)
        self.assertEqual(total['occupied'], 1)
        self.assertEqual(total['debt'], 125000)
        self.assertEqual(total['income'], 1250)
        self.assertEqual(total['expense'], 400)
        self.assertEqual(total['cash'], 950)            # (100 + 1000 - 400) + 250
        self.assertEqual(out['pers'][0]['cash'], 700)
        self.assertEqual(out['pers'][1]['cash'], 250)

    def test_overdue_calls_use_recorded_payments(self):
        records = [entry('e1', 'f', '2026-02-06', 200, call_id='c1')]
        calls = [{'id': 'c1', 'sci': 'f', 'kind': 'calls', 'lease_id': 'l',
                  'period': '2026-02', 'due': '2026-02-05', 'rent': 500, 'charges': 50}]
        out = self.metrics([sci('f', 'SCI Loyers')], records, calls)
        self.assertEqual(out['total']['overdue'], 350)


class DateStorageTests(unittest.TestCase):
    def test_dates_are_written_in_iso_format(self):
        clean = app.clean
        self.assertEqual(clean('entries', {'label': 'Loyer', 'date': '2026-01-05',
                                           'direction': 'Recette', 'amount': 10})['date'],
                         '2026-01-05')
        self.assertEqual(clean('calls', {'lease_id': 'bail-1', 'period': '2026-02',
                                         'due': '2026-02-05', 'rent': 1})['due'],
                         '2026-02-05')


if __name__ == '__main__':
    unittest.main()
