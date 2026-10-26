// Optional real-canvas acceptance; no API requests are created.
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
        await page.goto(process.env.SEEDANCE_KLING4_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__klingApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__klingApp?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        for (const filename of fs.readdirSync(folder).filter((file) => file.startsWith("kling-v4-") && file.endsWith(".json"))) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const report = await page.evaluate(async (workflow) => {
                const app = window.__klingApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 200));
                const generators = app.graph._nodes.filter((node) => node.comfyClass.startsWith("Kling_V4_"));
                for (const node of generators) {
                    for (const name of ["reference_type", "source_mode"]) {
                        const widget = node.widgets.find((item) => item.name === name);
                        if (!widget) continue;
                        const original = widget.value;
                        for (const value of [...widget.options.values, original]) {
                            widget.value = value;
                            widget.callback?.(value);
                            await new Promise((resolve) => setTimeout(resolve, 30));
                        }
                    }
                    node.setSize([850, node.size[1]]);
                    node.setSize([460, node.size[1]]);
                }
                const saved = app.graph.serialize();
                await app.loadGraphData(saved);
                await new Promise((resolve) => setTimeout(resolve, 200));
                const prompt = await app.graphToPrompt();
                const output = app.graph._nodes.filter((node) => node.comfyClass.startsWith("Kling_V4_")).map((node) => ({
                    type: node.comfyClass, inputs: prompt.output[String(node.id)].inputs,
                    control: node.widgets.find((item) => item.name === "control_after_generate").value,
                    outputCount: node.outputs.length,
                }));
                app.canvas.ds.scale = .60;
                app.canvas.ds.offset = [130, 160];
                app.canvas.setDirty(true, true);
                return output;
            }, workflow);
            assert.ok(report.length > 0);
            for (const row of report) {
                assert.equal(row.inputs.seed, 0);
                assert.equal(row.control, "fixed");
                assert.ok(Array.isArray(row.inputs.api_config));
                assert.equal(row.outputCount, row.type.includes("Custom") ? 5 : 4);
                if (row.type === "Kling_V4_I2V") assert.ok(!("ratio" in row.inputs));
            }
            if (filename.includes("主体音色连线")) {
                const omni = report.find((row) => row.type === "Kling_V4_Omni");
                assert.ok(Array.isArray(omni.inputs.image_element_ids));
                assert.ok(Array.isArray(omni.inputs.voice_ids));
                assert.equal(report.length, 3);
            }
            await page.keyboard.press("Escape");
            if (process.env.SEEDANCE_UI_SCREENSHOT_DIR && /主体音色连线|首尾帧|本地音频/.test(filename)) {
                await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, filename.replace(/\.json$/, ".png")) });
            }
            console.log(`CANVAS PASS ${filename}: modes, resize, reload, linked sockets, seed and prompt serialization`);
        }
        for (const kind of ["T2V", "I2V", "Omni"]) {
            const report = await page.evaluate(async (kind) => {
                const app = window.__klingApp;
                app.graph.clear();
                const node = window.LiteGraph.createNode(`SeedanceConcurrent_Kling_V4_${kind}_Submit`);
                app.graph.add(node);
                node.pos = [150, 100];
                await new Promise((resolve) => setTimeout(resolve, 100));
                if (kind === "Omni") {
                    for (let i = 1; i <= 10; i++) node.inputs.find((input) => input.name === `image${i}`).link = null;
                    node.onConnectionsChange?.();
                }
                node.widgets.find((widget) => widget.name === "control_after_generate").value = "fixed";
                node.setSize([850, node.size[1]]);
                node.setSize([460, node.size[1]]);
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 150));
                const restored = app.graph._nodes[0];
                return { output: restored.outputs[0].type,
                    image2Hidden: restored.inputs.find((input) => input.name === "image2")?.hidden,
                    video2Hidden: restored.inputs.find((input) => input.name === "video2")?.hidden,
                    control: restored.widgets.find((widget) => widget.name === "control_after_generate").value };
            }, kind);
            assert.equal(report.output, "SEEDANCE_VIDEO_FUTURE");
            assert.equal(report.control, "fixed");
            if (kind === "Omni") assert.ok(report.image2Hidden && report.video2Hidden);
            console.log(`CANVAS PASS concurrent ${kind}`);
        }
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
