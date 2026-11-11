// Isolated acceptance reuses completed task responses; no generation POSTs escape the fixture.
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
        await page.goto(process.env.SEEDANCE55_UI_URL ?? "http://127.0.0.1:5198", { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__s55 = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__s55?.graph);
        await page.keyboard.press("Escape");
        const folder = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(folder).filter((name) => /5\.5|draft-to-video|Seedream55/.test(name));
        assert.equal(files.length, 11);
        const legacy = fs.readdirSync(folder).filter((name) => name.startsWith("seedance-2.5-") && !name.includes("draft-to-video"));
        for (const filename of [...files, ...legacy]) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            const report = await page.evaluate(async (workflow) => {
                const app = window.__s55;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 75));
                await app.loadGraphData(workflow); await settle();
                const sources = app.graph._nodes.filter((node) => ["Seedance_2_5_Video", "Seedance_2_5_Draft_To_Video", "Seedream_5_5_Image", "Seedream_5_5_Layer_Decomposition"].includes(node.comfyClass));
                const before = sources.map((node) => ({ id: node.id, inputs: node.inputs.map((input) => input.name), model: node.widgets.find((widget) => widget.name === "model").value }));
                for (const node of sources) {
                    const model = node.widgets.find((widget) => widget.name === "model");
                    const original = model.value;
                    for (const value of [...model.options.values, original]) { model.value = value; model.callback?.(value); await settle(); }
                    const draft = node.widgets.find((widget) => widget.name === "draft");
                    if (draft) { const value = draft.value; for (const next of [true, false, value]) { draft.value = next; draft.callback?.(next); await settle(); } }
                    node.setSize([900, node.size[1]]); node.setSize([510, node.size[1]]);
                }
                await app.loadGraphData(app.graph.serialize()); await settle();
                const prompt = await app.graphToPrompt();
                const validation = await (await fetch("/seedance55_fixture/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output }) })).json();
                return { validation, nodes: before.map((previous) => {
                    const node = app.graph.getNodeById(previous.id);
                    return { previous, inputs: node.inputs.map((input) => input.name), values: prompt.output[String(node.id)].inputs,
                        control: node.widgets.find((widget) => widget.name === "control_after_generate").value };
                }) };
            }, workflow);
            assert.equal(report.validation.valid, true, `${filename}: ${JSON.stringify(report.validation)}`);
            for (const node of report.nodes) {
                assert.deepEqual(node.previous.inputs, node.inputs);
                assert.equal(node.previous.model, node.values.model);
                assert.equal(node.control, "fixed");
                assert.ok(Array.isArray(node.values.api_config));
                if (legacy.includes(filename)) assert.equal(node.values.draft, false);
            }
            console.log(`CANVAS PASS ${filename}: switch, resize, reload, stable links and backend queue validation`);
        }
        const reuse = await (await page.request.post(new URL("/seedance55_fixture/reuse", page.url()).href, { data: {} })).json();
        assert.equal(reuse.ready, true);
        const output = process.env.SEEDANCE_UI_SCREENSHOT_DIR;
        if (output) fs.mkdirSync(output, { recursive: true });
        async function execute() {
            return page.evaluate(async () => {
                const app = window.__s55;
                const prompt = await app.graphToPrompt();
                const { api } = await import("/scripts/api.js");
                const response = await fetch("/prompt", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output, client_id: api.clientId }) });
                const submitted = await response.json();
                if (!response.ok) throw new Error(JSON.stringify(submitted));
                let record;
                for (let i = 0; i < 180; i++) {
                    record = (await (await fetch(`/history/${submitted.prompt_id}`)).json())[submitted.prompt_id];
                    if (record?.status?.completed) break;
                    await new Promise((resolve) => setTimeout(resolve, 500));
                }
                if (record?.status?.status_str !== "success") throw new Error("Local reuse execution failed: " + JSON.stringify(record?.status?.messages?.map((item) => item[0])));
                return record.outputs;
            });
        }
        const videos = process.env.SEEDANCE55_TEST_STAGE === "videos";
        const executions = files.filter((filename) => videos
            ? filename.includes("样片成片连线") && (!process.env.SEEDANCE55_VIDEO_REGION || filename.includes("global") === (process.env.SEEDANCE55_VIDEO_REGION === "global"))
            : filename.includes("5.5") || filename.includes("Seedream55"));
        for (const filename of executions) {
            const workflow = JSON.parse(fs.readFileSync(path.join(folder, filename), "utf8"));
            await page.evaluate(async (workflow) => {
                const app = window.__s55;
                await app.loadGraphData(workflow);
                for (const node of app.graph._nodes) {
                    if (node.comfyClass === "Seedance_Config") node.widgets.find((widget) => widget.name === "api_key").value = "sk-test";
                    const control = node.widgets?.find((widget) => widget.name === "control_after_generate");
                    if (control) control.value = "fixed";
                }
                app.canvas.ds.scale = .65; app.canvas.ds.offset = [10, 20]; app.canvas.setDirty(true, true);
            }, workflow);
            const result = await execute();
            const saves = workflow.nodes.filter((node) => node.type === (videos ? "SaveVideo" : "SaveImage"));
            const entries = saves.flatMap((node) => result[String(node.id)]?.images ?? []);
            if (videos) {
                assert.equal(entries.length, 2, "Both draft and enhanced video must be saved");
                if (output) for (let index = 0; index < entries.length; index++) {
                    const bytes = await (await page.request.get(new URL("/view?"+new URLSearchParams(entries[index]), page.url()).href)).body();
                    assert.ok(bytes.length > 1000);
                    fs.writeFileSync(path.join(output, filename+`-${index}.saved`+path.extname(entries[index].filename)), bytes);
                }
            }
            if (!videos) {
                assert.equal(entries.length, filename.includes("分层") ? 2 : 1);
                for (let index = 0; index < entries.length; index++) {
                    const bytes = await (await page.request.get(new URL("/view?"+new URLSearchParams(entries[index]), page.url()).href)).body();
                    assert.ok(bytes.length > 1000);
                    if (output) fs.writeFileSync(path.join(output, filename+`-${index}.saved.png`), bytes);
                }
                const countUrl = new URL("/seedance55_fixture/counts", page.url()).href;
                const before = await (await page.request.get(countUrl)).json();
                await execute();
                const after = await (await page.request.get(countUrl)).json();
                assert.deepEqual(after, before, "Fixed rerun must not resubmit completed inputs");
                if (output && filename.includes("分层")) {
                    await page.waitForTimeout(700);
                    await page.screenshot({ path: path.join(output, filename+".desktop.png") });
                    await page.setViewportSize({ width: 390, height: 844 });
                    await page.evaluate(() => { const app=window.__s55; app.canvas.ds.scale=.35; app.canvas.ds.offset=[-300,120]; app.canvas.setDirty(true,true); });
                    await page.waitForTimeout(400);
                    await page.screenshot({ path: path.join(output, filename+".mobile.png") });
                    await page.setViewportSize({ width: 1700, height: 1100 });
                }
            }
            console.log(`NATIVE REUSE PASS ${filename}: actual node download/decode and native saving${videos ? "" : ", original alpha/list outputs and Fixed caching"}`);
        }
        if (!videos) {
            const built = await page.evaluate(async () => {
                const app=window.__s55; app.graph.clear();
                const create=(type)=>{const node=window.LiteGraph.createNode(type);app.graph.add(node);return node;};
                const config=create("Seedance_Config");config.widgets.find((w)=>w.name==="api_key").value="sk-test";
                const a=create("SeedanceConcurrent_Seedream_5_5_Image_Submit"),b=create("SeedanceConcurrent_Seedream_5_5_Image_Submit"),collector=create("SeedanceConcurrent_Image_Await");
                for(const [node,model] of [[a,"seedream-v5.5-t2i"],[b,"dola-seedream-5.5-t2i"]]){
                    node.widgets.find((w)=>w.name==="model").value=model;
                    node.widgets.find((w)=>w.name==="prompt").value="An isolated green leaf on transparent background";
                    node.widgets.find((w)=>w.name==="skip_error").value=true;
                    node.widgets.find((w)=>w.name==="control_after_generate").value="fixed";
                    config.connect(0,node,node.inputs.findIndex((i)=>i.name==="api_config"));
                }
                a.connect(0,collector,collector.inputs.findIndex((i)=>i.name==="future_1"));
                b.connect(0,collector,collector.inputs.findIndex((i)=>i.name==="future_2"));
                const saveIds=[];
                for(const slot of [0,1]){const save=create("SaveImage");save.widgets[0].value="seedance55_concurrent_"+slot;collector.connect(slot,save,0);saveIds.push(save.id);}
                return saveIds;
            });
            await page.request.post(new URL("/seedance55_fixture/fail-once",page.url()).href,{data:{case:"domestic_t2i"}});
            const result=await execute();
            assert.ok(built.every((id)=>result[String(id)]?.images?.length===1));
            console.log("NATIVE REUSE PASS concurrent RGBA save with one skipped sibling failure");
        }
        assert.deepEqual(errors, []);
        console.log("PASS zero page errors; task creation blocked by isolated fixture");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
