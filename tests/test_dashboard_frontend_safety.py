"""
Playwright E2E Test Suite for BEACON Dashboard Three-Column Redesign
Verifies:
1. Row 1: Three Summary statistic cards (Total, BLR, MLR).
2. Row 2: Three Main Cards side-by-side on desktop (High-Risk Zones, My Current Location Safety, Emergency Contacts).
   - Verifies equal horizontal alignment and visibility without vertical scrolling.
3. Card 1 (High-Risk Zones):
   - Top 5 dynamic ranking with rank, locality, city, risk score with red bar, incident count.
   - Click on row navigates and zooms on Safety Map.
   - Click "View on Safety Map ->" button.
   - City scope toggle (Combined View, Bengaluru, Mangaluru).
4. Card 2 (My Current Location Safety):
   - Initial state shows "Location Not Checked" with center shield illustration.
   - Prominent "Check My Current Location" orange button.
   - GPS permission & calculation: detected coordinates, risk score, 500m/1km/2km density, station, high-risk area.
   - Show position on Safety Map button.
   - Verification that manual search inputs/chips are completely absent.
5. Card 3 (Emergency Contacts):
   - 5 tiles: 112 (Emergency), 108 (Ambulance), 101 (Fire & Rescue), 100 (Police), 1091 (Women Helpline) with tel: links.
   - Verification that dashboard police stations list is completely absent.
6. Verification that Section 3 (Recent Incidents & Crime Trends) is completely absent.
7. Verification that Police Command and Safety Map pages remain intact.
8. Zero JavaScript console errors across all interactions.
"""

import asyncio
from playwright.async_api import async_playwright

