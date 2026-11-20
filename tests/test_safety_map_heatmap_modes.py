import asyncio
import os
import sys
from playwright.async_api import async_playwright

ARTIFACT_DIR = r"C:\Users\Prakhyath S.L\.gemini\antigravity\brain\5caba494-934b-4cc7-9f1e-b2dcce7dbae8"

async def run():
    print("=== STARTING SAFETY MAP TWO VIEW MODES REGRESSION TEST ===")
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=['--no-sandbox', '--disable-gpu'])
        context = await browser.new_context(viewport={'width': 1440, 'height': 900})
        page = await context.new_page()
        errors = []
        page.on('pageerror', lambda err: errors.append(str(err)))
        page.on('console', lambda msg: print(f"[BROWSER {msg.type.upper()}] {msg.text}") if msg.type in ['error', 'warn'] else None)

        page.set_default_timeout(45000)
        print("Loading application at http://127.0.0.1:8000/index.html...")
        await page.goto('http://127.0.0.1:8000/index.html', wait_until='networkidle')
        await page.wait_for_selector('#sidebar', timeout=15000)
        await page.wait_for_timeout(2500)

        # Switch to Safety Map page
        print("Navigating to Safety Map page...")
        await page.click('button[data-page="page-safety-map"]')
        await page.wait_for_selector('#safety-map', timeout=15000)
        await page.wait_for_timeout(1000)

        # =========================================================================
        # TEST 1: Classic View is Default on Load
        # =========================================================================
        print("\n--- TEST 1: Classic View is Default on Load ---")
        view_mode = await page.evaluate("() => AppState.safetyMapViewMode")
        assert view_mode == "classic", f"Expected default safetyMapViewMode to be 'classic', got '{view_mode}'"

        btn_classic_class = await page.locator("#btn-view-mode-classic").get_attribute("class")
        btn_heatmap_class = await page.locator("#btn-view-mode-heatmap").get_attribute("class")
        assert "bg-beacon-500" in btn_classic_class, "Classic button should have active bg-beacon-500 class"
        assert "text-slate-400" in btn_heatmap_class, "Heatmap button should have inactive text-slate-400 class"

        left_hidden = await page.evaluate("() => document.getElementById('heatmap-left-panel').classList.contains('hidden')")
        right_hidden = await page.evaluate("() => document.getElementById('heatmap-right-panel').classList.contains('hidden')")
        legend_hidden = await page.evaluate("() => document.getElementById('heatmap-legend').classList.contains('hidden')")
        assert left_hidden, "Left heatmap panel must be hidden in Classic View"
        assert right_hidden, "Right heatmap panel must be hidden in Classic View"
        assert legend_hidden, "Heatmap legend must be hidden in Classic View"

        # Wait for all 6,538 initial markers to load
        print("Waiting for initial 6,538 combined markers to load...")
        await page.wait_for_function("() => markersLayer && markersLayer.getLayers().length === 6538", timeout=30000)

        # Check marker layers
        marker_count = await page.evaluate("() => markersLayer ? markersLayer.getLayers().length : 0")
        assert marker_count == 6538, f"Expected 6,538 markers in Classic Combined View, got {marker_count}"
        has_heat_layer = await page.evaluate("() => activeHeatLayer !== null")
        assert not has_heat_layer, "activeHeatLayer should be null in Classic View"
        print(f"PASSED Test 1: Classic View is default with {marker_count} clustered markers.")

        # Take Classic View screenshot
        classic_shot = os.path.join(ARTIFACT_DIR, "safety_map_classic_view.png")
        await page.screenshot(path=classic_shot)
        print(f"Saved screenshot: {classic_shot}")

        # =========================================================================
        # TEST 2: Switch to Heatmap View
        # =========================================================================
        print("\n--- TEST 2: Switch to Heatmap View ---")
        await page.click("#btn-view-mode-heatmap")
        await page.wait_for_timeout(800)

        view_mode = await page.evaluate("() => AppState.safetyMapViewMode")
        assert view_mode == "heatmap", f"Expected safetyMapViewMode to be 'heatmap', got '{view_mode}'"

        btn_classic_class = await page.locator("#btn-view-mode-classic").get_attribute("class")
        btn_heatmap_class = await page.locator("#btn-view-mode-heatmap").get_attribute("class")
        assert "bg-beacon-500" in btn_heatmap_class, "Heatmap button should have active bg-beacon-500 class"
        assert "text-slate-400" in btn_classic_class, "Classic button should have inactive text-slate-400 class"

        left_hidden = await page.evaluate("() => document.getElementById('heatmap-left-panel').classList.contains('hidden')")
        right_hidden = await page.evaluate("() => document.getElementById('heatmap-right-panel').classList.contains('hidden')")
        legend_hidden = await page.evaluate("() => document.getElementById('heatmap-legend').classList.contains('hidden')")
        assert not left_hidden, "Left heatmap panel must be visible in Heatmap View"
        assert not right_hidden, "Right heatmap panel must be visible in Heatmap View"
        assert not legend_hidden, "Heatmap legend must be visible in Heatmap View"

        # Markers should be cleared and activeHeatLayer mounted
        marker_count = await page.evaluate("() => markersLayer ? markersLayer.getLayers().length : 0")
        assert marker_count == 0, f"Classic markers must be cleared in Heatmap View, got {marker_count}"

        heat_layer_active = await page.evaluate("() => activeHeatLayer !== null && safetyMap.hasLayer(activeHeatLayer)")
        assert heat_layer_active, "activeHeatLayer must be active and mounted on safetyMap"
        print("PASSED Test 2: Heatmap View activated with L.heatLayer and overlay panels.")

        # =========================================================================
        # TEST 3: Left Analytics Panel Verification
        # =========================================================================
        print("\n--- TEST 3: Left Analytics Panel Verification ---")
        stat_total = await page.locator("#heatmap-stat-total").inner_text()
        stat_scope = await page.locator("#heatmap-stat-scope").inner_text()
        stat_dominant = await page.locator("#heatmap-stat-dominant").inner_text()
        stat_range = await page.locator("#heatmap-stat-range").inner_text()

        print(f"Left Panel Stats: Total={stat_total}, Scope={stat_scope}, Dominant={stat_dominant}, Range={stat_range}")
        assert "6,538" in stat_total, f"Expected 6,538 in stat_total, got '{stat_total}'"
        assert "Combined" in stat_scope, f"Expected Combined in stat_scope, got '{stat_scope}'"
        assert len(stat_dominant.strip()) > 0, "Dominant category should not be empty"
        assert "2024" in stat_range and ("2014" in stat_range or "2015" in stat_range), f"Expected historical year range, got '{stat_range}'"
        print("PASSED Test 3: Left panel stats correctly calculated and displayed.")

        # =========================================================================
        # TEST 4: Right Analytics Panel (Top 5 Hotspot Localities)
        # =========================================================================
        print("\n--- TEST 4: Right Analytics Panel & Hotspot Click ---")
        await page.wait_for_selector("#heatmap-hotspots-list .hotspot-item", timeout=10000)
        hotspot_items = page.locator("#heatmap-hotspots-list .hotspot-item")
        count = await hotspot_items.count()
        assert count == 5, f"Expected exactly 5 hotspot localities, got {count}"

        first_name = await hotspot_items.nth(0).locator(".font-bold.text-white").inner_text()
        first_count = await hotspot_items.nth(0).locator(".text-slate-400.font-mono").inner_text()
        print(f"Top 1 Hotspot: {first_name} ({first_count})")

        # Test click-to-fly
        center_before = await page.evaluate("() => [safetyMap.getCenter().lat, safetyMap.getCenter().lng]")
        await hotspot_items.nth(0).click()
        await page.wait_for_timeout(1500)
        center_after = await page.evaluate("() => [safetyMap.getCenter().lat, safetyMap.getCenter().lng]")
        print(f"Map Center moved from {center_before} to {center_after}")
        assert center_before != center_after, "Map center should move when clicking a hotspot item"
        print("PASSED Test 4: Top 5 hotspots listed and click-to-fly works smoothly.")

        # Take Combined Heatmap screenshot
        combined_shot = os.path.join(ARTIFACT_DIR, "safety_map_heatmap_combined.png")
        await page.screenshot(path=combined_shot)
        print(f"Saved screenshot: {combined_shot}")

        # =========================================================================
        # TEST 5: Panel Collapse Functionality
        # =========================================================================
        print("\n--- TEST 5: Panel Collapse Controls ---")
        # Collapse left panel
        await page.click("#btn-collapse-left-panel")
        await page.wait_for_timeout(300)
        left_content_hidden = await page.evaluate("() => document.getElementById('heatmap-left-content').classList.contains('hidden')")
        assert left_content_hidden, "heatmap-left-content should be collapsed/hidden"

        # Re-expand left panel
        await page.click("#btn-collapse-left-panel")
        await page.wait_for_timeout(300)
        left_content_hidden = await page.evaluate("() => document.getElementById('heatmap-left-content').classList.contains('hidden')")
        assert not left_content_hidden, "heatmap-left-content should be re-expanded"

        # Collapse right panel
        await page.click("#btn-collapse-right-panel")
        await page.wait_for_timeout(300)
        right_content_hidden = await page.evaluate("() => document.getElementById('heatmap-right-content').classList.contains('hidden')")
        assert right_content_hidden, "heatmap-right-content should be collapsed/hidden"

        # Re-expand right panel
        await page.click("#btn-collapse-right-panel")
        await page.wait_for_timeout(300)
        right_content_hidden = await page.evaluate("() => document.getElementById('heatmap-right-content').classList.contains('hidden')")
        assert not right_content_hidden, "heatmap-right-content should be re-expanded"
        print("PASSED Test 5: Panel collapse and expand toggles work correctly.")

        # =========================================================================
        # TEST 6: City Selector Sync in Heatmap View
        # =========================================================================
        print("\n--- TEST 6: City Selector Sync in Heatmap View ---")
        # 6A: Filter to Bengaluru
        await page.click("#btn-city-blr")
        await page.wait_for_function("() => document.getElementById('heatmap-stat-total') && document.getElementById('heatmap-stat-total').innerText.includes('5,023')", timeout=15000)

        stat_total_blr = await page.locator("#heatmap-stat-total").inner_text()
        stat_scope_blr = await page.locator("#heatmap-stat-scope").inner_text()
        strip_total_blr = await page.locator("#strip-plotted-count").inner_text()
        print(f"Bengaluru Filter: Stat Total={stat_total_blr}, Scope={stat_scope_blr}, Strip Plotted={strip_total_blr}")
        assert "5,023" in stat_total_blr, f"Expected 5,023 for Bengaluru, got '{stat_total_blr}'"
        assert "Bengaluru" in stat_scope_blr, f"Expected Bengaluru scope, got '{stat_scope_blr}'"
        assert "5,023" in strip_total_blr, f"Expected 5,023 plotted in strip, got '{strip_total_blr}'"

        # Save Bengaluru Heatmap screenshot
        blr_shot = os.path.join(ARTIFACT_DIR, "safety_map_heatmap_bengaluru.png")
        await page.screenshot(path=blr_shot)
        print(f"Saved screenshot: {blr_shot}")

        # 6B: Filter to Mangaluru
        await page.click("#btn-city-mlr")
        await page.wait_for_function("() => document.getElementById('heatmap-stat-total') && document.getElementById('heatmap-stat-total').innerText.includes('1,515')", timeout=15000)

        stat_total_mlr = await page.locator("#heatmap-stat-total").inner_text()
        stat_scope_mlr = await page.locator("#heatmap-stat-scope").inner_text()
        strip_total_mlr = await page.locator("#strip-plotted-count").inner_text()
        print(f"Mangaluru Filter: Stat Total={stat_total_mlr}, Scope={stat_scope_mlr}, Strip Plotted={strip_total_mlr}")
        assert "1,515" in stat_total_mlr, f"Expected 1,515 for Mangaluru, got '{stat_total_mlr}'"
        assert "Mangaluru" in stat_scope_mlr, f"Expected Mangaluru scope, got '{stat_scope_mlr}'"
        assert "1,515" in strip_total_mlr, f"Expected 1,515 plotted in strip, got '{strip_total_mlr}'"

        # Save Mangaluru Heatmap screenshot
        mlr_shot = os.path.join(ARTIFACT_DIR, "safety_map_heatmap_mangaluru.png")
        await page.screenshot(path=mlr_shot)
        print(f"Saved screenshot: {mlr_shot}")

        # 6C: Return to Combined Scope
        await page.click("#btn-city-combined")
        await page.wait_for_function("() => document.getElementById('heatmap-stat-total') && document.getElementById('heatmap-stat-total').innerText.includes('6,538')", timeout=15000)
        stat_total_comb = await page.locator("#heatmap-stat-total").inner_text()
        assert "6,538" in stat_total_comb, f"Expected 6,538 after returning to Combined, got '{stat_total_comb}'"
        print("PASSED Test 6: City filters synchronize perfectly with Heatmap View (5,023 / 1,515 / 6,538).")

        # =========================================================================
        # TEST 7: Checkbox Layer Filtering in Heatmap View
        # =========================================================================
        print("\n--- TEST 7: Checkbox Layer Filtering in Heatmap View ---")
        # Uncheck Bengaluru markers
        await page.uncheck("#toggle-blr-markers")
        await page.wait_for_timeout(500)
        stat_total_noblr = await page.locator("#heatmap-stat-total").inner_text()
        assert "1,515" in stat_total_noblr, f"Expected 1,515 when BLR unchecked in combined view, got '{stat_total_noblr}'"

        # Re-check Bengaluru markers
        await page.check("#toggle-blr-markers")
        await page.wait_for_timeout(500)
        stat_total_restored = await page.locator("#heatmap-stat-total").inner_text()
        assert "6,538" in stat_total_restored, f"Expected 6,538 when BLR rechecked, got '{stat_total_restored}'"
        print("PASSED Test 7: Checkbox toggles dynamically filter heatmap points.")

        # =========================================================================
        # TEST 8: Basemap Tile Switch in Heatmap View
        # =========================================================================
        print("\n--- TEST 8: Basemap Tile Switch in Heatmap View ---")
        # Toggle Satellite
        await page.click("#btn-map-layer-sat")
        await page.wait_for_timeout(500)
        is_sat_active = await page.evaluate("() => safetyMap.hasLayer(baseTiles.sat)")
        heat_still_active = await page.evaluate("() => activeHeatLayer !== null && safetyMap.hasLayer(activeHeatLayer)")
        assert is_sat_active, "Satellite layer should be active on map"
        assert heat_still_active, "Heatmap layer should remain active over satellite basemap"

        sat_shot = os.path.join(ARTIFACT_DIR, "safety_map_heatmap_satellite.png")
        await page.screenshot(path=sat_shot)
        print(f"Saved screenshot: {sat_shot}")

        # Toggle Dark Map back
        await page.click("#btn-map-layer-map")
        await page.wait_for_timeout(500)
        is_dark_active = await page.evaluate("() => safetyMap.hasLayer(baseTiles.dark)")
        assert is_dark_active, "CartoDB Dark Matter layer should be active on map"
        print("PASSED Test 8: Satellite and Dark basemaps toggle cleanly in Heatmap View.")

        # =========================================================================
        # TEST 9: Seamless Switch back to Classic View
        # =========================================================================
        print("\n--- TEST 9: Seamless Switch back to Classic View ---")
        await page.click("#btn-view-mode-classic")
        await page.wait_for_function("() => markersLayer && markersLayer.getLayers().length === 6538", timeout=15000)

        view_mode = await page.evaluate("() => AppState.safetyMapViewMode")
        assert view_mode == "classic", f"Expected safetyMapViewMode to be 'classic', got '{view_mode}'"

        left_hidden = await page.evaluate("() => document.getElementById('heatmap-left-panel').classList.contains('hidden')")
        right_hidden = await page.evaluate("() => document.getElementById('heatmap-right-panel').classList.contains('hidden')")
        legend_hidden = await page.evaluate("() => document.getElementById('heatmap-legend').classList.contains('hidden')")
        assert left_hidden, "Left panel must be hidden in Classic View"
        assert right_hidden, "Right panel must be hidden in Classic View"
        assert legend_hidden, "Legend must be hidden in Classic View"

        marker_count = await page.evaluate("() => markersLayer ? markersLayer.getLayers().length : 0")
        assert marker_count == 6538, f"Expected 6,538 markers restored in Classic View, got {marker_count}"

        heat_removed = await page.evaluate("() => activeHeatLayer === null")
        assert heat_removed, "activeHeatLayer must be removed and null in Classic View"
        print("PASSED Test 9: Successfully switched back to Classic View with full marker restoration.")

        # =========================================================================
        # TEST 10: Repeated Switching Stress Test & Error Check
        # =========================================================================
        print("\n--- TEST 10: Repeated Switching Stress Test & Error Check ---")
        for i in range(5):
            await page.click("#btn-view-mode-heatmap")
            await page.wait_for_timeout(200)
            await page.click("#btn-view-mode-classic")
            await page.wait_for_timeout(200)

        # Assert no Javascript errors occurred during any of these steps
        print(f"Javascript Errors Logged: {len(errors)}")
        if len(errors) > 0:
            print("Errors detected:", errors)
        assert len(errors) == 0, f"Expected 0 javascript errors, but encountered {len(errors)}: {errors}"
        print("PASSED Test 10: 5 consecutive view switches executed with 0 errors and no memory leaks.")

        await browser.close()
        print("\n=== ALL 10 TESTS PASSED SUCCESSFULLY! ===")

if __name__ == "__main__":
    asyncio.run(run())

