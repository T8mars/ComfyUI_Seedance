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
        await page.goto(process.env.H3_TURBO_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__h3 = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__h3?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        const skipVideo = process.env.H3_TURBO_SKIP_VIDEO === "1";
        const files = fs.readdirSync(folder).filter((name) => /^(minimax-h3-comfyui-max|minimax-h3-image|qwen-image-2.1-turbo)/.test(name) && (!skipVideo || !name.includes("comfyui-max")));
        assert.equal(files.length, skipVideo ? 4 : 8);
        const reuse = await (await page.request.post(new URL("/h3_turbo_fixture/reuse", page.url()).href, { data: {} })).json();
        assert.ok(reuse.ready && reuse.recorded >= (skipVideo ? 4 : 6));
        async function execute() {
            return page.evaluate(async () => {
                const app = window.__h3;
                const graph = await app.graphToPrompt();
                const { api } = await import("/scripts/api.js");
                const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: graph.output, client_id: api.clientId }) });
                const submitted = await response.json();
                if (!response.ok) throw new Error(JSON.stringify(submitted));
                for (let i = 0; i < 240; i++) {
                    const record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                    if (record?.status?.completed) {
                        if (record.status.status_str !== "success") throw new Error("Native execution failed: " + JSON.stringify(record.status.messages.map((m) => m[0])));
                        return record.outputs;
                    }
                    await new Promise((resolve) => setTimeout(resolve, 500));
                }
                throw new Error("Native execution timed out");
            });
        }
        for (const filename of files) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const validation = await page.evaluate(async (workflow) => {
                const app = window.__h3;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => setTimeout(resolve, 100));
                const original = app.graph._nodes.find((n) => /^(Minimax_H3_|Qwen_Image_2_1_Turbo)/.test(n.comfyClass));
                const before = original.inputs.map((input) => ({ name: input.name, link: input.link }));
                original.setSize([900, original.size[1]]); original.setSize([510, original.size[1]]);
                await app.loadGraphData(app.graph.serialize());
                await new Promise((resolve) => setTimeout(resolve, 100));
                const node = app.graph.getNodeById(original.id);
                const after = node.inputs.map((input) => ({ name: input.name, link: input.link }));
                if (JSON.stringify(before) !== JSON.stringify(after)) throw new Error("Socket/link mutation");
                for (const item of app.graph._nodes) {
                    if (item.comfyClass === "Seedance_Config") item.widgets.find((w) => w.name === "api_key").value = "sk-test";
                }
                app.canvas.ds.scale = .65; app.canvas.ds.offset = [10, 20]; app.canvas.setDirty(true,true);
                const prompt = await app.graphToPrompt();
                return (await fetch("/h3_turbo_fixture/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output }) })).json();
            }, workflow);
            assert.equal(validation.valid, true, filename+": "+JSON.stringify(validation));
            const result = await execute();
            const save = workflow.nodes.find((n) => n.type === (filename.includes("comfyui-max") ? "SaveVideo" : "SaveImage"));
            const images = result[String(save.id)]?.images;
            assert.equal(images?.length, 1, filename+": native save");
            const response = await page.request.get(new URL("/view?"+new URLSearchParams(images[0]), page.url()).href);
            assert.equal(response.status(), 200);
            assert.ok((await response.body()).length > 1000);
            const countURL = new URL("/h3_turbo_fixture/counts", page.url()).href;
            const before = await (await page.request.get(countURL)).json();
            await execute();
            assert.deepEqual(await (await page.request.get(countURL)).json(), before, "Fixed inputs must stay cached");
            console.log("NATIVE PASS "+filename+": resize/reload/stable sockets/queue/save/Fixed cache");
        }
        const keys = ["Minimax_H3_ComfyUI_Max", "Minimax_H3_Image", "Qwen_Image_2_1_Turbo"];
        for (const key of keys) for (const concurrent of [false, true]) {
            const report = await page.evaluate(async ({key,concurrent}) => {
                const app = window.__h3; app.graph.clear();
                const node = LiteGraph.createNode(concurrent ? "SeedanceConcurrent_"+key+"_Submit" : key); app.graph.add(node);
                node.pos = [50, 60]; node.widgets.find((w) => w.name === "prompt").value = "A blue ceramic teapot on a white studio table.";
                const text = LiteGraph.createNode("PrimitiveStringMultiline"); app.graph.add(text);
                text.widgets.find((w) => w.name === "value").value = "A blue ceramic teapot on a white studio table.";
                const prompt = node.widgets.find((w) => w.name === "prompt");
                window.comfyAPI.widgetInputs.convertToInput(node, prompt);
                text.connect(0,node,node.inputs.findIndex((input) => input.name === "prompt"));
                if (concurrent) {
                    const collector = LiteGraph.createNode(key.includes("ComfyUI") ? "SeedanceConcurrent_Video_Await" : "SeedanceConcurrent_Image_Await");
                    if (!collector) return { collectorMissing: true };
                    app.graph.add(collector); collector.pos = [650,60];
                    node.connect(0,collector,collector.inputs.findIndex((i) => i.name === "future_1"));
                }
                node.setSize([900,node.size[1]]); node.setSize([500,node.size[1]]);
                await app.loadGraphData(app.graph.serialize());
                const graph = await app.graphToPrompt();
                return (await fetch("/h3_turbo_fixture/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: graph.output }) })).json();
            }, {key,concurrent});
            assert.equal(report.valid, true, key+" concurrent="+concurrent+": "+JSON.stringify(report));
        }
        const savedIds = await page.evaluate(() => {
            const app = window.__h3; app.graph.clear();
            const create = (key) => { const node=LiteGraph.createNode(key); app.graph.add(node); return node; };
            const config = create("Seedance_Config");
            config.widgets.find((w) => w.name === "api_key").value = "sk-test";
            const a=create("SeedanceConcurrent_Minimax_H3_Image_Submit");
            const b=create("SeedanceConcurrent_Qwen_Image_2_1_Turbo_Submit");
            for (const node of [a,b]) {
                node.widgets.find((w) => w.name === "prompt").value = "A blue ceramic teapot on a white studio table.";
                node.widgets.find((w) => w.name === "skip_error").value = true;
                node.widgets.find((w) => w.name === "control_after_generate").value = "fixed";
                config.connect(0,node,node.inputs.findIndex((i) => i.name === "api_config"));
            }
            const collector=create("SeedanceConcurrent_Image_Await");
            a.connect(0,collector,collector.inputs.findIndex((i) => i.name === "future_1"));
            b.connect(0,collector,collector.inputs.findIndex((i) => i.name === "future_2"));
            return [0,1].map((slot) => { const save=create("SaveImage"); collector.connect(slot,save,0); return save.id; });
        });
        await page.request.post(new URL("/h3_turbo_fixture/fail-once",page.url()).href,{ data: { case: "minimax_text" } });
        const concurrentResult=await execute();
        assert.ok(savedIds.every((id) => concurrentResult[String(id)]?.images?.length === 1));
        console.log("NATIVE PASS mixed-model concurrent image saves with one skipped failure");
        const output = process.env.H3_TURBO_SCREENSHOTS;
        if (output) {
            fs.mkdirSync(output, { recursive: true });
            await page.evaluate(async (workflow) => {
                const app=window.__h3; await app.loadGraphData(workflow);
                const node=app.graph._nodes.find((n) => n.comfyClass === "Minimax_H3_Image");
                app.canvas.ds.scale=.8; app.canvas.centerOnNode(node); app.canvas.setDirty(true,true);
            },JSON.parse(fs.readFileSync(path.join(folder,"minimax-h3-image图像编辑.json"),"utf8")));
            await page.waitForTimeout(250);
            await page.screenshot({ path: path.join(output,"desktop.png") });
            await page.setViewportSize({ width: 390, height: 844 });
            await page.waitForTimeout(400);
            await page.evaluate(() => { const app=window.__h3; app.canvas.ds.scale = .62; app.canvas.centerOnNode(app.graph._nodes.find((n) => n.comfyClass === "Minimax_H3_Image")); app.canvas.ds.offset[0] += 40; app.canvas.setDirty(true,true); });
            await page.waitForTimeout(200);
            await page.screenshot({ path: path.join(output,"mobile.png") });
        }
        assert.deepEqual(errors, []);
        console.log("PASS three concurrent schemas, native saves, Fixed cache and zero page errors; no generation POSTs");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
