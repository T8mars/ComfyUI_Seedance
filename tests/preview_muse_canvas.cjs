// Optional actual-canvas acceptance. Does not queue API generation.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

const KEYS = ["HY_Image_3_5_Preview", "Muse_Image", "Muse_Video", "Flux_3_Image_Variants"];
const MODELS = ["flux-3-image-t2i", "flux-3-image-i2i", "flux-3-image-klein-t2i", "flux-3-image-klein-i2i"];

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.SEEDANCE_PREVIEW_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__previewApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__previewApp?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        for (const filename of fs.readdirSync(folder).filter((file) => /^(HY35Preview|MuseImage|MuseVideo|flux-3-image-|MotionVideo)/.test(file))) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const report = await page.evaluate(async ({ workflow, keys, models }) => {
                const app = window.__previewApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 160));
                const generators = app.graph._nodes.filter((node) => keys.includes(node.comfyClass) || node.comfyClass === "Zhenzhen_Motion_Video");
                for (const node of generators) {
                    for (const name of ["model", "size", "operation"]) {
                        const widget = node.widgets.find((item) => item.name === name);
                        if (!widget) continue;
                        const original = widget.value;
                        const choices = name === "model" && keys.includes(node.comfyClass) ? models : widget.options.values;
                        for (const value of [...choices, original]) {
                            widget.value = value;
                            widget.callback?.(value);
                            await new Promise((resolve) => setTimeout(resolve, 20));
                        }
                    }
                    node.setSize([850, node.size[1]]);
                    node.setSize([460, node.size[1]]);
                }
                const saved = app.graph.serialize();
                for (const node of saved.nodes) {
                    for (const input of node.inputs ?? []) {
                        if (input.widget) {
                            if (String(input.widget.name).includes("seedance-hidden")) throw new Error("Hidden marker leaked");
                        }
                    }
                }
                await app.loadGraphData(saved);
                await new Promise((resolve) => setTimeout(resolve, 160));
                const prompt = await app.graphToPrompt();
                const report = app.graph._nodes.filter((node) => keys.includes(node.comfyClass) || node.comfyClass === "Zhenzhen_Motion_Video")
                    .map((node) => ({ type: node.comfyClass, inputs: prompt.output[String(node.id)].inputs,
                        sockets: node.inputs.filter((item) => ["IMAGE", "SEEDANCE_CONFIG"].includes(item.type)).length,
                        inputNames: node.inputs.map((item) => ({ name: item.name, type: item.type, widget: item.widget })),
                        outputs: node.outputs.length,
                        control: node.widgets.find((item) => item.name === "control_after_generate").value }));
                app.canvas.ds.scale = .72;
                app.canvas.ds.offset = [80, 80];
                app.canvas.setDirty(true, true);
                return report;
            }, { workflow, keys: KEYS, models: MODELS });
            assert.ok(report.length > 0);
            for (const row of report) {
                assert.equal(row.control, "fixed");
                assert.ok(Array.isArray(row.inputs.api_config));
                assert.equal(row.outputs, row.type === "Zhenzhen_Motion_Video" ? 10 : 4);
                if (row.type === "HY_Image_3_5_Preview") assert.equal(row.sockets, 6);
                if (row.type === "Flux_3_Image_Variants") assert.equal(row.sockets, 11);
                if (row.type.startsWith("Muse")) assert.equal(row.sockets, 10);
            }
            if (process.env.SEEDANCE_UI_SCREENSHOT_DIR && /自定义|klein-i2i|MuseVideo多图/.test(filename)) {
                await page.keyboard.press("Escape");
                await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, filename.replace(/\.json$/, ".png")) });
            }
            console.log(`CANVAS PASS ${filename}: switches, resize, reload, links, seed and serialization`);
        }
        for (const kind of KEYS) {
            const report = await page.evaluate(async ({ kind, models }) => {
                const app = window.__previewApp;
                app.graph.clear();
                const node = window.LiteGraph.createNode(`SeedanceConcurrent_${kind}_Submit`);
                app.graph.add(node);
                node.pos = [150, 100];
                await new Promise((resolve) => setTimeout(resolve, 80));
                const widget = node.widgets.find((item) => item.name === "model");
                if (widget) for (const model of models) {
                    widget.value = model; widget.callback?.(model);
                    await new Promise((resolve) => setTimeout(resolve, 20));
                }
                node.widgets.find((item) => item.name === "control_after_generate").value = "fixed";
                node.setSize([850, node.size[1]]);
                node.setSize([460, node.size[1]]);
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 100));
                const restored = app.graph._nodes[0];
                return { type: restored.outputs[0].type, sockets: restored.inputs.length,
                    control: restored.widgets.find((item) => item.name === "control_after_generate").value };
            }, { kind, models: MODELS });
            assert.equal(report.type, kind === "Muse_Video" ? "SEEDANCE_VIDEO_FUTURE" : "SEEDANCE_IMAGE_FUTURE");
            assert.equal(report.control, "fixed");
            console.log(`CANVAS PASS concurrent ${kind}`);
        }
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
