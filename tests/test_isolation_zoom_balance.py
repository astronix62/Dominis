"""Garanties structurelles : réglages de tableau cloisonnés, zoom d'aperçu,
lignes de totaux mensuelles de la trésorerie et page « Bilan ».

Ces régressions portent sur le JavaScript embarqué dans Dominis.py (application
mono-fichier). Les tests vérifient la présence et l'articulation des mécanismes
qui garantissent le comportement attendu : une clé de réglages par tableau, un
facteur de zoom qui agit réellement sur le contenu, des lignes de mois limitées
à la trésorerie et une page de bilan sur l'onglet attendu.
"""
import importlib.util
import re
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / 'Dominis' / 'Dominis.py'
spec = importlib.util.spec_from_file_location('dominis_ui', APP)
app = importlib.util.module_from_spec(spec)
spec.loader.exec_module(app)

HTML = app.HTML


def between(start, end):
    i = HTML.index(start)
    j = HTML.index(end, i)
    return HTML[i:j + len(end)]


class TableSettingsIsolationTests(unittest.TestCase):
    def test_every_table_has_its_own_settings_key(self):
        self.assertIn('function tableKey(kind)', HTML)
        self.assertIn("if(page==='dashboard')return 'dashboard';", HTML)
        self.assertIn("if(navs[page])return 'page:'+page;", HTML)
        self.assertIn("if(S.scis.some(s=>s.id===page))return 'sci:'+page;", HTML)
        # La lecture et l'écriture utilisent la clé du tableau, plus le type.
        self.assertIn('all[key]={...tableView(key),...cfg};', HTML)
        self.assertIn('let own=(all[key]&&typeof all[key]===\'object\')?all[key]:{};', HTML)
        self.assertIn('let cfg=all[key]||all[kind]||null;', HTML)

    def test_treasury_page_and_sci_treasury_are_separate(self):
        self.assertIn('let tkey=tableKey(kind);', HTML)
        self.assertIn('let cols=getTableColumns(tkey)', HTML)
        self.assertIn('let v=tableView(tkey);', HTML)
        self.assertIn('data-table-config="${tkey}"', HTML)

    def test_dashboard_preview_applies_its_own_settings(self):
        self.assertIn("let tkey=tableKey('entries_preview'),v=tableView(tkey);", HTML)
        self.assertIn('<div class="table-wrap ${tableWrapClass(v)}">', HTML)

    def test_column_reset_is_explicit_and_local(self):
        self.assertIn('all[k]={order:[],hidden:[]};', HTML)
        self.assertNotIn('delete all[k];await setPref({table_columns:all});', HTML)

    def test_settings_modal_names_the_scope(self):
        self.assertIn("'Réglages du tableau · '+tableKindLabel(key)", HTML)
        self.assertIn('réglages propres à ce tableau', HTML)


class MonthlyTotalsTests(unittest.TestCase):
    def test_month_rows_are_limited_to_treasury_and_totals_option(self):
        self.assertIn("if(kind==='entries'&&v.totals&&list.length){", HTML)
        self.assertIn('function entriesMonthRows(list,id,cols,colTd){', HTML)

    def test_month_rows_carry_cumulative_totals(self):
        block = between('function entriesMonthRows(', 'return out;')
        self.assertIn('cumCredit=r2(cumCredit+amt)', block)
        self.assertIn('cumDebit=r2(cumDebit+amt)', block)
        self.assertIn('let bal=cashAtDate(id,m.last)', block)
        self.assertIn('Totaux au ', block)

    def test_totals_toggle_is_hidden_where_it_has_no_effect(self):
        self.assertIn("hasTotals=['entries','calls'].includes(kind)", HTML)

    def test_no_month_rows_without_totals(self):
        # Le garde-fou du rendu : sans l'option, aucune ligne de totaux n'est produite.
        self.assertNotIn("if(kind==='entries'&&list.length){", HTML)
        self.assertIn("if(kind==='entries'&&v.totals&&list.length){", HTML)


