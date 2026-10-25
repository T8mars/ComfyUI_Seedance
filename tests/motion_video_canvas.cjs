// Optional acceptance test against an isolated ComfyUI server; no API calls.
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
        await page.goto(process.env.SEEDANCE_MOTION_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__motionApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__motionApp?.graph);
        await page.keyboard.press("Escape");
        for (const pro of [false, true]) {
            for (const revision of [false, true]) {
                const filename = `MotionVideo${pro ? "Pro" : "Standard"}${revision ? "成片修订" : "动效生成"}.json`;
                const workflow = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "examples", filename), "utf8"));
                const report = await page.evaluate(async ({ workflow, revision }) => {
                    const app = window.__motionApp;
                    await app.loadGraphData(workflow);
                    await new Promise((resolve) => setTimeout(resolve, 250));
                    let node = app.graph._nodes.find((item) => Number(item.id) === (revision ? 4 : 2));
                    const widget = (name) => node.widgets.find((item) => item.name === name);
                    for (const model of widget("model").options.values) {
                        widget("model").value = model;
                        widget("model").callback?.(model);
                        node.setSize([800, node.size[1]]);
                        node.setSize([460, node.size[1]]);
                    }
                    widget("model").value = workflow.nodes.find((item) => Number(item.id) === Number(node.id)).widgets_values[0];
                    for (const value of ["generate", "revise", revision ? "revise" : "generate"]) {
                        widget("operation").value = value;
                        widget("operation").callback?.(value);
                        await new Promise((resolve) => setTimeout(resolve, 40));
                    }
                    await app.loadGraphData(app.graph.serialize());
                    await new Promise((resolve) => setTimeout(resolve, 250));
                    node = app.graph._nodes.find((item) => Number(item.id) === (revision ? 4 : 2));
                    const prompt = await app.graphToPrompt();
                    app.canvas.ds.scale = .62;
                    app.canvas.ds.offset = [100, 60];
                    app.canvas.setDirty(true, true);
                    return { inputs: prompt.output[String(node.id)].inputs,
                        hidden: widget("revision_instruction").type.startsWith("converted-widget:seedance-hidden"),
                        control: widget("control_after_generate").value,
                        outputs: node.outputs.length };
                }, { workflow, revision });
                assert.equal(report.inputs.model, `zhenzhen/motion-video${pro ? "-pro" : ""}`);
                assert.equal(report.inputs.operation, revision ? "revise" : "generate");
                assert.equal(report.inputs.duration, 15);
                assert.equal(report.hidden, !revision);
                assert.equal(report.control, "fixed");
                assert.equal(report.outputs, 10);
                if (revision) assert.deepEqual(report.inputs.revise_from, ["2", 2]);
                await page.keyboard.press("Escape");
                if (process.env.SEEDANCE_UI_SCREENSHOT_DIR) {
                    await page.screenshot({ path: path.join(process.env.SEEDANCE_UI_SCREENSHOT_DIR, filename.replace(/\.json$/, ".png")) });
                }
                console.log(`CANVAS PASS ${filename}: models, modes, resizing, reload, linked task and seed`);
            }
        }
        const concurrent = await page.evaluate(async () => {
            const app = window.__motionApp;
            app.graph.clear();
            const node = window.LiteGraph.createNode("SeedanceConcurrent_Zhenzhen_Motion_Video_Submit");
            app.graph.add(node);
            node.pos = [100, 80];
            const widget = (name) => node.widgets.find((item) => item.name === name);
            await new Promise((resolve) => setTimeout(resolve, 100));
            for (const operation of ["revise", "generate", "revise"]) {
                widget("operation").value = operation;
                widget("operation").callback?.(operation);
                node.setSize([780, node.size[1]]);
                node.setSize([460, node.size[1]]);
            }
            widget("control_after_generate").value = "fixed";
            await app.loadGraphData(app.graph.serialize());
            await new Promise((resolve) => setTimeout(resolve, 150));
            const restored = app.graph._nodes[0];
            return { output: restored.outputs[0].type,
                operation: restored.widgets.find((item) => item.name === "operation").value,
                revisionType: restored.widgets.find((item) => item.name === "revision_instruction").type };
        });
        assert.equal(concurrent.output, "SEEDANCE_VIDEO_FUTURE");
        assert.equal(concurrent.operation, "revise");
        assert.ok(!concurrent.revisionType.startsWith("converted-widget:seedance-hidden"));
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS concurrent submit; zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
