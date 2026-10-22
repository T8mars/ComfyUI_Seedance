// Optional real-canvas acceptance: requires a running isolated ComfyUI and Playwright.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.SEEDANCE_MOSS_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__mossApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__mossApp?.graph);
        await page.keyboard.press("Escape");
        for (const mode of ["文生图", "图像编辑"]) {
            const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "examples", `moss-image${mode}.json`), "utf8"));
            const report = await page.evaluate(async (workflow) => {
                const app = window.__mossApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 250));
                let node = app.graph._nodes.find((item) => item.comfyClass === "Moss_Image");
                for (const ratio of node.widgets.find((item) => item.name === "ratio").options.values) {
                    const widget = node.widgets.find((item) => item.name === "ratio");
                    widget.value = ratio;
                    widget.callback?.(ratio);
                    node.setSize([720, node.size[1]]);
                    node.setSize([480, node.size[1]]);
                }
                node.widgets.find((item) => item.name === "ratio").value = "9:16";
                const saved = app.graph.serialize();
                await app.loadGraphData(saved);
                await new Promise((resolve) => setTimeout(resolve, 250));
                node = app.graph._nodes.find((item) => item.comfyClass === "Moss_Image");
                const prompt = await app.graphToPrompt();
                const inputs = prompt.output[String(node.id)].inputs;
                app.canvas.ds.scale = .85;
                app.canvas.ds.offset = [10, 60];
                app.canvas.setDirty(true, true);
                return { ratio: inputs.ratio, seed: inputs.seed, hasReference: Array.isArray(inputs.image1),
                    sockets: node.inputs.filter((item) => ["image1", "api_config"].includes(item.name)).map((item) => item.name),
                    control: node.widgets.find((item) => item.name === "control_after_generate")?.value,
                    forbidden: node.widgets.filter((item) => ["n", "resolution", "width", "height", "output_format"].includes(item.name)).map((item) => item.name) };
            }, workflow);
            assert.equal(report.ratio, "9:16");
            assert.equal(report.seed, 0);
            assert.equal(report.control, "fixed");
            assert.equal(report.hasReference, mode === "图像编辑");
            assert.deepEqual(report.sockets, ["image1", "api_config"]);
            assert.deepEqual(report.forbidden, []);
            await page.keyboard.press("Escape");
            await page.waitForTimeout(250);
            if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) {
                await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, mode === "文生图" ? "moss-text.png" : "moss-edit.png") });
            }
            console.log(`CANVAS PASS Moss ${mode}: ratios, resize, reload, seed and API prompt serialization`);
        }
        const concurrent = await page.evaluate(async () => {
            const app = window.__mossApp;
            const node = window.LiteGraph.createNode("SeedanceConcurrent_Moss_Image_Submit");
            app.graph.clear();
            app.graph.add(node);
            node.pos = [200, 150];
            await new Promise((resolve) => setTimeout(resolve, 250));
            const widget = node.widgets.find((item) => item.name === "ratio");
            const ratios = [...widget.options.values];
            widget.value = "16:9";
            widget.callback?.("16:9");
            node.widgets.find((item) => item.name === "control_after_generate").value = "fixed";
            node.setSize([800, node.size[1]]);
            node.setSize([440, node.size[1]]);
            await app.loadGraphData(app.graph.serialize());
            await new Promise((resolve) => setTimeout(resolve, 250));
            const restored = app.graph._nodes.find((item) => item.comfyClass === "SeedanceConcurrent_Moss_Image_Submit");
            return { ratios, ratio: restored.widgets.find((item) => item.name === "ratio").value,
                output: restored.outputs[0].type, control: restored.widgets.find((item) => item.name === "control_after_generate").value };
        });
        assert.equal(concurrent.ratios.length, 8);
        assert.equal(concurrent.ratio, "16:9");
        assert.equal(concurrent.output, "SEEDANCE_IMAGE_FUTURE");
        assert.equal(concurrent.control, "fixed");
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS Moss concurrent submit: stable Future output and controls; zero page errors.");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
