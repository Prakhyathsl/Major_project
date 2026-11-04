import asyncio
from playwright.async_api import async_playwright

async def run_tests():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        page = await browser.new_page(viewport={'width': 1400, 'height': 900})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))

        page.set_default_timeout(45000)
        await page.goto('http://127.0.0.1:8000/', wait_until='domcontentloaded')
        await page.wait_for_selector('#page-dashboard', timeout=20000)
        await page.wait_for_timeout(1000)
        print("Loaded page:", await page.title())

        # ==================== 1. VERIFY THEME TOGGLE BUTTON ====================
        toggle_btn = page.locator('#btn-theme-toggle')
        assert await toggle_btn.is_visible(), "Theme toggle button must be visible in header"
        sun_icon = page.locator('#theme-icon-sun')
        moon_icon = page.locator('#theme-icon-moon')
        
        # Initial dark mode state
        is_dark = await page.evaluate("() => document.documentElement.classList.contains('dark')")
        assert is_dark, "Initial theme must be dark"
        assert await sun_icon.is_visible(), "Sun icon must be visible in dark mode"
        assert await moon_icon.is_hidden(), "Moon icon must be hidden in dark mode"
        print("Verified initial dark mode state.")

        # ==================== 2. TOGGLE TO LIGHT MODE ====================
        await toggle_btn.click()
        await page.wait_for_timeout(400)

        is_light = await page.evaluate("() => document.documentElement.classList.contains('light')")
        theme_attr = await page.evaluate("() => document.documentElement.getAttribute('data-theme')")
        saved_theme = await page.evaluate("() => localStorage.getItem('beacon-theme')")
        assert is_light, "Class 'light' must be added to <html>"
        assert theme_attr == 'light', "data-theme must be 'light'"
        assert saved_theme == 'light', "localStorage beacon-theme must be 'light'"
        assert await sun_icon.is_hidden(), "Sun icon must be hidden in light mode"
        assert await moon_icon.is_visible(), "Moon icon must be visible in light mode"

        # Check body and card computed background color in light mode
        body_bg = await page.evaluate("() => window.getComputedStyle(document.body).backgroundColor")
        card_bg = await page.evaluate("() => window.getComputedStyle(document.querySelector('.tactical-card')).backgroundColor")
        print(f"Light mode colors: body_bg={body_bg}, card_bg={card_bg}")
        assert "248, 250, 252" in body_bg or "255, 255, 255" in body_bg, f"Unexpected body_bg: {body_bg}"
        assert "255, 255, 255" in card_bg, f"Card should be white in light mode, got: {card_bg}"
        print("Verified Light Mode styles applied cleanly to body and cards.")

        # ==================== 3. VERIFY PERSISTENCE ON RELOAD ====================
        await page.reload(wait_until='domcontentloaded')
        await page.wait_for_selector('#page-dashboard', timeout=20000)
        await page.wait_for_timeout(500)
        reloaded_light = await page.evaluate("() => document.documentElement.classList.contains('light')")
        reloaded_saved = await page.evaluate("() => localStorage.getItem('beacon-theme')")
        assert reloaded_light, "Theme must persist as 'light' after reload"
        assert reloaded_saved == 'light', "localStorage must retain 'light'"
        print("Verified theme persistence across page reload.")

        # ==================== 4. TEST ALL PAGES IN LIGHT MODE ====================
        # AI Risk Analysis
        await page.click('button[data-page="page-risk-analysis"]')
        await page.wait_for_timeout(400)
        assert await page.locator('#page-risk-analysis').is_visible()
        risk_input_bg = await page.evaluate("() => window.getComputedStyle(document.querySelector('#risk-input-hour')).backgroundColor")
        print("AI Risk input background in light mode:", risk_input_bg)

        # Safe Route
        await page.click('button[data-page="page-safe-route"]')
        await page.wait_for_timeout(400)
        assert await page.locator('#page-safe-route').is_visible()

        # Crime Analytics
        await page.click('button[data-page="page-crime-analytics"]')
        await page.wait_for_timeout(400)
        assert await page.locator('#page-crime-analytics').is_visible()

        # Police Command
        await page.click('button[data-page="page-police-command"]')
        await page.wait_for_timeout(400)
        assert await page.locator('#page-police-command').is_visible()
        print("Verified all pages switch cleanly in Light Mode.")

        # ==================== 5. SAFETY MAP & SIMPLIFIED POPUP ====================
        await page.click('button[data-page="page-safety-map"]')
        await page.wait_for_timeout(1000)
        assert await page.locator('#page-safety-map').is_visible()

        # Test popup rendering using renderIncidentPopup
        test_popup_html = await page.evaluate("""() => {
            const testRec = {
                id: 'BLR-2020-0042',
                crime_type: 'Motor Vehicle Theft',
                place: 'Indiranagar 100ft Road',
                police_station: 'Indiranagar Police Station',
                date: '2020-08-14',
                time: '21:30',
                city: 'Bengaluru',
                validation_status: 'LOCALITY_MATCH_ONLY',
                latitude: 12.9789,
                longitude: 77.6403
            };
            return renderIncidentPopup(testRec);
        }""")

        # Verify unwanted technical items are completely absent
        assert "LOCALITY CENTROID ONLY" not in test_popup_html, "Must NOT contain LOCALITY CENTROID ONLY"
        assert "GEOSPATIAL ACCURACY" not in test_popup_html.upper(), "Must NOT contain GEOSPATIAL ACCURACY"
        assert "GPS:" not in test_popup_html, "Must NOT contain raw GPS label"
        assert "12.9789" not in test_popup_html, "Must NOT contain raw latitude"
        assert "77.6403" not in test_popup_html, "Must NOT contain raw longitude"
        assert "centroid approximation" not in test_popup_html.lower(), "Must NOT contain centroid approximation explanation"

        # Verify required items are present
        assert "BLR-2020-0042" in test_popup_html, "Must contain incident ID"
        assert "Motor Vehicle Theft" in test_popup_html, "Must contain crime type"
        assert "Indiranagar 100ft Road" in test_popup_html, "Must contain recorded area"
        assert "Indiranagar Police Station" in test_popup_html, "Must contain jurisdiction"
        assert "2020-08-14" in test_popup_html, "Must contain recorded date"
        assert "21:30" in test_popup_html, "Must contain time"
        assert "Bengaluru" in test_popup_html or "BLR" in test_popup_html, "Must contain city badge"
        print("Verified simplified incident popup structure (zero technical clutter).")

        # Also test Mangaluru record in popup
        test_mlr_html = await page.evaluate("""() => {
            const testMlr = {
                id: 'MLR-2020-0105',
                crime_type: 'Burglary / Break-in',
                place: 'Kadri Temple Road',
                police_station: 'Kadri Police Station',
                date: '2020-11-02',
                time: '02:15',
                city: 'Mangaluru',
                latitude: 12.8897,
                longitude: 74.8501
            };
            return renderIncidentPopup(testMlr);
        }""")
        assert "LOCALITY CENTROID ONLY" not in test_mlr_html
        assert "GEOSPATIAL ACCURACY" not in test_mlr_html.upper()
        assert "MLR-2020-0105" in test_mlr_html
        assert "Burglary / Break-in" in test_mlr_html
        assert "Kadri Temple Road" in test_mlr_html
        assert "Mangaluru" in test_mlr_html
        print("Verified Mangaluru incident popup simplifies consistently.")

        # ==================== 6. TOGGLE BACK TO DARK MODE ====================
        await toggle_btn.click()
        await page.wait_for_timeout(400)
        is_dark_again = await page.evaluate("() => document.documentElement.classList.contains('dark')")
        saved_theme_again = await page.evaluate("() => localStorage.getItem('beacon-theme')")
        assert is_dark_again, "Class 'dark' must be restored"
        assert saved_theme_again == 'dark', "localStorage must be updated to 'dark'"
        assert await sun_icon.is_visible(), "Sun icon must be visible in dark mode"
        assert await moon_icon.is_hidden(), "Moon icon must be hidden in dark mode"
        print("Verified toggle back to Dark Mode.")

        # Zero console errors
        critical_errors = [e for e in errors if 'ERR_CONNECTION' not in e]
        assert len(critical_errors) == 0, f"Unexpected JS errors: {critical_errors}"
        print("\nAll Theme and Simplified Popup tests passed with 0 JavaScript errors!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run_tests())
