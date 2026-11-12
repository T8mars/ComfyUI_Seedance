// Canvas-only acceptance: no task submission or media upload is allowed.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) => {
            const request = route.request();
            if (request.method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(request.url())) {
                return route.abort("blockedbyclient");
            }
            return route.continue();
        });
        await page.goto(process.env.SEEDREAM55_REFERENCE_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__referenceApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__referenceApp?.graph);
        await page.keyboard.press("Escape");
        for (const key of ["Seedream_5_5_Image", "SeedanceConcurrent_Seedream_5_5_Image_Submit"]) {
            const report = await page.evaluate(async (key) => {
                const app = window.__referenceApp;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 100));
                app.graph.clear();
                const target = LiteGraph.createNode(key); app.graph.add(target); target.pos = [570, 90];
                const config = LiteGraph.createNode("Seedance_Config"); app.graph.add(config); config.pos = [140, 550];
                config.connect(0, target, target.inputs.findIndex((input) => input.name === "api_config"));
                const source = LiteGraph.createNode("LoadImage"); app.graph.add(source); source.pos = [140, 90];
                target.widgets.find((widget) => widget.name === "prompt").value = "Keep the subjects and combine the reference images in a clean studio.";
                const initialNames = target.inputs.map((input) => input.name);
                const setModel = async (value) => {
                    const widget = target.widgets.find((item) => item.name === "model");
                    widget.value = value; widget.callback?.(value); await settle();
                };
                const visible = () => target.inputs.filter((input) => /^image\d+$/.test(input.name) && !input.hidden).map((input) => input.name);
                const counts = [];
                for (const model of ["seedream-v5.5-i2i", "dola-seedream-5.5-i2i"]) {
                    await setModel(model);
                    counts.push(visible().length);
                }
                for (let index = 1; index <= 10; index++) {
                    source.connect(0, target, target.inputs.findIndex((input) => input.name === `image${index}`));
                    await settle();
                    if (visible().length !== 10) throw new Error(`Only ${visible().length} visible after connecting image${index}`);
                }
                const links = target.inputs.filter((input) => /^image\d+$/.test(input.name)).map((input) => input.link);
                const canvasPositions = [];
                for (const width of [950, 510]) {
                    target.setSize([width, target.size[1]]); await settle();
                    canvasPositions.push(target.inputs.filter((input) => /^image\d+$/.test(input.name)).map((input) => {
                        const slot = target.inputs.indexOf(input);
                        return Array.from(target.getConnectionPos(true, slot, new Float32Array(2)));
                    }));
                }
                await setModel("seedream-v5.5-t2i");
                counts.push(visible().length);
                await setModel("dola-seedream-5.5-i2i");
                const id = target.id;
                await app.loadGraphData(app.graph.serialize()); await settle();
                const restored = app.graph.getNodeById(id);
                const prompt = (await app.graphToPrompt()).output[String(id)];
                app.canvas.ds.scale = .85; app.canvas.centerOnNode(restored); app.canvas.setDirty(true, true);
                return { counts, initialNames, restoredNames: restored.inputs.map((input) => input.name), links,
                    restoredLinks: restored.inputs.filter((input) => /^image\d+$/.test(input.name)).map((input) => input.link),
                    visibleAfterReload: restored.inputs.filter((input) => /^image\d+$/.test(input.name) && !input.hidden).length,
                    promptImages: Object.keys(prompt.inputs).filter((name) => /^image\d+$/.test(name)).length,
                    canvasPositions };
            }, key);
            assert.deepEqual(report.counts, [10, 10, 10]);
            assert.equal(report.visibleAfterReload, 10);
            assert.equal(report.promptImages, 10);
            assert.deepEqual(report.restoredNames, report.initialNames);
            assert.deepEqual(report.restoredLinks, report.links);
            assert.ok(report.links.every((link) => link != null));
            for (const positions of report.canvasPositions) {
                assert.equal(new Set(positions.map((point) => point[1])).size, 10, "All ten sockets must have distinct positions");
            }
            console.log(`PASS ${key}: ten visible empty/connected references, model switch, resize, distinct socket positions, reload and serialized prompt`);
            if (process.env.SEEDREAM55_REFERENCE_SCREENSHOTS) {
                fs.mkdirSync(process.env.SEEDREAM55_REFERENCE_SCREENSHOTS, { recursive: true });
                await page.waitForTimeout(200);
                await page.screenshot({ path: path.join(process.env.SEEDREAM55_REFERENCE_SCREENSHOTS, key+".png") });
            }
        }
        assert.deepEqual(errors, []);
        console.log("PASS zero page errors; no generation API requests");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
