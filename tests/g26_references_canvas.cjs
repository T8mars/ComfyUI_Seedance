// Canvas-only acceptance: no task submission or external media.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(process.env.SEEDANCE_IMAGE26_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__refsApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__refsApp?.graph);
        await page.keyboard.press("Escape");
        for (const name of ["Zhenzhen_Image_G26", "SeedanceConcurrent_Zhenzhen_Image_G26_Submit"]) {
            const report = await page.evaluate(async (name) => {
                const app = window.__refsApp;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 80));
                app.graph.clear();
                const node = window.LiteGraph.createNode(name);
                const source = window.LiteGraph.createNode("EmptyImage");
                const config = window.LiteGraph.createNode("Seedance_Config");
                for (const item of [node, source, config]) app.graph.add(item);
                node.pos = [480, 40]; source.pos = [40, 80]; config.pos = [40, 400];
                const slot = (field) => node.inputs.findIndex((input) => input.name === field);
                const input = (field) => node.inputs[slot(field)];
                const widget = (field) => node.widgets.find((item) => item.name === field);
                const change = async (field, value) => {
                    widget(field).value = value; widget(field).callback?.(value); await settle();
                };
                config.connect(0, node, slot("api_config"));
                widget("prompt").value = "Combine sixteen reference images in order";
                widget("control_after_generate").value = "fixed";
                if (name.startsWith("SeedanceConcurrent")) {
                    const collector = window.LiteGraph.createNode("SeedanceConcurrent_Image_Await");
                    app.graph.add(collector);
                    collector.pos = [1060, 40];
                    node.connect(0, collector, collector.inputs.findIndex((input) => input.name === "future_1"));
                }
                await settle();
                const progressive = [];
                for (let i = 1; i <= 16; i++) {
                    progressive.push(!input(`image${i}`).hidden);
                    source.connect(0, node, slot(`image${i}`));
                    await settle();
                }
                const lowprice = !input("image16").hidden;
                await change("mode", "gif");
                const gif = !input("image16").hidden && input("image16").link != null;
                await change("model", "zhenzhen-image-g-v2.6-flare");
                const retained = !input("image10").hidden && input("image10").link != null;
                await change("mode", "image");
                const official = !input("image11").hidden;
                source.connect(0, node, slot("image11"));
                await change("model", "zhenzhen-image-g-v2.6-lowprice");
                const excessRetained = !input("image11").hidden && input("image11").link != null;
                await settle();
                node.setSize([850, node.size[1]]); node.setSize([480, node.size[1]]);
                await settle();
                await app.loadGraphData(app.graph.serialize());
                await settle();
                const restored = app.graph.getNodeById(node.id);
                const prompt = await app.graphToPrompt();
                const visible = restored.inputs.filter((input) => /^image\d+$/.test(input.name) && !input.hidden).map((input) => input.name);
                const sockets = restored.inputs.filter((input) => /^image\d+$/.test(input.name)).map((input) => input.name);
                const submitted = prompt.output[String(node.id)].inputs;
                const control = restored.widgets.find((widget) => widget.name === "control_after_generate").value;
                app.canvas.ds.scale = .72; app.canvas.ds.offset = [10, 50]; app.canvas.setDirty(true, true);
                return { progressive, lowprice, gif, retained, official, excessRetained, visible, sockets, submitted, control,
                    outputs: restored.outputs.length };
            }, name);
            assert.ok(report.progressive.every(Boolean), "Reference sockets must appear progressively through image16");
            for (const field of ["lowprice", "gif", "retained", "official", "excessRetained"]) assert.ok(report[field], field);
            assert.deepEqual(report.sockets, Array.from({ length: 16 }, (_, i) => `image${i + 1}`));
            assert.deepEqual(report.visible, Array.from({ length: 16 }, (_, i) => `image${i + 1}`));
            for (let i = 1; i <= 16; i++) assert.ok(Array.isArray(report.submitted[`image${i}`]));
            assert.ok(Array.isArray(report.submitted.api_config));
            assert.equal(report.control, "fixed");
            assert.equal(report.outputs, name === "Zhenzhen_Image_G26" ? 8 : 1);
            if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({
                path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, `${name}-sixteen-references.png`),
            });
            console.log(`CANVAS PASS ${name}: sixteen progressive references, model/mode switches, resize, reload, fixed seed and stable sockets`);
        }
        const folder = path.join(__dirname, "..", "examples");
        for (const filename of fs.readdirSync(folder).filter((name) => /^zhenzhen-image-g-v2\.6-lowprice.*\.json$/.test(name))) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            if (filename === "zhenzhen-image-g-v2.6-lowprice文生图.json") {
                for (const node of workflow.nodes) if (node.type === "Zhenzhen_Image_G26") node.widgets_values.pop();
            }
            const report = await page.evaluate(async (workflow) => {
                const app = window.__refsApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 100));
                const node = app.graph._nodes.find((item) => item.comfyClass === "Zhenzhen_Image_G26");
                const prompt = await app.graphToPrompt();
                return { model: prompt.output[String(node.id)].inputs.model, mode: prompt.output[String(node.id)].inputs.mode,
                    refs: node.inputs.filter((input) => /^image\d+$/.test(input.name)).length,
                    saver: app.graph._nodes.some((item) => item.comfyClass === "Seedance_Save_GIF") };
            }, workflow);
            assert.equal(report.model, "zhenzhen-image-g-v2.6-lowprice");
            assert.equal(report.refs, 16);
            if (filename.includes("GIF")) assert.ok(report.saver);
            console.log(`LEGACY PASS ${filename}`);
        }
        if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, "g26-references.png") });
        assert.deepEqual(errors, []);
        console.log("Canvas acceptance passed without generation requests or browser page errors.");
    } finally {
        await browser.close();
    }
})().catch((error) => { console.error(error); process.exitCode = 1; });