class DocumentZoomTests(unittest.TestCase):
    def test_viewport_no_longer_centres_and_clips_the_content(self):
        viewport = between('.doc-preview-viewport{', '}')
        self.assertNotIn('display:flex', viewport)
        stage = between('.doc-preview-stage{', '}')
        self.assertIn('align-items:flex-start', stage)
        self.assertIn('width:calc(100% * var(--doc-zoom,1))', stage)

    def test_sheet_text_follows_the_zoom(self):
        # Les cellules avaient une taille en pixels fixes : le zoom ne changeait
        # que le cadre. Ces règles sont la correction du défaut.
        self.assertIn('.doc-preview-sheet th{font-size:calc(9px * var(--doc-zoom,1));padding:calc(12px * var(--doc-zoom,1)) calc(20px * var(--doc-zoom,1))}', HTML)
        self.assertIn('.doc-preview-sheet td{font-size:calc(11px * var(--doc-zoom,1));padding:calc(14px * var(--doc-zoom,1)) calc(20px * var(--doc-zoom,1))}', HTML)
        self.assertIn('doc-preview-sheet-stage', HTML)

    def test_pdf_is_really_scaled(self):
        frame = between('.doc-preview-frame{', '}')
        self.assertIn('transform:scale(var(--doc-zoom,1))', frame)
        self.assertIn('width:calc(100% / var(--doc-zoom,1))', frame)
        self.assertIn('.doc-preview-stage.doc-preview-pdf{width:calc(100% * var(--doc-zoom,1))', HTML)

    def test_zoom_controls_and_bounds(self):
        self.assertIn('function docPreviewClampZoom(z){', HTML)
        self.assertIn('return Math.min(4,Math.max(0.25,Math.round(n*100)/100));', HTML)
        self.assertIn("if(ev.target.id==='doc-zoom-range'){docPreviewStageZoom((Number(ev.target.value)||100)/100);}", HTML)
        self.assertIn("if(v==='in')docPreviewStageZoom(docPreviewZoom+0.25);else if(v==='out')docPreviewStageZoom(docPreviewZoom-0.25);", HTML)
        # Le libellé et le curseur suivent toujours le facteur réellement appliqué.
        self.assertIn("label.textContent='×'+next.toFixed(2).replace('.',',')", HTML)


class BalancePageTests(unittest.TestCase):
    def test_balance_tab_sits_between_documents_and_identity(self):
        tabs = between('const tabs=[', '];')
        self.assertIn("['documents','Documents'],['balance','Bilan'],['identity','Société']", tabs)

    def test_balance_tab_is_routed(self):
        self.assertIn("tab==='balance'?balancePage(s)", HTML)

    def test_balance_period_can_be_a_year_or_a_custom_range(self):
        self.assertIn('id="balance-year"', HTML)
        self.assertIn('id="balance-start"', HTML)
        self.assertIn('id="balance-end"', HTML)
        self.assertIn("if(el.value==='custom')", HTML)
        self.assertIn('Période personnalisée', HTML)

    def test_balance_uses_the_legal_presentation(self):
        for label in ('Actif', 'Passif', 'Compte de résultat', 'Capital social ou individuel',
                      'Report à nouveau', 'Résultat de l’exercice',
                      'Immobilisations corporelles', 'Créances · clients et comptes rattachés',
                      'Disponibilités', 'Emprunts et dettes assimilées',
                      'Comptes courants d’associés', 'Dépôts de garantie reçus'):
            self.assertIn(label, HTML)
        # Cases officielles du bilan simplifié 2033-A.
        for code in ("code:'028'", "code:'068'", "code:'084'", "code:'120'",
                     "code:'134'", "code:'136'", "code:'164'", "code:'169'", "code:'174'"):
            self.assertIn(code, HTML)
        self.assertIn('Total général de l’actif · 110 (brut) / 112 (net)', HTML)
        self.assertIn('Total général du passif · 180', HTML)
        self.assertIn('<th class="align-right">Brut</th><th class="align-right">Amortissements</th>', HTML)

    def test_financing_flows_are_excluded_from_the_result(self):
        self.assertIn("const BALANCE_FINANCING_IN=new Set(['Apport associé','Emprunt (capital + intérêts)','Dépôt de garantie']);", HTML)
        self.assertIn("const BALANCE_FINANCING_OUT=new Set(['Remboursement associé','Emprunt (capital + intérêts)','Apport associé']);", HTML)
        self.assertIn('Opérations de financement exclues du résultat', HTML)

    def test_balance_gap_is_shown_not_hidden(self):
        self.assertIn('Écart actif − passif', HTML)
        self.assertIn('Cet écart n’est pas corrigé automatiquement', HTML)
        self.assertIn("let gap=r2(totalActif-totalPassif);", HTML)

    def test_balance_uses_the_same_cash_rules_as_the_treasury(self):
        block = between('function balanceModel(', 'let gap=r2(totalActif-totalPassif);')
        self.assertIn('sciCashInfo(s,entries,period.end)', block)
        self.assertIn('opening=toNum(s.opening)', block)

    def test_comparison_covers_each_existing_year(self):
        self.assertIn('Comparaison des exercices', HTML)
        self.assertIn('let compare=years.slice(0,5).map(y=>{', HTML)


