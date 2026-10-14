"""Contrôle navigateur optionnel, sur un serveur --preview avec une base fictive.
Nécessite Playwright et Chromium (CHROMIUM_PATH facultatif).
Les réponses de mise à jour sont simulées ; aucun script n'est installé.
"""
import asyncio
import json
import os
from pathlib import Path
from playwright.async_api import async_playwright


async def main():
    async with async_playwright() as p:
        opts = {'headless': True, 'args': ['--no-sandbox', '--disable-dev-shm-usage']}
        if os.environ.get('CHROMIUM_PATH'): opts['executable_path'] = os.environ['CHROMIUM_PATH']
        browser = await p.chromium.launch(**opts)
        page = await browser.new_page(viewport={'width': 1440, 'height': 1000})
        await page.emulate_media(reduced_motion='reduce')
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        url = os.environ.get('DOMINIS_TEST_URL', 'http://127.0.0.1:8765')
        await page.goto(url)
        await page.locator('.brand-mark').wait_for()
        assert await page.evaluate('S.preview'), 'Utiliser un aperçu avec des données fictives.'
        # Même avec la dernière page enregistrée sur Paramètres, on rouvre le général.
        await page.evaluate("setPref({last_page:'settings',last_tab:'identity',theme:'dark'})")
        await page.reload()
        await page.get_by_role('heading', name='Votre patrimoine, en perspective.').wait_for()
        assert await page.locator('#modal .modal').count() == 0
        snapshot = {'status': 'current', 'current': 'v0.0.1', 'latest': 'v0.0.1', 'checked_at': '2026-10-14T12:00:00',
                    'message': 'Dominis est à jour.', 'dismissed': False, 'preview': False, 'instance': 'test-instance', 'restart_notice': None}
        async def mock_status(route):
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(snapshot))
        await page.route('**/api/update', mock_status)
        await page.locator('#sidebar [data-nav="settings"]').click()
        await page.get_by_role('tab', name='Version', exact=True).click()
        await page.get_by_text('À jour', exact=True).wait_for()
        assert await page.locator('#modal .modal').count() == 0
        Path('.cache').mkdir(exist_ok=True)
        await page.screenshot(path='.cache/version-dark.png', full_page=True)
        # Une panne ne doit pas déclencher une notification ni afficher « À jour ».
        snapshot.update(status='unavailable', message='Vérification impossible : connexion indisponible.')
        await page.get_by_text('Vérification impossible', exact=True).wait_for()
        assert await page.locator('#modal .modal').count() == 0
        snapshot.update(status='available', latest='v0.0.2', message='Une nouvelle version est disponible.')
        await page.get_by_role('dialog', name='Mise à jour disponible', exact=True).wait_for()
        await page.screenshot(path='.cache/update-offer.png', full_page=True)
        await page.get_by_role('button', name='Plus tard', exact=True).click()
        # Simule le report conservé par le serveur pendant la session.
        snapshot['dismissed'] = True
        await page.wait_for_timeout(1500)
        assert await page.locator('#modal .modal').count() == 0
        await page.reload()
        await page.get_by_role('heading', name='Votre patrimoine, en perspective.').wait_for()
        await page.wait_for_timeout(1500)
        assert await page.locator('#modal .modal').count() == 0
        # Au lancement suivant, un nouveau serveur ne conserve pas ce report.
        snapshot['dismissed'] = False
        await page.reload()
        await page.get_by_role('dialog', name='Mise à jour disponible', exact=True).wait_for()
        async def mock_install(route):
            snapshot.update(status='downloading', message='Téléchargement sécurisé de Dominis.py…', dismissed=True)
            await route.fulfill(status=200, content_type='application/json', body=json.dumps(snapshot))
        await page.route('**/api/update/install', mock_install)
        await page.get_by_role('button', name='Mettre à jour', exact=True).click()
        await page.locator('#update-progress').wait_for()
        assert await page.get_by_role('button', name='Fermer', exact=True).is_disabled()
        snapshot.update(status='installing', message='Fichier vérifié. Sauvegarde de vos données…')
        await page.get_by_role('heading', name='Installation en cours', exact=True).wait_for()
        await page.screenshot(path='.cache/update-installing.png', full_page=True)
        snapshot.update(status='failed', message='Mise à jour annulée : disque plein.')
        await page.get_by_role('dialog', name='Mise à jour annulée', exact=True).wait_for()
        await page.get_by_role('button', name='Continuer avec cette version').click()
        snapshot.update(status='current', latest='v0.0.1', message='Dominis est à jour.')
        await page.locator('#sidebar [data-nav="settings"]').click()
        await page.get_by_role('tab', name='Préférences & données').click()
        await page.locator('[data-theme="light"]').click()
        await page.get_by_role('tab', name='Version', exact=True).click()
        await page.get_by_text('À jour', exact=True).wait_for()
        await page.screenshot(path='.cache/version-light.png', full_page=True)
        for width in (1440, 850, 390):
            await page.set_viewport_size({'width': width, 'height': 1000})
            assert await page.get_by_role('heading', name='Version de Dominis').is_visible()
            overflow = await page.evaluate('document.documentElement.scrollWidth > innerWidth')
            if overflow:
                print(await page.evaluate("[...document.querySelectorAll('body *')].filter(e=>e.getBoundingClientRect().right>innerWidth).map(e=>[e.tagName,e.className,e.id,e.getBoundingClientRect().width,e.getBoundingClientRect().right]).slice(0,25)"))
                await page.screenshot(path='.cache/version-mobile-overflow.png', full_page=True)
            assert not overflow, f'Débordement de l’onglet Version à {width}px'
        assert not errors, errors
        await browser.close()
        print('UI mises à jour OK : accueil général, Version, silence à jour/hors ligne, report, installation, échec, thèmes et tailles.')


if __name__ == '__main__': asyncio.run(main())
