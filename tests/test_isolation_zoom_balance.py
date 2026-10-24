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
        for label in ('Actif', 'Passif', 'Compte de résultat', 'Capital social',
                      'Report à nouveau', 'Résultat de la période',
                      'Immobilisations corporelles', 'Créances · loyers échus non encaissés',
                      'Disponibilités · trésorerie', 'Emprunts et dettes financières',
                      'Comptes courants d’associés', 'Dépôts de garantie reçus'):
            self.assertIn(label, HTML)
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


if __name__ == '__main__':
    unittest.main()
