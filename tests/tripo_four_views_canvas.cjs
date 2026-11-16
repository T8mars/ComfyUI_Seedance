// Canvas-only fixed-view acceptance. Task creation and uploads are blocked.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1150 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) => {
            const request = route.request();
            if (request.method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(request.url())) return route.abort("blockedbyclient");
            return route.continue();
        });
        await page.goto(process.env.SEEDANCE_REFERENCE_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__tripoApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__tripoApp?.graph);
        await page.waitForTimeout(1000);
        await page.keyboard.press("Escape");
        const screenshot = async (filename) => {
            if (!process.env.SEEDANCE_REFERENCE_SCREENSHOTS) return;
            fs.mkdirSync(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, { recursive: true });
            await page.mouse.move(1450, 850); await page.waitForTimeout(700);
            const clip = await page.evaluate(() => {
                const app = window.__tripoApp, node = app.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate"), ds = app.canvas.ds;
                const box = app.canvas.canvas.getBoundingClientRect();
                const x = Math.max(0, Math.floor(box.left + (node.pos[0] + ds.offset[0]) * ds.scale) - 8);
                const y = Math.max(0, Math.floor(box.top + (node.pos[1] + ds.offset[1] - 30) * ds.scale) - 8);
                return { x, y, width: Math.min(Math.ceil(node.size[0] * ds.scale) + 16, innerWidth - x), height: Math.min(Math.ceil((node.size[1] + 40) * ds.scale) + 16, innerHeight - y) };
            });
            await page.screenshot({ path: path.join(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, filename), clip });
        };
        for (const family of ["h-v3.1", "h-v3.0", "h-v2.5", "p-p2", "p-p1"]) {
            const model = `tripo-${family}-multiview-to-3d`;
            const initial = await page.evaluate(async (model) => {
                const app = window.__tripoApp; app.graph.clear();
                const node = LiteGraph.createNode("Tripo_Generate"); app.graph.add(node); node.pos = [650, 80];
                for (const [name, value] of [["model", model], ["input_mode", "views"]]) {
                    const widget = node.widgets.find((widget) => widget.name === name); widget.value = value; widget.callback?.(value);
                }
                await new Promise((resolve) => setTimeout(resolve, 100));
                const fresh = node.inputs.filter((input) => /^image[1-4]$/.test(input.name)).map((input) => ({ name: input.name, hidden: input.hidden, link: input.link, label: input.label }));
                const workflow = app.graph.serialize();
                for (const input of workflow.nodes.find((node) => node.type === "Tripo_Generate").inputs.filter((input) => /^image[34]$/.test(input.name))) {
                    input.pos = [-100000, -100000]; input.widget = { name: "__seedance_hidden_input__" }; input.hidden = true;
                }
                await app.loadGraphData(workflow); await new Promise((resolve) => setTimeout(resolve, 100));
                const source = LiteGraph.createNode("EmptyImage"); app.graph.add(source); source.pos = [80, 80];
                app.canvas.ds.scale = .8; app.canvas.ds.offset[0] = 0; app.canvas.ds.offset[1] = 0; app.canvas.setDirty(true, true);
                return fresh;
            }, model);
            assert.equal(initial.length, 4);
            assert.ok(initial.every((input) => !input.hidden && input.link == null), `${model}: four visible ports before any connections`);
            assert.deepEqual(initial.map((input) => input.label), ["image1 (front)", "image2 (left)", "image3 (back)", "image4 (right)"]);
            for (let index = 1; index <= 4; index++) {
                await page.waitForTimeout(100);
                const points = await page.evaluate((index) => {
                    const app = window.__tripoApp, source = app.graph._nodes.find((node) => node.comfyClass === "EmptyImage"), target = app.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate");
                    const slot = target.inputs.findIndex((input) => input.name === `image${index}`);
                    if (target.inputs[slot].hidden) throw new Error(`image${index} is hidden`);
                    const box = app.canvas.canvas.getBoundingClientRect(), ds = app.canvas.ds;
                    const screen = (point) => [box.left + (point[0] + ds.offset[0]) * ds.scale, box.top + (point[1] + ds.offset[1]) * ds.scale];
                    return { from: screen(source.getConnectionPos(false, 0, new Float32Array(2))), to: screen(target.getConnectionPos(true, slot, new Float32Array(2))) };
                }, index);
                await page.mouse.move(...points.from); await page.mouse.down(); await page.mouse.move(...points.to, { steps: 12 }); await page.mouse.up();
                await page.waitForTimeout(100);
                assert.equal(await page.evaluate((index) => window.__tripoApp.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate").inputs.find((input) => input.name === `image${index}`).link != null, index), true, `${model}: mouse connects image${index}`);
            }
            if (process.env.SEEDANCE_REFERENCE_SCREENSHOTS && family === "h-v3.1") {
                await screenshot("tripo-four-connected.png");
            }
            const report = await page.evaluate(async (family) => {
                const app = window.__tripoApp;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 80));
                let node = app.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate");
                const images = () => node.inputs.filter((input) => /^image[1-4]$/.test(input.name));
                const names = node.inputs.map((input) => input.name), links = images().map((input) => input.link);
                const prompt = (await app.graphToPrompt()).output[String(node.id)];
                for (const width of [900, 510]) { node.setSize([width, node.size[1]]); await settle(); }
                await app.loadGraphData(app.graph.serialize()); await settle(); node = app.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate");
                const restoredLinks = images().map((input) => input.link);
                for (const name of ["image3", "image4"]) node.disconnectInput(node.inputs.findIndex((input) => input.name === name));
                await settle(); await app.loadGraphData(app.graph.serialize()); await settle(); node = app.graph._nodes.find((node) => node.comfyClass === "Tripo_Generate");
                const legacyTwoVisible = images().filter((input) => !input.hidden).length;
                const legacyTwoLinks = images().map((input) => input.link != null);
                const change = async (name, value) => { const widget = node.widgets.find((widget) => widget.name === name); widget.value = value; widget.callback?.(value); await settle(); };
                await change("input_mode", "multiviewTaskId");
                const reuseLinkedVisible = images().filter((input) => !input.hidden).length;
                for (const name of ["image1", "image2"]) node.disconnectInput(node.inputs.findIndex((input) => input.name === name));
                await settle();
                const reuseEmptyVisible = images().filter((input) => !input.hidden).length;
                await change("input_mode", "views");
                const viewsEmptyVisible = images().filter((input) => !input.hidden).length;
                await change("model", `tripo-${family}-image-to-3d`);
                const singleVisible = images().filter((input) => !input.hidden).length;
                await change("model", `tripo-${family}-text-to-3d`);
                const textVisible = images().filter((input) => !input.hidden).length;
                await change("model", `tripo-${family}-multiview-to-3d`);
                const finalVisible = images().filter((input) => !input.hidden).length;
                const positions = images().map((input) => Array.from(node.getConnectionPos(true, node.inputs.indexOf(input), new Float32Array(2))));
                const concreteVisible = node._concreteInputs.filter((input) => /^image[1-4]$/.test(input.name) && input.widget?.name !== "__seedance_hidden_input__").length;
                return { names, restoredNames: node.inputs.map((input) => input.name), links, restoredLinks, promptImages: Object.keys(prompt.inputs).filter((name) => /^image[1-4]$/.test(name)),
                    legacyTwoVisible, legacyTwoLinks, reuseLinkedVisible, reuseEmptyVisible, viewsEmptyVisible, singleVisible, textVisible, finalVisible, positions, concreteVisible };
            }, family);
            assert.deepEqual(report.names, report.restoredNames); assert.deepEqual(report.links, report.restoredLinks);
            assert.deepEqual(report.promptImages.sort(), ["image1", "image2", "image3", "image4"]);
            assert.equal(report.legacyTwoVisible, 4); assert.deepEqual(report.legacyTwoLinks, [true, true, false, false]);
            assert.deepEqual([report.reuseLinkedVisible, report.reuseEmptyVisible, report.viewsEmptyVisible, report.singleVisible, report.textVisible, report.finalVisible, report.concreteVisible], [2, 0, 4, 1, 0, 4, 4]);
            assert.equal(new Set(report.positions.map((position) => position[1])).size, 4);
            assert.ok(report.positions.flat().every((value) => Number.isFinite(value) && value > -50000));
            console.log(`PASS ${model}: four empty view ports, four physical mouse connections, legacy two-reference reload, mode switches, sizing and serialized prompt`);
            if (family === "h-v3.1") await screenshot("tripo-four-empty.png");
        }
        assert.deepEqual(errors, []);
        console.log("PASS all five multiview models, zero page errors; no generation or upload requests");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
