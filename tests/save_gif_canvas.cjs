// Isolated local acceptance: uses previously downloaded GIFs, never generation APIs.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.SEEDANCE_SAVE_GIF_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__gifSaveApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__gifSaveApp?.graph);
        await page.keyboard.press("Escape");
        const directory = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(directory).filter((name) => /^zhenzhen-image-g-v2\.6-.*GIF动画\.json$/.test(name)
            || ["G26GIF三模型并发.json", "保存GIF_本地图像帧.json"].includes(name));
        assert.equal(files.length, 5);
        for (const name of files) {
            const workflow = JSON.parse(fs.readFileSync(path.join(directory, name), "utf8"));
            const report = await page.evaluate(async (workflow) => {
                const app = window.__gifSaveApp;
                app.nodeOutputs = {};
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 100));
                const savers = app.graph._nodes.filter((node) => node.comfyClass === "Seedance_Save_GIF");
                for (const node of savers) {
                    const selector = node.widgets.find((widget) => widget.name === "source_mode");
                    const original = selector.value;
                    for (const mode of ["original", "frames", "auto", original]) {
                        selector.value = mode; selector.callback?.(mode);
                        await new Promise((resolve) => setTimeout(resolve, 20));
                    }
                    node.setSize([800, node.size[1]]); node.setSize([360, node.size[1]]);
                }
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 100));
                const prompt = await app.graphToPrompt();
                return app.graph._nodes.filter((node) => node.comfyClass === "Seedance_Save_GIF").map((node) => ({
                    inputs: prompt.output[String(node.id)].inputs,
                    sockets: node.inputs.map((input) => input.name), outputCount: node.outputs.length,
                    hasApiButton: node.widgets.some((widget) => widget.name.includes("APIKEY")),
                }));
            }, workflow);
            assert.equal(report.length, name === "G26GIF三模型并发.json" ? 3 : 1);
            for (const saver of report) {
                assert.deepEqual(saver.sockets.filter((name) => ["images", "source_path", "durations_json"].includes(name)),
                    ["images", "source_path", "durations_json"]);
                assert.ok(Array.isArray(saver.inputs.images));
                assert.equal(saver.outputCount, 2);
                assert.equal(saver.hasApiButton, false);
                if (name.includes("GIF动画")) assert.ok(Array.isArray(saver.inputs.source_path));
            }
            console.log(`CANVAS PASS ${name}: Save GIF links, modes, resize and reload`);
        }
        const execution = await page.evaluate(async () => {
            const app = window.__gifSaveApp;
            app.graph.clear();
            app.nodeOutputs = {};
            const fixture = window.LiteGraph.createNode("SeedanceSaveGIFFixture");
            app.graph.add(fixture);
            fixture.pos = [30, 100];
            const selector = fixture.widgets.find((widget) => widget.name === "filename");
            selector.value = selector.options.values.find((value) => value.includes("lowprice"));
            const savers = ["original", "frames"].map((mode, index) => {
                const node = window.LiteGraph.createNode("Seedance_Save_GIF");
                app.graph.add(node);
                node.pos = [420 + index * 620, 80];
                node.widgets.find((widget) => widget.name === "filename_prefix").value = "gif_test/" + mode;
                const control = node.widgets.find((widget) => widget.name === "source_mode");
                control.value = mode; control.callback?.(mode);
                fixture.connect(0, node, node.inputs.findIndex((input) => input.name === "images"));
                if (mode === "original") fixture.connect(1, node, node.inputs.findIndex((input) => input.name === "source_path"));
                else fixture.connect(2, node, node.inputs.findIndex((input) => input.name === "durations_json"));
                return node;
            });
            const prompt = await app.graphToPrompt();
            const { api } = await import("/scripts/api.js");
            const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt.output, client_id: api.clientId }) });
            const submitted = await response.json();
            if (!response.ok) throw new Error(JSON.stringify(submitted));
            let record;
            for (let i = 0; i < 60; i++) {
                record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                if (record?.status?.completed) break;
                await new Promise((resolve) => setTimeout(resolve, 500));
            }
            if (record?.status?.status_str !== "success") throw new Error(JSON.stringify(record?.status));
            for (const node of savers) if (!node.seedanceGifWidget) node.onExecuted?.(record.outputs[String(node.id)]);
            app.canvas.ds.scale = .72; app.canvas.ds.offset = [40, 80]; app.canvas.setDirty(true, true);
            return { source: selector.value, outputs: savers.map((node) => record.outputs[String(node.id)]) };
        });
        const sourceDir = process.env.SEEDANCE_GIF_SAVE_SOURCE_DIR;
        for (const [index, output] of execution.outputs.entries()) {
            assert.ok(output.animated[0]);
            const response = await page.request.get(new URL("/view?" + new URLSearchParams(output.images[0]), page.url()).href);
            const bytes = await response.body();
            assert.equal(bytes.subarray(0, 3).toString(), "GIF");
            if (index === 0 && sourceDir) assert.ok(bytes.equals(fs.readFileSync(path.join(sourceDir, execution.source))), "Original GIF bytes changed");
        }
        await page.waitForTimeout(700);
        for (let index = 0; index < 2; index++) {
            const image = page.locator(".seedance-gif-preview img").nth(index);
            const hashes = new Set();
            for (let frame = 0; frame < 8; frame++) {
                hashes.add(crypto.createHash("sha256").update(await image.screenshot()).digest("hex"));
                await page.waitForTimeout(100);
            }
            assert.ok(hashes.size > 1, "Saved GIF preview does not animate");
            console.log(`GIF PASS ${index ? "encoded frames" : "original copy"}: changing preview pixels`);
        }
        const [download] = await Promise.all([page.waitForEvent("download"), page.locator(".seedance-gif-preview a").first().click()]);
        assert.equal(await download.failure(), null);
        assert.ok(download.suggestedFilename().endsWith(".gif"));
        if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, "save-gif-desktop.png") });

        const localWorkflow = JSON.parse(fs.readFileSync(path.join(directory, "保存GIF_本地图像帧.json"), "utf8"));
        const local = await page.evaluate(async (workflow) => {
            const app = window.__gifSaveApp;
            app.nodeOutputs = {};
            await app.loadGraphData(workflow);
            const prompt = await app.graphToPrompt();
            const { api } = await import("/scripts/api.js");
            const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt.output, client_id: api.clientId }) });
            const submitted = await response.json();
            if (!response.ok) throw new Error(JSON.stringify(submitted));
            let record;
            for (let i = 0; i < 60; i++) {
                record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                if (record?.status?.completed) break;
                await new Promise((resolve) => setTimeout(resolve, 500));
            }
            if (record?.status?.status_str !== "success") throw new Error(JSON.stringify(record?.status));
            const node = app.graph._nodes.find((node) => node.comfyClass === "Seedance_Save_GIF");
            if (!node.seedanceGifWidget) node.onExecuted?.(record.outputs[String(node.id)]);
            node.pos = [40, 70]; node.setSize([430, node.size[1]]);
            return record.outputs[String(node.id)];
        }, localWorkflow);
        assert.ok(local.animated[0]);
        console.log("GIF PASS native LoadImage + ImageBatch + Save GIF, no API config");
        await page.setViewportSize({ width: 390, height: 844 });
        await page.evaluate(() => {
            const app = window.__gifSaveApp;
            for (const node of app.graph._nodes) if (node.comfyClass !== "Seedance_Save_GIF") node.pos = [-3000, -3000];
            app.canvas.ds.scale = .58; app.canvas.ds.offset = [70, 120]; app.canvas.setDirty(true, true);
        });
        await page.waitForTimeout(3500);
        const bounds = await page.locator(".seedance-gif-preview img").last().boundingBox();
        assert.ok(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 390 && bounds.y + bounds.height <= 844);
        if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, "save-gif-mobile.png") });
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS mobile preview and zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
