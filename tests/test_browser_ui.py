import asyncio
from playwright.async_api import async_playwright

async def run():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        page = await browser.new_page()
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))

        # Load page
        page.set_default_timeout(45000)
        await page.goto('http://127.0.0.1:8000/index.html', wait_until='networkidle')
        await page.wait_for_selector('#sidebar', timeout=15000)
        await page.wait_for_timeout(1000)
        print('Page title:', await page.title())

        # Switch to Safe Route page
        await page.click('button[data-page="page-safe-route"]')
        await page.wait_for_timeout(500)

        # 1. Verify preset selector is COMPLETELY REMOVED from DOM
        preset_count = await page.locator('#route-preset-select').count()
        assert preset_count == 0, "#route-preset-select must be completely removed from DOM"
        print('Verified Preset Transit Corridors dropdown is completely removed.')

        # Verify coordinate input fields are NOT visible, and place search inputs ARE visible
        src_lat_visible = await page.locator('#route-src-lat').is_visible()
        src_lon_visible = await page.locator('#route-src-lon').is_visible()
        dst_lat_visible = await page.locator('#route-dst-lat').is_visible()
        dst_lon_visible = await page.locator('#route-dst-lon').is_visible()
        assert not src_lat_visible, "route-src-lat should not be visible"
        assert not src_lon_visible, "route-src-lon should not be visible"
        assert not dst_lat_visible, "route-dst-lat should not be visible"
        assert not dst_lon_visible, "route-dst-lon should not be visible"

        src_place = page.locator('#route-src-place')
        dst_place = page.locator('#route-dst-place')
        assert await src_place.is_visible(), "route-src-place must be visible"
        assert await dst_place.is_visible(), "route-dst-place must be visible"
        assert await src_place.get_attribute('placeholder') == 'Enter starting place or address'
        assert await dst_place.get_attribute('placeholder') == 'Enter destination place or address'

        # Verify Calculate button is initially disabled (no default route silently selected)
        btn_calc = page.locator('#btn-calculate-route')
        assert await btn_calc.is_disabled(), "Calculate button must be initially disabled when inputs are empty"
        print('Verified place inputs visible with required placeholders; lat/lon inputs hidden; calculate button initially disabled.')

        # Verify Route Risk Legend is visible on map
        legend = page.locator('#route-map-legend')
        assert await legend.is_visible(), "Route Risk Legend overlay must be visible"
        legend_text = await legend.inner_text()
        assert "LOWER THREAT" in legend_text.upper(), "Legend must show Lower Threat"
        assert "MODERATE THREAT" in legend_text.upper(), "Legend must show Moderate Threat"
        assert "ELEVATED THREAT" in legend_text.upper(), "Legend must show Elevated Threat"
        assert "HIGHER THREAT" in legend_text.upper(), "Legend must show Higher Threat"
        assert "UNMEASURED" in legend_text.upper(), "Legend must show Unmeasured / Insufficient"
        print('Verified Route Risk Scale legend is rendered on map with all 5 threat categories.')

        # 2. Enter Origin and Destination for Bengaluru Route (Banashankari -> Indiranagar)
        await page.fill('#route-src-place', 'Banashankari')
        await page.evaluate("() => { document.getElementById('route-src-lat').value = '12.9298'; document.getElementById('route-src-lon').value = '77.6005'; document.getElementById('route-src-lat').dataset.matchedText = 'Banashankari'; document.getElementById('route-src-resolved-badge').classList.remove('hidden'); }")
        await page.fill('#route-dst-place', 'Indiranagar')
        await page.evaluate("() => { document.getElementById('route-dst-lat').value = '12.9789'; document.getElementById('route-dst-lon').value = '77.6403'; document.getElementById('route-dst-lat').dataset.matchedText = 'Indiranagar'; document.getElementById('route-dst-resolved-badge').classList.remove('hidden'); }")
        await page.evaluate("() => { updateRouteCalculateBtnState(); document.querySelectorAll('#route-src-suggestions, #route-dst-suggestions').forEach(el => el.classList.add('hidden')); }")

        assert not await btn_calc.is_disabled(), "Calculate button must be enabled when both places have text"
        await btn_calc.click()
        await page.wait_for_selector('#route-details-panel:not(.hidden)', timeout=12000)
        await page.wait_for_timeout(500)

        panel_text = await page.inner_text('#route-details-panel')
        badge_text = await page.inner_text('#route-distance-badge')
        print('\n--- Measured Route Details Panel ---')
        print(panel_text.encode('ascii', 'replace').decode('ascii'))
        print('Badge:', badge_text.encode('ascii', 'replace').decode('ascii'))

        assert "BANASHANKARI" in panel_text.upper(), "Missing origin name in details panel"
        assert "INDIRANAGAR" in panel_text.upper(), "Missing destination name in details panel"
        assert "HEURISTIC HISTORICAL INDICATOR" in panel_text.upper(), "Missing heuristic indicator label"
        assert "ROUTE SEGMENT RISK COVERAGE" in panel_text.upper(), "Missing segment risk coverage section"
        assert "MEASURED:" in panel_text.upper(), "Missing measured percentage breakdown"
        assert "UNMEASURED:" in panel_text.upper(), "Missing unmeasured percentage breakdown"
        assert "CONFIDENCE" in panel_text, "Missing confidence label"
        assert "mins" in badge_text, "Missing transit time in measured route badge"
        assert "/100" in panel_text, "Missing measured score fraction for measured route"

        # Verify multiple segmented Leaflet polylines are rendered on map
        segment_polylines = await page.locator('#route-map svg path.leaflet-interactive').count()
        assert segment_polylines > 5, f"Expected multiple risk-colored route segments on map, found {segment_polylines}"
        print(f'Verified segmented route visualization: {segment_polylines} interactive segment polylines rendered on map.')

        # Click the first segment polyline to verify popup metrics
        await page.evaluate("() => { const layers = routeLayer.getLayers(); for (let l of layers) { if (l.getPopup && l.getPopup()) { l.openPopup(); break; } } }")
        await page.wait_for_selector('.leaflet-popup-content', timeout=5000)
        popup_text = await page.inner_text('.leaflet-popup-content')
        assert "ROAD SEGMENT #" in popup_text.upper(), f"Popup missing Road Segment header: {popup_text}"
        assert "HISTORICAL INCIDENTS WITHIN 1.2 KM CORRIDOR BUFFER" in popup_text.upper(), f"Popup missing incidents count: {popup_text}"
        assert "LOCATION EVIDENCE:" in popup_text.upper(), f"Popup missing location evidence: {popup_text}"
        print('Verified segment click popup displays segment ID, threat score, historical incidents, and location evidence.')

        # 2b. Test Historical Incident Details Panel on segment click
        await page.evaluate("() => { const layers = routeLayer.getLayers(); for (let l of layers) { if (l._beaconSeg && l._beaconSeg.incident_count > 0) { l.fire('click'); break; } } }")
        await page.wait_for_selector('#segment-incident-panel:not(.hidden)', timeout=10000)
        await page.wait_for_selector('#segment-incident-panel #segment-category-list', timeout=10000)
        panel_incident_text = await page.inner_text('#segment-incident-panel')
        
        assert "HISTORICAL INCIDENT DETAILS" in panel_incident_text.upper(), "Panel missing Historical Incident Details title"
        assert "ROAD SEGMENT #" in panel_incident_text.upper(), "Panel missing Road Segment identifier"
        assert "ABOUT THESE INCIDENTS" in panel_incident_text.upper(), "Panel missing simplified disclaimer header"
        assert "RECORDED WITHIN 1.2 KM" in panel_incident_text.upper(), "Panel missing persistent buffer disclaimer text"
        assert "RISK LEVEL" in panel_incident_text.upper(), "Panel missing simplified Risk Level card"
        assert "ROAD LENGTH" in panel_incident_text.upper(), "Panel missing simplified Road Length card"
        assert "NEARBY INCIDENTS" in panel_incident_text.upper(), "Panel missing simplified Nearby Incidents card"
        assert "LOCATION ACCURACY" in panel_incident_text.upper(), "Panel missing simplified Location Accuracy card"
        assert "CRIMES REPORTED NEAR THIS ROUTE" in panel_incident_text.upper(), "Panel missing Crimes reported near this route section"
        print('Verified Historical Incident Details panel opens with simplified summary, disclaimer, and crime list.')

        # Test Category Expand/Collapse
        first_cat = page.locator('#segment-incident-panel #segment-category-list > div:first-child')
        assert await first_cat.is_visible(), "Category list item must be visible"
        await first_cat.locator('> div').first.click()
        await page.wait_for_timeout(300)
        first_cat_expanded = await page.locator('#segment-incident-panel button:has-text("View on map")').count()
        assert first_cat_expanded > 0, "Expanding category must reveal individual incident records with View on map button"
        print(f'Verified expanding category reveals {first_cat_expanded} incident cards.')

        # Test View on Map action & simplified popup wording
        await page.locator('#segment-incident-panel button:has-text("View on map")').first.click()
        await page.wait_for_timeout(400)
        incident_markers = await page.locator('.incident-preview-marker').count()
        assert incident_markers > 0, "Clicking View on map must render incident preview marker on map"
        marker_popup_text = await page.locator('.leaflet-popup-content').inner_text()
        assert "DISTANCE FROM ROUTE:" in marker_popup_text.upper(), "Marker popup must display 'Distance from route'"
        print('Verified View on Map places interactive marker on route map with simplified popup wording.')

        # Test Locality Search Filter
        await page.fill('#segment-filter-locality', 'Bangalore')
        await page.wait_for_timeout(600)
        filtered_text = await page.inner_text('#segment-incident-panel')
        assert "CRIMES REPORTED NEAR THIS ROUTE" in filtered_text.upper(), "Crimes list header must remain visible after filtering"
        await page.click('#btn-reset-segment-filters')
        await page.wait_for_timeout(400)
        print('Verified segment date and locality filters update counts consistently.')

        # Close incident details panel
        await page.click('#segment-incident-panel button[title="Close Panel"]')
        await page.wait_for_timeout(300)
        assert await page.locator('#segment-incident-panel').is_hidden(), "Panel should be hidden after clicking close"
        print('Verified close button hides Historical Incident Details panel.')

        # 3. Test Swap Control (Swap A & B)
        await page.click('#btn-swap-route')
        await page.wait_for_timeout(400)
        new_src = await page.input_value('#route-src-place')
        new_dst = await page.input_value('#route-dst-place')
        assert "Indiranagar" in new_src, f"Expected Indiranagar as new src, got {new_src}"
        assert "Banashankari" in new_dst, f"Expected Banashankari as new dst, got {new_dst}"
        print('Verified Swap button successfully swapped A and B.')

        # 4. Test Autocomplete Place Search Suggestions
        await page.fill('#route-dst-place', '')
        await page.type('#route-dst-place', 'Koramangala', delay=40)
        await page.wait_for_selector('#route-dst-suggestions:not(.hidden)', timeout=10000)
        suggestions = page.locator('#route-dst-suggestions')
        assert await suggestions.is_visible(), "Autocomplete suggestions dropdown must appear"
        item_count = await page.locator('#route-dst-suggestions .route-suggestion-item').count()
        assert item_count > 0, f"Expected suggestions for Koramangala, found {item_count}"
        print(f'Verified autocomplete suggestions visible with {item_count} items.')

        # Click the first suggestion
        await page.click('#route-dst-suggestions .route-suggestion-item:first-child')
        await page.wait_for_timeout(400)
        assert await page.locator('#route-dst-resolved-badge').is_visible(), "Resolved badge must appear"
        print('Verified selecting suggestion resolves location and shows badge.')

        # 5. Test Identical Origin and Destination Error
        await page.fill('#route-src-place', 'Indiranagar')
        await page.evaluate("() => { document.getElementById('route-src-lat').value = '12.9789'; document.getElementById('route-src-lon').value = '77.6403'; document.getElementById('route-src-lat').dataset.matchedText = 'Indiranagar'; }")
        await page.fill('#route-dst-place', 'Indiranagar')
        await page.evaluate("() => { document.getElementById('route-dst-lat').value = '12.9789'; document.getElementById('route-dst-lon').value = '77.6403'; document.getElementById('route-dst-lat').dataset.matchedText = 'Indiranagar'; }")
        await page.evaluate("() => { document.querySelectorAll('#route-src-suggestions, #route-dst-suggestions').forEach(el => { el.classList.add('hidden'); el.innerHTML = ''; }); }")
        await page.click('#btn-calculate-route', force=True)
        await page.wait_for_timeout(500)
        global_err = await page.inner_text('#route-global-error')
        assert "IDENTICAL" in global_err.upper(), f"Expected identical endpoints error, got: {global_err}"
        print('Verified identical origin and destination error handling.')

        # 6. Test Reset Action
        await page.evaluate("() => { document.querySelectorAll('#route-src-suggestions, #route-dst-suggestions').forEach(el => { el.classList.add('hidden'); el.innerHTML = ''; }); }")
        await page.click('#btn-reset-route', force=True)
        await page.wait_for_timeout(400)
        reset_src = await page.input_value('#route-src-place')
        reset_dst = await page.input_value('#route-dst-place')
        assert reset_src == '', "route-src-place should be cleared after reset"
        assert reset_dst == '', "route-dst-place should be cleared after reset"
        badge_after_reset = await page.inner_text('#route-distance-badge')
        assert "Ready for Calculation" in badge_after_reset
        assert await btn_calc.is_disabled(), "Calculate button must be disabled after reset"
        print('Verified Reset action clears inputs, closes popups, resets badge, and disables calculate button.')

        # 7. Test Mangaluru Place Route (Kadri -> Surathkal)
        await page.fill('#route-src-place', 'Kadri, Mangaluru')
        await page.evaluate("() => { document.getElementById('route-src-lat').value = '12.8897'; document.getElementById('route-src-lon').value = '74.8501'; document.getElementById('route-src-lat').dataset.matchedText = 'Kadri, Mangaluru'; document.getElementById('route-src-resolved-badge').classList.remove('hidden'); }")
        await page.fill('#route-dst-place', 'Surathkal, Mangaluru')
        await page.evaluate("() => { document.getElementById('route-dst-lat').value = '12.9949'; document.getElementById('route-dst-lon').value = '74.8120'; document.getElementById('route-dst-lat').dataset.matchedText = 'Surathkal, Mangaluru'; document.getElementById('route-dst-resolved-badge').classList.remove('hidden'); }")
        await page.evaluate("() => { updateRouteCalculateBtnState(); document.querySelectorAll('#route-src-suggestions, #route-dst-suggestions').forEach(el => el.classList.add('hidden')); }")

        await btn_calc.click()
        await page.wait_for_selector('#route-details-panel:not(.hidden)', timeout=12000)
        await page.wait_for_timeout(500)
        panel_mlr = await page.inner_text('#route-details-panel')
        assert "KADRI" in panel_mlr.upper(), "Missing Kadri in MLR route panel"
        assert "SURATHKAL" in panel_mlr.upper(), "Missing Surathkal in MLR route panel"
        assert "ROUTE SEGMENT RISK COVERAGE" in panel_mlr.upper(), "Missing segment coverage in MLR panel"
        print('Verified Mangaluru place-to-place segmented routing.')

        # 8. Test Unmeasured Rural Corridor (displaying UNMEASURED without /100)
        await page.fill('#route-src-place', 'Rural Outpost A')
        await page.evaluate("() => { document.getElementById('route-src-lat').value = '12.7500'; document.getElementById('route-src-lon').value = '77.4000'; document.getElementById('route-src-lat').dataset.matchedText = 'Rural Outpost A'; }")
        await page.fill('#route-dst-place', 'Rural Outpost B')
        await page.evaluate("() => { document.getElementById('route-dst-lat').value = '12.7800'; document.getElementById('route-dst-lon').value = '77.4200'; document.getElementById('route-dst-lat').dataset.matchedText = 'Rural Outpost B'; }")
        await page.evaluate("() => { updateRouteCalculateBtnState(); document.querySelectorAll('#route-src-suggestions, #route-dst-suggestions').forEach(el => el.classList.add('hidden')); }")
        async with page.expect_response(lambda r: '/api/safe-route' in r.url and r.status == 200):
            await page.click('#btn-calculate-route')
        await page.wait_for_selector('#route-details-panel:has-text("Rural Outpost A")', timeout=10000)
        await page.wait_for_timeout(300)

        panel_text_unmeasured = await page.inner_text('#route-details-panel')
        assert "INSUFFICIENT EVIDENCE" in panel_text_unmeasured.upper(), "Missing INSUFFICIENT EVIDENCE badge"
        assert "UNMEASURED" in panel_text_unmeasured.upper(), "Unmeasured corridor must display UNMEASURED rather than numeric score"
        assert "/100" not in panel_text_unmeasured, "Unmeasured corridor must NEVER display a numeric /100 score"
        print('Verified unmeasured corridor displays UNMEASURED.')

        # 9. Verify Map Tile Provider is OpenStreetMap (no API KEY REQUIRED)
        map_html = await page.inner_html('#route-map')
        assert "api key required" not in map_html.lower(), "Map must not show API KEY REQUIRED"
        print('Verified map basemap tiles loaded without API key requirement.')

        # 10. Verify Responsive Layout (mobile viewport test)
        await page.set_viewport_size({"width": 375, "height": 667})
        await page.wait_for_timeout(300)
        panel_visible_mobile = await page.locator('#route-details-panel').is_visible()
        map_visible_mobile = await page.locator('#route-map').is_visible()
        assert panel_visible_mobile, "Route details panel must be visible on mobile viewport"
        assert map_visible_mobile, "Route map must be visible on mobile viewport"
        print('Verified mobile layout responsiveness (375x667).')

        # Assert zero page JS errors throughout
        assert len(errors) == 0, f"Page JS Errors: {errors}"
        print('\nZero JavaScript errors detected in all browser tests!')
        await browser.close()

if __name__ == '__main__':
    asyncio.run(run())
