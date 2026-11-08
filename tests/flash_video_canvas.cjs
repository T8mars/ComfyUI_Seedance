// Canvas serialization checks only; never submit generation tasks.
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
        await page.goto(process.env.SEEDANCE_IMAGE26_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__flashApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__flashApp?.graph);
        await page.keyboard.press("Escape");
        const directory = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(directory).filter((file) => /^(zhenzhen-video-kling-v4-flash|zhenzhen-video-g-omni-1\.2-flash-lowprice).*\.json$/.test(file));
        assert.equal(files.length, 8);
        for (const filename of [...files, "kling-v4-omni图片视频参考.json", "kling-v4-omni主体音色连线.json"]) {
            const workflow = JSON.parse(fs.readFileSync(path.join(directory, filename), "utf8"));
            if (filename.startsWith("kling-v4-")) {
                for (const node of workflow.nodes) if (node.type === "Kling_V4_Omni") node.widgets_values.pop();
            }
            const report = await page.evaluate(async (workflow) => {
                const app = window.__flashApp;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 100));
                await app.loadGraphData(workflow); await settle();
                const source = app.graph._nodes.find((node) => ["Kling_V4_Omni", "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice"].includes(node.comfyClass));
                const model = source.widgets.find((widget) => widget.name === "model");
                const original = model?.value;
                const sockets = source.inputs.map((input) => input.name);
                if (model) for (const value of [...model.options.values, original]) {
                    model.value = value; model.callback?.(value); await settle();
                }
                source.setSize([850, source.size[1]]); source.setSize([460, source.size[1]]);
                await settle();
                await app.loadGraphData(app.graph.serialize()); await settle();
                const restored = app.graph.getNodeById(source.id);
                const prompt = await app.graphToPrompt();
                app.canvas.ds.scale = .7; app.canvas.ds.offset = [10, 20]; app.canvas.setDirty(true, true);
                return { original, sockets, restored: restored.inputs.map((input) => input.name),
                    inputs: prompt.output[String(restored.id)].inputs, outputs: restored.outputs.length,
                    fixed: restored.widgets.find((widget) => widget.name === "control_after_generate").value };
            }, workflow);
            assert.deepEqual(report.sockets, report.restored);
            assert.equal(report.outputs, 4);
            assert.equal(report.fixed, "fixed");
            assert.ok(Array.isArray(report.inputs.api_config));
            if (filename.startsWith("kling-v4-")) assert.equal(report.inputs.model, "kling-v4-omni");
            if (filename.startsWith("zhenzhen-video-kling")) assert.equal(report.inputs.model, "zhenzhen-video-kling-v4-flash");
            if (filename.includes("多图")) for (const field of ["image1", "image2"]) assert.ok(Array.isArray(report.inputs[field]));
            if (filename.includes("本地视频")) assert.ok(Array.isArray(report.inputs.video1));
            if (filename.includes("主体音色")) for (const field of ["image_element_ids", "voice_ids"]) assert.ok(Array.isArray(report.inputs[field]));
            console.log(`CANVAS PASS ${filename}: model switches, resize, reload, seed and stable links`);
        }
        for (const key of ["Kling_V4_Omni", "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice"]) {
            const report = await page.evaluate(async (key) => {
                const app = window.__flashApp;
                app.graph.clear();
                const node = window.LiteGraph.createNode(`SeedanceConcurrent_${key}_Submit`);
                const collector = window.LiteGraph.createNode("SeedanceConcurrent_Video_Await");
                app.graph.add(node); app.graph.add(collector);
                node.connect(0, collector, collector.inputs.findIndex((input) => input.name === "future_1"));
                const model = node.widgets.find((widget) => widget.name === "model");
                if (model) { model.value = "zhenzhen-video-kling-v4-flash"; model.callback?.(model.value); }
                node.widgets.find((widget) => widget.name === "control_after_generate").value = "fixed";
                node.setSize([800, node.size[1]]); node.setSize([460, node.size[1]]);
                await new Promise((resolve) => setTimeout(resolve, 100));
                await app.loadGraphData(app.graph.serialize());
                const prompt = await app.graphToPrompt();
                const restored = app.graph.getNodeById(node.id);
                return { type: restored.outputs[0].type, future: prompt.output[String(collector.id)].inputs.future_1,
                    sockets: restored.inputs.filter((input) => /^image\d+$/.test(input.name)).length };
            }, key);
            assert.equal(report.type, "SEEDANCE_VIDEO_FUTURE");
            assert.ok(Array.isArray(report.future));
            assert.equal(report.sockets, 10);
            console.log(`CONCURRENT PASS ${key}`);
        }
        if (process.env.SEEDANCE_REAL_GIF_PATH) {
            const entry = await page.evaluate(async (source) => {
                const app = window.__flashApp;
                app.graph.clear();
                const node = window.LiteGraph.createNode("Seedance_Save_GIF");
                app.graph.add(node); node.pos = [200, 100];
                const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ prompt: { [node.id]: { class_type: "Seedance_Save_GIF", inputs: {
                        filename_prefix: "seedance/nov08_gif_copy", source_mode: "original", source_path: source, fps: 10, loop: 0,
                    } } } }) });
                const submitted = await response.json();
                if (!response.ok) throw new Error(JSON.stringify(submitted));
                let record;
                for (let i = 0; i < 60; i++) {
                    record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                    if (record?.status?.completed) break;
                    await new Promise((resolve) => setTimeout(resolve, 200));
                }
                if (record?.status?.status_str !== "success") throw new Error("Local GIF save failed");
                const output = record.outputs[String(node.id)];
                node.onExecuted?.(output);
                app.canvas.ds.scale = 1; app.canvas.ds.offset = [10, 20]; app.canvas.setDirty(true, true);
                return output.images[0];
            }, process.env.SEEDANCE_REAL_GIF_PATH);
            const bytes = await (await page.request.get(new URL("/view?" + new URLSearchParams(entry), page.url()).href)).body();
            assert.ok(bytes.equals(fs.readFileSync(process.env.SEEDANCE_REAL_GIF_PATH)), "Saved GIF must retain original bytes");
            const preview = page.locator(".seedance-gif-preview img").first();
            await preview.waitFor();
            const frames = new Set();
            for (let i = 0; i < 8; i++) {
                frames.add(crypto.createHash("sha256").update(await preview.screenshot()).digest("hex"));
                await page.waitForTimeout(100);
            }
            assert.ok(frames.size > 1, "GIF preview must animate");
            console.log("GIF PASS: newly generated LowPrice GIF copies byte-for-byte, downloads and animates in the canvas");
        }
        if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, "flash-video-desktop.png") });
        assert.deepEqual(errors, []);
        console.log("Flash canvas checks passed with zero page errors and no generation requests.");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
