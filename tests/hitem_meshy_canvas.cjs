// Optional isolated ComfyUI acceptance. Uses saved local models, never the API.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE,
        args: ["--enable-unsafe-swiftshader"] });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.SEEDANCE_3D_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__threeApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__threeApp?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(folder).filter((name) => /^(hitem3d-|meshy-6-)/.test(name));
        assert.equal(files.length, 5);
        for (const filename of files) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const report = await page.evaluate(async (workflow) => {
                const app = window.__threeApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 160));
                let node = app.graph._nodes.find((node) => ["Hitem3D_V2", "Hitem3D_Portrait_V2_1", "Meshy_6_Global"].includes(node.comfyClass));
                const selector = node.widgets.find((widget) => widget.name === "model");
                const original = selector.value;
                for (const value of [...selector.options.values, original]) {
                    selector.value = value; selector.callback?.(value);
                    await new Promise((resolve) => setTimeout(resolve, 25));
                }
                node.setSize([850, node.size[1]]);
                node.setSize([430, node.size[1]]);
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 160));
                node = app.graph._nodes.find((node) => node.comfyClass.startsWith("Hitem3D_") || node.comfyClass === "Meshy_6_Global");
                const prompt = await app.graphToPrompt();
                app.canvas.ds.scale = .75; app.canvas.ds.offset = [90, 100]; app.canvas.setDirty(true, true);
                return { type: node.comfyClass, output: node.outputs[0].type,
                    inputNames: node.inputs.filter((item) => ["IMAGE", "SEEDANCE_CONFIG"].includes(item.type)).map((item) => item.name),
                    control: node.widgets.find((item) => item.name === "control_after_generate").value,
                    inputs: prompt.output[String(node.id)].inputs };
            }, workflow);
            assert.equal(report.output, "FILE_3D");
            assert.equal(report.control, "fixed");
            assert.ok(Array.isArray(report.inputs.image1) && Array.isArray(report.inputs.api_config));
            assert.equal(report.inputs.seed, 0);
            assert.deepEqual(report.inputNames, report.type === "Meshy_6_Global" ? ["image1", "api_config"]
                : ["image1", "image2", "image3", "image4", "api_config"]);
            if (filename.includes("multi-image")) assert.ok(Array.isArray(report.inputs.image2));
            console.log(`CANVAS PASS ${filename}: model switch, resize, reload, native links and fixed seed`);
        }
        const file = process.env.SEEDANCE_3D_FIXTURE_FILE ?? "sample.glb";
        const execution = await page.evaluate(async (filename) => {
            const app = window.__threeApp;
            app.graph.clear();
            const fixture = window.LiteGraph.createNode("Seedance3DFixture");
            const preview = window.LiteGraph.createNode("Preview3D");
            const save = window.LiteGraph.createNode("SaveGLB");
            for (const node of [fixture, preview, save]) app.graph.add(node);
            fixture.widgets.find((widget) => widget.name === "model_file").value = filename;
            fixture.pos = [40, 180]; preview.pos = [420, 80]; save.pos = [1200, 180];
            preview.setSize([650, 650]);
            const a = fixture.connect(0, preview, preview.inputs.findIndex((item) => item.name === "model_file"));
            const b = fixture.connect(0, save, save.inputs.findIndex((item) => item.name === "mesh"));
            if (!a || !b) throw new Error("Native File3D links failed");
            app.canvas.ds.scale = .88; app.canvas.ds.offset = [90, 70]; app.canvas.setDirty(true, true);
            const prompt = await app.graphToPrompt();
            const { api } = await import("/scripts/api.js");
            const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ prompt: prompt.output, client_id: api.clientId, extra_data: { extra_pnginfo: { workflow: prompt.workflow } } }) });
            const submitted = await response.json();
            if (!response.ok) throw new Error(JSON.stringify(submitted));
            let record;
            for (let i = 0; i < 60; i++) {
                const history = await (await fetch(`/history/${submitted.prompt_id}`)).json();
                record = history[submitted.prompt_id];
                if (record?.status?.completed) break;
                await new Promise((resolve) => setTimeout(resolve, 1000));
            }
            if (record?.status?.status_str !== "success") throw new Error(JSON.stringify(record?.status));
            const output = record.outputs[String(preview.id)];
            preview.onExecuted?.(output);
            return { saved: record.outputs[String(save.id)]["3d"], preview: output };
        }, file);
        assert.ok(execution.saved.length > 0);
        console.log("NATIVE PASS actual File3D -> Preview3D and SaveGLB execution");
        await page.waitForTimeout(5000);
        await page.keyboard.press("Escape");
        const canvases = await page.evaluate(() => Array.from(document.querySelectorAll("canvas")).map((canvas) => {
            const rect = canvas.getBoundingClientRect();
            return { x: rect.x, y: rect.y, width: rect.width, height: rect.height, pixels: [canvas.width, canvas.height] };
        }).filter((rect) => rect.width > 150 && rect.height > 150));
        console.log("VIEWPORTS", JSON.stringify(canvases));
        const directory = process.env.SEEDANCE_UI_SCREENSHOT_DIR;
        if (directory) {
            await page.screenshot({ path: path.join(directory, `native-${file}.png`) });
            const viewport = canvases.find((rect) => rect.width < 900 && rect.x > 200 && rect.height > 200);
            if (viewport) {
                await page.screenshot({ path: path.join(directory, `viewer-${file}.png`), clip: viewport });
                await page.mouse.move(viewport.x + viewport.width * .5, viewport.y + viewport.height * .5);
                await page.mouse.down();
                await page.mouse.move(viewport.x + viewport.width * .7, viewport.y + viewport.height * .55, { steps: 15 });
                await page.mouse.up();
                await page.waitForTimeout(500);
                await page.screenshot({ path: path.join(directory, `viewer-rotated-${file}.png`), clip: viewport });
            }
            await page.setViewportSize({ width: 390, height: 844 });
            await page.evaluate(() => {
                const app = window.__threeApp;
                app.canvas.ds.scale = .43;
                app.canvas.ds.offset = [-250, 120];
                app.canvas.setDirty(true, true);
            });
            await page.waitForTimeout(800);
            await page.screenshot({ path: path.join(directory, `mobile-${file}.png`) });
            const mobile = await page.evaluate(() => Array.from(document.querySelectorAll("canvas")).map((canvas) => {
                const r = canvas.getBoundingClientRect();
                return { x: r.x, y: r.y, width: r.width, height: r.height };
            }).find((r) => r.x > 50 && r.y < 500 && r.width > 150 && r.width < 330 && r.height > 150));
            assert.ok(mobile, "Mobile native 3D viewport missing or out of frame");
            assert.ok(mobile.x + mobile.width <= 390 && mobile.y + mobile.height <= 844);
            await page.screenshot({ path: path.join(directory, `mobile-viewer-${file}.png`), clip: mobile });
        }
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
