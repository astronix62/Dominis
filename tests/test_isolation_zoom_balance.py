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
        self.assertIn("['documents','Documents'],['balance','Déclaration'],['identity','Société']", tabs)

    def test_balance_tab_is_routed_to_the_declaration_page(self):
        self.assertIn("tab==='balance'?declPage(s)", HTML)

    def test_balance_period_can_be_a_year_or_a_custom_range(self):
        self.assertIn('id="balance-year"', HTML)
        self.assertIn('id="balance-start"', HTML)
        self.assertIn('id="balance-end"', HTML)
        self.assertIn("if(el.value==='custom')", HTML)
        self.assertIn('Période personnalisée', HTML)

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

    def test_accounting_balance_is_reserved_to_income_tax_companies(self):
        # 2033-A / 2033-B ne sont déposés que par une SCI à l'IS : les cases
        # officielles restent, mais uniquement dans l'onglet IS.
        for code in ("code:'028'", "code:'068'", "code:'084'", "code:'120'",
                     "code:'134'", "code:'136'", "code:'164'", "code:'169'", "code:'174'"):
            self.assertIn(code, HTML)
        self.assertIn('Total général de l’actif · 110 (brut) / 112 (net)', HTML)
        self.assertIn('Total général du passif · 180', HTML)
        self.assertIn('const DECL_IS_TABS=[[\'is\',\'2065 · 2033-A/B\']];', HTML)
        self.assertIn('ni 2072-S, ni 2044', HTML)


class Declaration2072STests(unittest.TestCase):
    """2072-S : numérotation officielle, arrondis, adresses, associés, 2044.

    Une SCI à l'IR dépose la 2072-S (cadres I à IV) avec l'annexe A1 (cadre VII,
    lignes 1 à 23) et l'annexe A2 (cadre IX). Chaque associé recopie ensuite sa
    quote-part sur sa 2044 puis sur sa 2042. La numérotation de la 2072-S n'est
    pas celle de la 2072-C : pas de ligne « immeubles spéciaux » ni
    « amortissement », le revenu de l'immeuble est en 18, le revenu net en 21 et
    le montant à répartir en 23.
    """

    def test_official_lines_are_listed_in_order(self):
        block = between('const DECL_A1_LINES=[', '];')
        numbers = [n.replace("'", '') for n in re.findall(r"\[(\d+|'9bis'),'", block)]
        self.assertEqual(numbers, ['1', '2', '3', '4', '5', '6', '7', '8', '9',
                                   '9bis', '10', '11', '12', '13', '14', '15', '16',
                                   '17', '18', '19', '20', '21', '22', '23'])
        self.assertIn('REVENU (+) OU DÉFICIT (−) DE L’IMMEUBLE (lignes 5 − 16 − 17)', block)
        self.assertIn('REVENU NET (+) OU DÉFICIT (−) (lignes 18 + 19 − 20)', block)
        self.assertIn('À RÉPARTIR ENTRE LES ASSOCIÉS (lignes 21 + 22)', block)

    def test_totals_follow_the_official_formulas(self):
        block = between('function declA1Rows(', 'return rowsOut;')
        self.assertIn('get(1)[i]+get(2)[i]+get(3)[i]+get(4)[i]', block)              # 5
        self.assertIn('get(6)[i]+get(7)[i]+get(8)[i]+get(9)[i]+get(10)[i]', block)   # 16
        self.assertIn('-get(14)[i]+get(15)[i]', block)                               # 14 déduite
        self.assertIn('get(5)[i]-get(16)[i]-get(17)[i]', block)                      # 18
        self.assertIn('get(18)[i]+get(19)[i]-get(20)[i]', block)                     # 21
        self.assertIn('get(21)[i]+get(22)[i]', block)                                # 23

    def test_main_form_carries_the_five_boxes(self):
        block = between('function declMainCases(', 'R5:sum(23)')
        self.assertIn('R1:sum(5)+sum(19)-sum(20)+sum(22)', block)
        self.assertIn('R2:sum(9)', block)
        self.assertIn('R3:sum(16)', block)
        self.assertIn('R4:sum(17)', block)
        self.assertIn("'R5'", block) if "'R5'" in block else self.assertIn('R5:sum(23)', block)

    def test_amounts_are_rounded_per_column_before_summing(self):
        self.assertIn('return keys.map(k=>Math.round(L&&L.by[k]?L.by[k]:0));', HTML)
        self.assertIn('function declSum(cells)', HTML)
        self.assertIn("Arrondi à l'euro de chaque colonne, puis seulement ensuite addition.", HTML)

    def test_buildings_are_grouped_by_distinct_address(self):
        self.assertIn('function balanceAddressKey', HTML)
        self.assertIn('__sans_adresse__', HTML)
        block = between('function balanceBuildings(', 'function entryBuilding(')
        self.assertIn('balanceAddressKey', block)

    def test_the_twenty_euro_flat_rate_is_gone(self):
        self.assertNotIn('balance_forfait', HTML)
        self.assertNotIn('balance-forfait', HTML)
        self.assertNotIn('20 € par local', HTML)

    def test_associates_get_their_quota_share(self):
        block = between('function declShares(', 'A-B-D')
        self.assertIn('let A=Math.round((c.R1)*p.quote);', block)
        self.assertIn('let B=Math.round((c.R3)*p.quote);', block)
        self.assertIn('let D=Math.round((c.R4)*p.quote);', block)
        self.assertIn('A-B-D', block)
        self.assertIn('function declPartners(s)', HTML)

    def test_2044_routes_the_deficit_to_the_right_boxes(self):
        block = between('function decl2044Cases(', 'function decl2044View(')
        self.assertIn('let cap=Math.min(10700+(Number(renov)||0),21400);', block)
        self.assertIn('bb:reste+interetsExcedent', block)
        self.assertIn('bb:deficit-bc', block)
        self.assertIn("ba:r420", block)
        for case in ('4BA', '4BB', '4BC', '4BD'):
            self.assertIn(case, HTML)

    def test_line_mapping_and_assignment_are_persisted(self):
        self.assertIn("case'decl-map-save'", HTML)
        self.assertIn('decl_line_map', HTML)
        self.assertIn("case'decl-assign-save'", HTML)
        self.assertIn("data-decl-assign", HTML)

    def test_each_amount_can_be_copied_into_the_online_form(self):
        self.assertIn('data-decl-copy=', HTML)
        self.assertIn('navigator.clipboard', HTML)
        self.assertIn('function declCopyAmount(', HTML)

    def test_each_amount_says_where_it_comes_from(self):
        self.assertIn('function declProvenance(', HTML)
        self.assertIn('data-decl-detail=', HTML)
        self.assertIn('function declDetailModal(', HTML)

    def test_unclassified_and_unsplit_are_never_silently_reused(self):
        self.assertIn('ne sont pas comptés dans ce tableau', HTML)
        self.assertIn('La ligne 17 n’accepte que les intérêts', HTML)

    def test_checks_tab_tells_what_is_missing(self):
        self.assertIn('Pouvez-vous déclarer ?', HTML)
        self.assertIn('function declChecksView(', HTML)
        self.assertIn("'Bloquant'", HTML)


if __name__ == '__main__':
    unittest.main()