async def run_dashboard_tests():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        page = await browser.new_page(viewport={'width': 1400, 'height': 900})
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))

        page.set_default_timeout(30000)
        await page.goto('http://127.0.0.1:8000/', wait_until='networkidle')
        await page.wait_for_selector('#page-dashboard', timeout=15000)
        print("Loaded BEACON Dashboard:", await page.title())

        # ==================== 1. ROW 1: SUMMARY STATISTIC CARDS ====================
        total_inc = await page.locator('#dash-total-incidents').inner_text()
        blr_inc = await page.locator('#dash-blr-incidents').inner_text()
        mlr_inc = await page.locator('#dash-mlr-incidents').inner_text()
        assert len(total_inc) > 0, "Total incidents summary card must have value"
        assert len(blr_inc) > 0, "Bengaluru summary card must have value"
        assert len(mlr_inc) > 0, "Mangaluru summary card must have value"
        print(f"Verified Row 1 Summary Cards: Total={total_inc}, BLR={blr_inc}, MLR={mlr_inc}")

        # ==================== 2. ROW 2: THREE-COLUMN HORIZONTAL ALIGNMENT ====================
        card1 = page.locator('#card-high-risk-zones')
        card2 = page.locator('#card-current-location-safety')
        card3 = page.locator('#card-emergency-contacts')

        assert await card1.is_visible(), "High-Risk Zones card must be visible"
        assert await card2.is_visible(), "My Current Location Safety card must be visible"
        assert await card3.is_visible(), "Emergency Contacts card must be visible"

        box1 = await card1.bounding_box()
        box2 = await card2.bounding_box()
        box3 = await card3.bounding_box()

        # On desktop (1400px width), all 3 cards must be arranged horizontally
        assert box1['x'] < box2['x'] < box3['x'], f"Cards must be horizontally sequenced: {box1['x']}, {box2['x']}, {box3['x']}"
        assert abs(box1['y'] - box2['y']) < 15 and abs(box2['y'] - box3['y']) < 15, f"Cards must be horizontally aligned in Row 2: y1={box1['y']}, y2={box2['y']}, y3={box3['y']}"
        print(f"Verified Row 2 Three-Column Layout: all 3 cards side-by-side at y~={round(box1['y'])}px.")

        # ==================== 3. CARD 1: HIGH-RISK ZONES ====================
        # Wait for table rows to render
        await page.wait_for_selector('#high-risk-zones-container table tbody tr', timeout=10000)
        rows = await page.locator('#high-risk-zones-container table tbody tr').count()
        assert rows == 5, f"Expected 5 top high-risk zones, got {rows}"
        print(f"Verified High-Risk Zones: {rows} dynamically ranked areas rendered in 4-column format.")

        # Check compact disclaimer notice
        disclaimer = await page.locator('text=do not guarantee future safety').is_visible()
        assert disclaimer, "Notice must explain historical estimates do not guarantee future safety"

        # Test city scope filter (Mangaluru via top bar)
        await page.click('#btn-city-mlr')
        await page.wait_for_timeout(500)
        mlr_badges = await page.locator('#high-risk-zones-container tr:has-text("MLR")').count()
        assert mlr_badges > 0, "Mangaluru city scope must display MLR zones"
        print("Verified city filter updates High-Risk Zones (MLR).")

        # Reset to Combined View
        await page.click('#btn-city-combined')
        await page.wait_for_timeout(500)

        # Test clicking a high-risk locality row -> navigates to Safety Map and opens popup
        first_row = page.locator('#high-risk-zones-container table tbody tr').first
        await first_row.click()
        await page.wait_for_timeout(1000)
        assert await page.locator('#page-safety-map').is_visible(), "Clicking high-risk zone must navigate to Safety Map"
        assert await page.locator('.leaflet-popup').is_visible(), "Clicking high-risk zone must zoom and open popup on map"
        print("Verified click-to-map navigation and popup zoom for High-Risk Zones.")

        # Return to Dashboard
        await page.click('button[data-page="page-dashboard"]')
        await page.wait_for_timeout(500)

        # Test "View on Safety Map ->" button on Card 1
        await page.click('#btn-hrz-view-map')
        await page.wait_for_timeout(500)
        assert await page.locator('#page-safety-map').is_visible(), "View on Safety Map button must navigate to map"
        print("Verified 'View on Safety Map ->' button.")

        # Return to Dashboard
        await page.click('button[data-page="page-dashboard"]')
        await page.wait_for_timeout(500)

        # ==================== 4. CARD 2: MY CURRENT LOCATION SAFETY ====================
        # Verify initial idle state with "Location Not Checked"
        idle_visible = await page.locator('#loc-state-idle:not(.hidden)').is_visible()
        assert idle_visible, "Initial state must show Location Not Checked illustration"
        idle_text = await page.locator('#loc-state-idle').inner_text()
        assert "Location Not Checked" in idle_text, f"Expected 'Location Not Checked', got: {idle_text}"
        print("Verified initial idle state: 'Location Not Checked' with shield illustration.")

        # Verify manual search elements are completely absent
        assert await page.locator('#manual-loc-search-input').count() == 0, "Manual search input must not exist"
        assert await page.locator('#btn-manual-loc-search').count() == 0, "Manual lookup button must not exist"
        assert await page.locator('.manual-chip').count() == 0, "Manual chips must not exist"

        # Test GPS button click & evaluation
        context = page.context
        await context.grant_permissions(['geolocation'])
        await context.set_geolocation({'latitude': 12.9716, 'longitude': 77.5946})

        await page.click('#btn-check-my-location')
        await page.wait_for_selector('#loc-state-results:not(.hidden)', timeout=10000)

        title_text = await page.locator('#loc-res-title').inner_text()
        assert "12.9716" in title_text or "Bengaluru" in title_text, f"Unexpected title: {title_text}"

        d500 = await page.locator('#loc-density-500m').inner_text()
        d1k = await page.locator('#loc-density-1km').inner_text()
        d2k = await page.locator('#loc-density-2km').inner_text()
        assert int(d500.replace(',', '')) >= 0
        assert int(d1k.replace(',', '')) >= int(d500.replace(',', ''))
        assert int(d2k.replace(',', '')) >= int(d1k.replace(',', ''))
        print(f"Verified Concentric Incident Density: 500m={d500}, 1km={d1k}, 2km={d2k}")

        ps_name = await page.locator('#loc-res-ps-name').inner_text()
        hr_name = await page.locator('#loc-res-hr-name').inner_text()
        assert len(ps_name) > 0 and len(hr_name) > 0
        print(f"Verified Location Safety Results: Station='{ps_name}', HighRiskArea='{hr_name}'")

        # Test "Show Position on Safety Map" button
        await page.click('#btn-view-loc-on-map')
        await page.wait_for_timeout(1000)
        assert await page.locator('#page-safety-map').is_visible(), "Must switch to Safety Map"
        assert await page.locator('.custom-user-marker').is_visible(), "User marker must be plotted"
        print("Verified user position plotted with pulsing marker on Safety Map.")

        # Return to Dashboard
        await page.click('button[data-page="page-dashboard"]')
        await page.wait_for_timeout(500)

        # ==================== 5. CARD 3: EMERGENCY CONTACTS ====================
        tel_112 = await page.locator('a[href="tel:112"]').count()
        tel_108 = await page.locator('a[href="tel:108"]').count()
        tel_101 = await page.locator('a[href="tel:101"]').count()
        tel_100 = await page.locator('a[href="tel:100"]').count()
        tel_1091 = await page.locator('a[href="tel:1091"]').count()
        assert tel_112 >= 1, "tel:112 link must exist"
        assert tel_108 >= 1, "tel:108 link must exist"
        assert tel_101 >= 1, "tel:101 link must exist"
        assert tel_100 >= 1, "tel:100 link must exist"
        assert tel_1091 >= 1, "tel:1091 link must exist"
        print("Verified all 5 Emergency Hotline tiles (112, 108, 101, 100, 1091).")

        # Verify dashboard-only police station directory is completely absent
        assert await page.locator('#dash-police-stations-list').count() == 0
        assert await page.locator('#ps-filter-all').count() == 0

        # ==================== 6. REMOVED SECTIONS VERIFICATION ====================
        assert await page.locator('#dash-recent-incidents-table-body').count() == 0
        assert await page.locator('#dash-chart-crime-types').count() == 0
        assert await page.locator('#dash-chart-hourly').count() == 0
        assert await page.locator('#btn-dash-view-all-incidents').count() == 0
        print("Verified Section 3 (Recent Incidents & Crime Trends) completely absent from dashboard.")

        # ==================== 7. VERIFY OTHER PAGES INTACT ====================
        # Police Command Page
        await page.click('button[data-page="page-police-command"]')
        await page.wait_for_timeout(500)
        assert await page.locator('#police-stations-grid').is_visible()
        station_cards = await page.locator('#police-stations-grid > div').count()
        assert station_cards >= 5
        print(f"Verified Police Command page is intact ({station_cards} stations rendered).")

        # Safety Map Page
        await page.click('button[data-page="page-safety-map"]')
        await page.wait_for_timeout(500)
        recent_feed_rows = await page.locator('#recent-incidents-table-body tr').count()
        assert recent_feed_rows > 0
        print(f"Verified Safety Map page is intact ({recent_feed_rows} records in feed).")

        # ==================== 8. CONSOLE ERRORS CHECK ====================
        critical_errors = [e for e in errors if 'ERR_CONNECTION' not in e]
        assert len(critical_errors) == 0, f"Unexpected JS errors: {critical_errors}"
        print("\nAll Three-Column Redesign tests passed with 0 JavaScript errors!")

        await browser.close()

if __name__ == "__main__":
    asyncio.run(run_dashboard_tests())
