import asyncio
from playwright.async_api import async_playwright

async def run_e2e():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        page = await browser.new_page(viewport={'width': 1600, 'height': 950})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))

        page.set_default_timeout(60000)
        print("Navigating to http://127.0.0.1:8000/ ...")
        await page.goto('http://127.0.0.1:8000/', wait_until='domcontentloaded')
        await page.wait_for_selector('#page-dashboard', timeout=20000)
        await page.wait_for_timeout(1000)

        # 1. Navigate to Safety Map
        print("Navigating to Safety Map...")
        await page.click('button[data-page="page-safety-map"]')
        await page.wait_for_selector('#page-safety-map', state='visible')
        await page.wait_for_timeout(2000)

        # 2. Switch to Bengaluru Scope
        blr_btn = page.locator('button.city-btn[data-city="bengaluru"]')
        await blr_btn.click()
        print("Clicked Bengaluru scope button...")

        # Wait for all 5,023 approximate markers to load and strip to update
        await page.wait_for_function("""() => {
            const el = document.getElementById('strip-plotted-count');
            return el && el.textContent.includes('5,023');
        }""", timeout=30000)
        print("Verified strip-plotted-count displays 5,023.")

        # Check the other strip counters
        unverified_txt = await page.locator('#strip-unverified-count').text_content()
        station_txt = await page.locator('#strip-station-count').text_content()
        mismatch_txt = await page.locator('#strip-mismatch-count').text_content()
        total_txt = await page.locator('#strip-total-records').text_content()

        print(f"Audit Strip: Approx Plotted=5,023 | Unverified={unverified_txt} | Station={station_txt} | Mismatch={mismatch_txt} | Total={total_txt}")
        assert "2,925" in unverified_txt, f"Expected 2,925 unverified excluded, got {unverified_txt}"
        assert "1,001" in station_txt, f"Expected 1,001 station references, got {station_txt}"
        assert "910" in mismatch_txt, f"Expected 910 mismatch, got {mismatch_txt}"
        assert "9,859" in total_txt, f"Expected 9,859 total records, got {total_txt}"

        # 3. Verify Leaflet markers and cluster count
        cluster_count = await page.evaluate("() => markersLayer.getLayers().length")
        print(f"Leaflet markersLayer count: {cluster_count}")
        assert cluster_count == 5023, f"Expected exactly 5,023 markers, got {cluster_count}"

        # 4. Inspect an individual marker and its popup
        popup_html = await page.evaluate("""() => {
            const firstLayer = markersLayer.getLayers()[0];
            return firstLayer.getPopup().getContent();
        }""")

        assert "Approximate Location" in popup_html, "Popup must display 'Approximate Location' badge"
        assert "Area-level record, not verified crime scene" in popup_html, "Popup must display approximate reference note"
        assert "LOCALITY CENTROID ONLY" not in popup_html, "Popup must not have deprecated technical centroid wording"
        print("Verified incident popup contains 'Approximate Location' badge and warning note.")

        # Take screenshot of Safety Map with Bengaluru Approximate Locality Markers
        await page.screenshot(path="C:/Users/Prakhyath S.L/.gemini/antigravity/brain/5caba494-934b-4cc7-9f1e-b2dcce7dbae8/bengaluru_approximate_markers_5023.png")
        print("Saved screenshot: bengaluru_approximate_markers_5023.png")

        # 5. Toggle Police Station References Layer ON
        station_toggle = page.locator('#toggle-station-markers')
        await station_toggle.check()
        print("Toggled police stations ON, waiting for station markers...")
        await page.wait_for_timeout(2500)

        station_count = await page.evaluate("() => policeStationsLayer.getLayers().length")
        print(f"policeStationsLayer marker count: {station_count}")
        assert station_count == 1001, f"Expected 1,001 station reference markers, got {station_count}"

        # Verify markersLayer count remained exactly 5023 (complete isolation!)
        cluster_count_after = await page.evaluate("() => markersLayer.getLayers().length")
        assert cluster_count_after == 5023, f"Incident markers count modified by station toggle! Got {cluster_count_after}"
        print("Verified police stations are isolated in separate layer and incident layer stays 5,023.")

        # Take screenshot of Station Reference Layer
        await page.screenshot(path="C:/Users/Prakhyath S.L/.gemini/antigravity/brain/5caba494-934b-4cc7-9f1e-b2dcce7dbae8/police_stations_isolated_layer.png")
        print("Saved screenshot: police_stations_isolated_layer.png")

        # Toggle Police Station References Layer OFF
        await station_toggle.uncheck()
        await page.wait_for_timeout(500)
        station_count_off = await page.evaluate("() => policeStationsLayer.getLayers().length")
        assert station_count_off == 0, f"Expected 0 station markers after toggling off, got {station_count_off}"
        print("Verified station markers removed when untoggled.")

        # 6. Test Crime Category Filter
        print("Filtering by crime category THEFT...")
        await page.evaluate("() => filterMapByCrimeCategory('THEFT')")
        await page.wait_for_timeout(3000)

        filtered_count = await page.evaluate("() => markersLayer.getLayers().length")
        print(f"Filtered THEFT marker count: {filtered_count}")
        assert filtered_count > 0, "Expected non-zero theft markers"
        assert filtered_count < 5023, "Filtered count should be subset of 5,023"

        # Reset category filter back to all
        print("Resetting category filter to all...")
        await page.evaluate("() => filterMapByCrimeCategory('all')")
        await page.wait_for_timeout(3000)
        reset_count = await page.evaluate("() => markersLayer.getLayers().length")
        print(f"Reset marker count: {reset_count}")
        assert reset_count == 5023, f"Expected 5,023 markers restored, got {reset_count}"

        # 7. Test City Switching to Mangaluru and back
        mlr_btn = page.locator('button.city-btn[data-city="mangaluru"]')
        await mlr_btn.click()
        print("Switched to Mangaluru...")
        await page.wait_for_timeout(2500)

        mlr_plotted = await page.evaluate("() => markersLayer.getLayers().length")
        print(f"Mangaluru plotted count: {mlr_plotted}")
        assert mlr_plotted > 0, "Mangaluru markers must be plotted"

        # Switch back to Bengaluru
        await blr_btn.click()
        print("Switched back to Bengaluru...")
        await page.wait_for_timeout(3000)
        blr_restored = await page.evaluate("() => markersLayer.getLayers().length")
        print(f"Bengaluru restored count: {blr_restored}")
        assert blr_restored == 5023, f"Expected 5,023 Bengaluru markers restored, got {blr_restored}"

        assert len(errors) == 0, f"Encountered unexpected JS page errors: {errors}"
        print("ALL E2E SAFETY MAP TESTS PASSED WITH ZERO JAVASCRIPT ERRORS!")
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run_e2e())
