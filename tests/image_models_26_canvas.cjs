// Isolated canvas acceptance; fixtures replay downloaded GIFs without API calls.
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
        await page.evaluate(async () => { window.__image26App = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__image26App?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        const keys = ["Zhenzhen_Image_G26", "Krea_V3_Image", "Z_Image_T2I"];
        const files = fs.readdirSync(folder).filter((file) => /^(zhenzhen-image-g-v2\.6-|krea-v3-|z-image-t2i)/.test(file));
        assert.equal(files.length, 12);
        for (const filename of files) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const report = await page.evaluate(async ({ workflow, keys }) => {
                const app = window.__image26App;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 120));
                let node = app.graph._nodes.find((node) => keys.includes(node.comfyClass));
                const sockets = node.inputs.filter((input) => ["IMAGE", "SEEDANCE_CONFIG"].includes(input.type)).map((input) => input.name);
                for (const field of ["model", "mode", "size", "frame_size", "output_format"]) {
                    const widget = node.widgets.find((item) => item.name === field);
                    if (!widget) continue;
                    const original = widget.value;
                    for (const value of [...widget.options.values, original]) {
                        widget.value = value; widget.callback?.(value);
                        await new Promise((resolve) => setTimeout(resolve, 20));
                    }
                }
                node.setSize([850, node.size[1]]);
                node.setSize([480, node.size[1]]);
                const saved = app.graph.serialize();
                await app.loadGraphData(saved);
                await new Promise((resolve) => setTimeout(resolve, 120));
                node = app.graph._nodes.find((node) => keys.includes(node.comfyClass));
                const prompt = await app.graphToPrompt();
                return { type: node.comfyClass, outputs: node.outputs.length, sockets,
                    restored: node.inputs.filter((input) => ["IMAGE", "SEEDANCE_CONFIG"].includes(input.type)).map((input) => input.name),
                    control: node.widgets.find((widget) => widget.name === "control_after_generate").value,
                    inputs: prompt.output[String(node.id)].inputs };
            }, { workflow, keys });
            assert.equal(report.outputs, report.type === keys[0] ? 8 : 4);
            assert.equal(report.control, "fixed");
            assert.deepEqual(report.sockets, report.restored);
            assert.ok(Array.isArray(report.inputs.api_config));
            if (filename.includes("图像编辑")) assert.ok(Array.isArray(report.inputs.image1));
            console.log(`CANVAS PASS ${filename}`);
        }
        for (const key of keys) {
            const report = await page.evaluate(async (key) => {
                const app = window.__image26App;
                app.graph.clear();
                const node = window.LiteGraph.createNode(`SeedanceConcurrent_${key}_Submit`);
                app.graph.add(node);
                await new Promise((resolve) => setTimeout(resolve, 80));
                const model = node.widgets.find((widget) => widget.name === "model");
                if (model) for (const value of model.options.values) {
                    model.value = value; model.callback?.(value);
                    const mode = node.widgets.find((widget) => widget.name === "mode");
                    if (mode) for (const value of mode.options.values) {
                        mode.value = value; mode.callback?.(value);
                        await new Promise((resolve) => setTimeout(resolve, 20));
                    }
                }
                node.setSize([850, node.size[1]]); node.setSize([480, node.size[1]]);
                node.widgets.find((widget) => widget.name === "control_after_generate").value = "fixed";
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 80));
                return app.graph._nodes[0].outputs[0].type;
            }, key);
            assert.equal(report, "SEEDANCE_IMAGE_FUTURE");
            console.log(`CANVAS PASS concurrent ${key}`);
        }
        const concurrentWorkflow = JSON.parse(fs.readFileSync(path.join(folder, "G26GIF三模型并发.json"), "utf8"));
        const concurrentExample = await page.evaluate(async (workflow) => {
            const app = window.__image26App;
            await app.loadGraphData(workflow);
            await new Promise((resolve) => setTimeout(resolve, 120));
            const prompt = await app.graphToPrompt();
            const sources = app.graph._nodes.filter((node) => node.comfyClass === "SeedanceConcurrent_Zhenzhen_Image_G26_Submit");
            const collector = app.graph._nodes.find((node) => node.comfyClass === "SeedanceConcurrent_Image_Await");
            return { models: sources.map((node) => prompt.output[String(node.id)].inputs.model),
                fixed: sources.every((node) => node.widgets.find((widget) => widget.name === "control_after_generate").value === "fixed"),
                inputs: prompt.output[String(collector.id)].inputs, outputs: collector.outputs.length };
        }, concurrentWorkflow);
        assert.equal(concurrentExample.models.length, 3);
        assert.equal(new Set(concurrentExample.models).size, 3);
        assert.ok(concurrentExample.fixed);
        assert.equal(concurrentExample.outputs, 31);
        for (let i = 1; i <= 3; i++) assert.ok(Array.isArray(concurrentExample.inputs[`future_${i}`]));
        console.log("CANVAS PASS three-model GIF concurrency workflow");
        const info = await (await page.request.get(new URL("/object_info/SeedanceGIFPreviewFixture", page.url()).href)).json();
        const gifs = info.SeedanceGIFPreviewFixture.input.required.filename[0];
        assert.equal(gifs.length, 3);
        for (const concurrent of [false, true]) {
            const preview = await page.evaluate(async ({ filenames, concurrent }) => {
                const app = window.__image26App;
                app.graph.clear();
                let target;
                if (concurrent) {
                    target = window.LiteGraph.createNode("SeedanceConcurrent_Image_Await");
                    app.graph.add(target);
                }
                const sources = filenames.map((filename, index) => {
                    const node = window.LiteGraph.createNode(concurrent ? "SeedanceGIFFutureFixture" : "SeedanceGIFPreviewFixture");
                    if (!node) throw new Error("Fixture not registered");
                    app.graph.add(node);
                    node.widgets.find((widget) => widget.name === "filename").value = filename;
                    if (concurrent) node.connect(0, target, target.inputs.findIndex((input) => input.name === `future_${index + 1}`));
                    return node;
                });
                const prompt = await app.graphToPrompt();
                const { api } = await import("/scripts/api.js");
                const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ prompt: prompt.output, client_id: api.clientId }) });
                const submitted = await response.json();
                if (!response.ok) throw new Error(JSON.stringify(submitted));
                let record;
                for (let index = 0; index < 60; index++) {
                    record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                    if (record?.status?.completed) break;
                    await new Promise((resolve) => setTimeout(resolve, 500));
                }
                if (record?.status?.status_str !== "success") throw new Error(JSON.stringify(record?.status));
                const outputs = (concurrent ? [target] : sources).map((node) => record.outputs[String(node.id)]);
                app.graph.clear();
                const production = window.LiteGraph.createNode(concurrent ? "SeedanceConcurrent_Image_Await" : "Zhenzhen_Image_G26");
                app.graph.add(production);
                if (!concurrent) {
                    const mode = production.widgets.find((widget) => widget.name === "mode");
                    mode.value = "gif"; mode.callback?.("gif");
                }
                production.pos = [100, 80];
                production.setSize([650, concurrent ? 1150 : 900]);
                const entries = outputs.flatMap((output) => output.images);
                app.nodeOutputs[String(production.id)] = { images: entries, animated: [true] };
                production.onExecuted?.({ images: entries, animated: [true] });
                app.canvas.ds.scale = .72; app.canvas.ds.offset = [200, 20]; app.canvas.setDirty(true, true);
                return { entries, outputs: outputs.map((output) => ({ animated: output.animated, count: output.images.length })) };
            }, { filenames: gifs, concurrent });
            assert.equal(preview.entries.length, 3);
            assert.ok(preview.outputs.every((output) => output.animated[0]));
            for (const entry of preview.entries) {
                const response = await page.request.get(new URL("/view?" + new URLSearchParams(entry), page.url()).href);
                assert.equal(response.status(), 200);
                const data = await response.body();
                assert.equal(data.subarray(0, 3).toString(), "GIF");
            }
            await page.waitForTimeout(1000);
            await page.keyboard.press("Escape");
            const animation = await page.evaluate(() => {
                const images = [...document.querySelectorAll(".seedance-gif-preview img")].filter((image) => image.naturalWidth > 100);
                if (images.length !== 3) throw new Error("Expected three animated GIF previews");
                const image = images[0];
                return { count: images.length, width: image.naturalWidth, height: image.naturalHeight,
                    bounds: image.getBoundingClientRect().toJSON(),
                    previewType: window.__image26App.graph._nodes[0].previewMediaType };
            });
            animation.changes = [];
            for (let index = 0; index < 3; index++) {
                const hashes = new Set();
                const previewImage = page.locator(".seedance-gif-preview img").nth(index);
                for (let frame = 0; frame < 8; frame++) {
                    hashes.add(require("node:crypto").createHash("sha256").update(await previewImage.screenshot()).digest("hex"));
                    await page.waitForTimeout(110);
                }
                animation.changes.push(hashes.size);
            }
            assert.ok(animation.changes.every((count) => count > 1), "GIF preview does not advance frames");
            const link = page.locator(".seedance-gif-preview a").first();
            const [download] = await Promise.all([page.waitForEvent("download"), link.click()]);
            assert.ok(download.suggestedFilename().endsWith(".gif"));
            assert.equal(await download.failure(), null);
            if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) {
                const saved = path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, concurrent ? "concurrent-download.gif" : "serial-download.gif");
                await download.saveAs(saved);
                const response = await page.request.get(new URL("/view?" + new URLSearchParams(preview.entries[0]), page.url()).href);
                assert.ok(fs.readFileSync(saved).equals(await response.body()), "Download changed the original GIF bytes");
            }
            console.log(`GIF PASS ${concurrent ? "concurrent" : "serial"}: three moving previews and original-GIF download`, animation);
            const directory = process.env.SEEDANCE_UI_SCREENSHOT_DIR;
            if (directory) await page.screenshot({ path: path.join(directory, concurrent ? "g26-concurrent.png" : "g26-serial.png") });
        }
        await page.setViewportSize({ width: 390, height: 844 });
        await page.evaluate(() => {
            const app = window.__image26App;
            app.canvas.ds.scale = .35; app.canvas.ds.offset = [30, 40]; app.canvas.setDirty(true, true);
        });
        await page.waitForTimeout(400);
        assert.ok(await page.locator(".seedance-gif-preview img").count() >= 3);
        if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, "g26-mobile.png") });
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