class Balance2072Tests(unittest.TestCase):
    """Formulaire 2072-C-A1 : numérotation officielle, arrondis, adresses.

    Le classeur de référence portait « L136 = 21/24 » : le revenu ou déficit de
    l'immeuble (ligne 21) devient le revenu net (ligne 24) réparti entre les
    associés. Les montants sont arrondis à l'euro colonne par colonne, jamais
    après addition, et deux biens à la même adresse ne forment qu'une colonne.
    """

    def test_official_lines_are_listed_in_order(self):
        block = between('const BALANCE_2072_LINES=[', '];')
        numbers = [int(n) for n in re.findall(r'\[(\d+),', block)]
        self.assertEqual(numbers, list(range(1, 27)))
        self.assertIn('REVENU (+) OU DÉFICIT (-) DE L’IMMEUBLE', block)
        self.assertIn('REVENU NET (+) OU DÉFICIT (-)', block)
        self.assertIn('À RÉPARTIR ENTRE LES ASSOCIÉS', block)

    def test_result_is_carried_to_lines_21_and_24(self):
        block = between('// 21 = 5 − 17 − 18 − 19 − 20', 'pushRow(25,')
        self.assertIn('prev[5].cells[i]-prev[17].cells[i]', block)
        self.assertIn('prev[21].cells[i]+prev[22].cells[i]-prev[23].cells[i]', block)
        self.assertIn('21 / 24', HTML)

    def test_amounts_are_rounded_per_column_before_summing(self):
        self.assertIn('let cells=keys.map(k=>Math.round(balanceLineAmount(m,n,k)));', HTML)
        self.assertIn('rounded=cells.reduce((a,b)=>a+b,0);', HTML)
        self.assertIn('arrondis à l’euro colonne par colonne, puis additionnés', HTML)

    def test_buildings_are_grouped_by_distinct_address(self):
        self.assertIn('function balanceAddressKey', HTML)
        self.assertIn('__sans_adresse__', HTML)
        block = between('function balanceBuildings(', 'function balanceEntryBuilding(')
        self.assertIn('balanceAddressKey', block)

    def test_forfait_is_a_single_editable_amount(self):
        self.assertIn('function balanceForfaitSetting(s,year,hasBuildings)', HTML)
        self.assertIn('return hasBuildings?20:0;', HTML)
        self.assertIn('data-action="balance-forfait-local"', HTML)
        self.assertIn('Appliquer le forfait de 20 €', HTML)
        # Le forfait ne dépend pas du nombre d'adresses.
        self.assertNotIn('20*m.buildings.length', HTML)

    def test_line_mapping_and_assignment_are_persisted(self):
        self.assertIn("case'balance-map-save'", HTML)
        self.assertIn('balance_line_map', HTML)
        self.assertIn("case'balance-assign-save'", HTML)
        self.assertIn("data-balance-assign", HTML)

    def test_is_company_is_pointed_to_the_2033_bundle(self):
        self.assertIn('2033-A', HTML)
        self.assertIn('2033-B', HTML)
        self.assertIn('data-balance-tab="comptable"', HTML)

    def test_unassigned_and_unclassified_are_never_silently_reused(self):
        self.assertIn('Ils ne sont pas repris dans les totaux officiels.', HTML)
        self.assertIn('Ils apparaissent en « Non affecté ».', HTML)


if __name__ == '__main__':
    unittest.main()
