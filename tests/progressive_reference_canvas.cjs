// Real canvas and local graph serialization only. Never submit a generation task.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { cases } = require("./reference_input_cases.cjs");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) => {
            const request = route.request();
            if (request.method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(request.url())) return route.abort("blockedbyclient");
            return route.continue();
        });
        await page.goto(process.env.SEEDANCE_REFERENCE_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__refApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__refApp?.graph);
        await page.waitForTimeout(1000);
        await page.keyboard.press("Escape");
        const info = await (await page.request.get(new URL("/object_info", page.url()).href)).json();
        const filter = process.env.SEEDANCE_REFERENCE_NODE_FILTER;
        const selected = filter ? cases.filter(([, key]) => new RegExp(filter).test(key)) : cases;
        if (filter) assert.ok(selected.length, "No cases match SEEDANCE_REFERENCE_NODE_FILTER");
        let count = 0;
        for (const [, base, capacity, fallback] of process.env.SEEDANCE_REFERENCE_MOUSE_ONLY ? [] : selected) {
            for (const key of [base, `SeedanceConcurrent_${base}_Submit`].filter((name) => info[name])) {
                const fields = { ...info[key].input.required, ...info[key].input.optional };
                const models = Array.isArray(fields.model?.[0]) ? fields.model[0] : fallback.length ? fallback : [""];
                const report = await page.evaluate(async ({ key, models, capacity }) => {
                    const app = window.__refApp;
                    const settle = () => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                    const marker = "__seedance_hidden_input__";
                    const media = (node) => node.inputs.filter((input) => /^(image|video|audio)\d+$/.test(input.name));
                    const check = (node) => {
                        const rows = new Set();
                        for (const input of media(node).filter((input) => !input.hidden)) {
                            const position = node.getConnectionPos(true, node.inputs.indexOf(input), new Float32Array(2));
                            if (input.widget?.name === marker || position[0] < -50000 || position[1] < -50000) throw new Error(`${key}/${input.name} remains invisible`);
                            const concrete = node._concreteInputs.find((slot) => slot.name === input.name);
                            if (concrete?.widget?.name === marker) throw new Error(`${key}/${input.name} concrete slot remains hidden`);
                            if (rows.has(position[1])) throw new Error(`${key}/${input.name} overlaps another material slot`);
                            rows.add(position[1]);
                        }
                    };
                    const results = [];
                    for (const model of models) {
                        app.graph.clear();
                        let node = LiteGraph.createNode(key); app.graph.add(node); node.pos = [550, 90];
                        const selector = node.widgets.find((widget) => widget.name === "model");
                        if (selector && model) { selector.value = model; selector.callback?.(model); }
                        await settle();
                        const workflow = app.graph.serialize();
                        const saved = workflow.nodes.find((item) => item.type === key);
                        for (const input of saved.inputs.filter((input) => /^(image|video|audio)\d+$/.test(input.name))) {
                            input.pos = [-100000, -100000]; input.widget = { name: marker }; input.hidden = true;
                        }
                        await app.loadGraphData(workflow); await settle();
                        node = app.graph._nodes.find((node) => node.comfyClass === key);
                        const names = node.inputs.map((input) => input.name);
                        check(node);
                        const counts = {};
                        const flash = model === "zhenzhen-video-kling-v4-flash" || key.includes("Omni_1_2");
                        for (const family of Object.keys(capacity)) {
                            if (flash && family === "video") continue;
                            const source = LiteGraph.createNode("EmptyImage"); app.graph.add(source); source.pos = [90, 90];
                            source.outputs[0].type = family === "image" ? "IMAGE" : family === "video" ? "VIDEO" : "AUDIO";
                            let connected = 0;
                            for (let index = 1; index <= capacity[family]; index++) {
                                const slot = node.inputs.findIndex((input) => input.name === `${family}${index}`);
                                if (node.inputs[slot].hidden) break;
                                if (!source.connect(0, node, slot)) throw new Error(`${key}/${family}${index}: connect failed`);
                                await settle(); check(node); connected++;
                            }
                            counts[family] = connected;
                        }
                        const links = media(node).map((input) => input.link);
                        for (const width of [900, 510]) { node.setSize([width, node.size[1]]); await settle(); check(node); }
                        const serialized = app.graph.serialize();
                        const leaked = serialized.nodes.flatMap((n) => (n.inputs ?? []).filter((i) => i.widget?.name === marker || i.pos?.[0] === -100000).map((i) => [n.type, i.name, i.widget, i.pos]));
                        if (leaked.length) throw new Error(`${key}/${model}: Hidden presentation leaked ${JSON.stringify(leaked)}`);
                        await app.loadGraphData(serialized); await settle();
                        node = app.graph._nodes.find((node) => node.comfyClass === key); check(node);
                        if (JSON.stringify(node.inputs.map((input) => input.name)) !== JSON.stringify(names)) throw new Error("Input order changed");
                        if (JSON.stringify(media(node).map((input) => input.link)) !== JSON.stringify(links)) throw new Error("Links changed on reload");
                        results.push({ model, counts });
                    }
                    app.canvas.ds.scale = .7; app.canvas.centerOnNode(app.graph._nodes.find((node) => node.comfyClass === key)); app.canvas.setDirty(true, true);
                    return results;
                }, { key, models, capacity });
                const { limitsFor } = require("./reference_input_cases.cjs");
                for (const result of report) {
                    const expected = limitsFor(base, result.model, capacity);
                    for (const [family, connected] of Object.entries(result.counts)) assert.equal(connected, expected[family], `${key}/${result.model}/${family}: reaches API capacity`);
                }
                count += report.length;
                console.log(`CANVAS PASS ${key}: ${report.length} models, progressive expansion to capacity, old markers, resize, reload and stable links`);
                if (process.env.SEEDANCE_REFERENCE_SCREENSHOTS && (base === "Tripo_Generate" || base === "Zhenzhen_Image_NB_Lowprice")) {
                    fs.mkdirSync(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, { recursive: true });
                    await page.screenshot({ path: path.join(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, key + ".png") });
                }
            }
        }
        const mouseCases = filter ? selected.flatMap(([, key, { image }, fallback]) =>
            [key, `SeedanceConcurrent_${key}_Submit`].filter((name) => info[name]).map((name) => [name, fallback.at(-1), image]))
            : [["Zhenzhen_Image_NB_Lowprice", "zhenzhen-image-nb-pro-lowprice", 3], ["Tripo_Generate", "tripo-h-v3.1-multiview-to-3d", 3]];
        for (const [key, model, max] of mouseCases) {
            await page.evaluate(async ({ key, model }) => {
                const app = window.__refApp; app.graph.clear();
                const source = LiteGraph.createNode("EmptyImage"); app.graph.add(source); source.pos = [80, 80];
                const target = LiteGraph.createNode(key); app.graph.add(target); target.pos = [650, 80];
                const widget = target.widgets.find((widget) => widget.name === "model");
                if (widget && model) { widget.value = model; widget.callback?.(model); }
                await new Promise((r) => setTimeout(r, 100));
                const workflow = app.graph.serialize();
                const saved = workflow.nodes.find((node) => node.type === key);
                saved.inputs.find((input) => input.name === "image3").pos = [-100000, -100000];
                saved.inputs.find((input) => input.name === "image3").widget = { name: "__seedance_hidden_input__" };
                await app.loadGraphData(workflow);
                app.canvas.ds.scale = .8; app.canvas.ds.offset[0] = 0; app.canvas.ds.offset[1] = 0; app.canvas.setDirty(true, true);
            }, { key, model });
            for (let index = 1; index <= max; index++) {
                await page.waitForTimeout(120);
                const points = await page.evaluate(({ key, index }) => {
                    const app = window.__refApp, source = app.graph._nodes.find((node) => node.comfyClass === "EmptyImage"), target = app.graph._nodes.find((node) => node.comfyClass === key);
                    const slot = target.inputs.findIndex((input) => input.name === `image${index}`);
                    if (target.inputs[slot].hidden) throw new Error(`image${index} did not expand`);
                    const box = app.canvas.canvas.getBoundingClientRect(), ds = app.canvas.ds;
                    const screen = (point) => [box.left + (point[0] + ds.offset[0]) * ds.scale, box.top + (point[1] + ds.offset[1]) * ds.scale];
                    return { from: screen(source.getConnectionPos(false, 0, new Float32Array(2))), to: screen(target.getConnectionPos(true, slot, new Float32Array(2))) };
                }, { key, index });
                await page.mouse.move(...points.from); await page.mouse.down(); await page.mouse.move(...points.to, { steps: 12 }); await page.mouse.up();
                await page.waitForTimeout(120);
                assert.equal(await page.evaluate(({ key, index }) => window.__refApp.graph._nodes.find((node) => node.comfyClass === key).inputs.find((input) => input.name === `image${index}`).link != null, { key, index }), true, `${key}: real mouse connection image${index}`);
            }
            console.log(`MOUSE PASS ${key}: connected images 1 through ${max}`);
            if (process.env.SEEDANCE_REFERENCE_SCREENSHOTS) {
                fs.mkdirSync(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, { recursive: true });
                await page.screenshot({ path: path.join(process.env.SEEDANCE_REFERENCE_SCREENSHOTS, key + "-mouse.png") });
            }
        }
        for (const filename of process.env.SEEDANCE_REFERENCE_WORKFLOWS?.split(";") ?? []) {
            const graph = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "examples", filename), "utf8"));
            await page.evaluate(async (workflow) => {
                const app = window.__refApp;
                await app.loadGraphData(workflow);
                await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
                const { output } = await app.graphToPrompt();
                for (const saved of workflow.nodes.filter((node) => /Digital_Human|Image_GK_V15/.test(node.type))) {
                    const restored = app.graph.getNodeById(saved.id);
                    for (const original of saved.inputs.filter((slot) => slot.link != null)) {
                        if (restored.inputs.find((slot) => slot.name === original.name)?.link !== original.link
                            || !output[saved.id]?.inputs[original.name]) throw new Error(`Lost ${original.name} link in ${saved.type}`);
                    }
                    for (let i = 0; i < saved.widgets_values.length; i++) {
                        if (app.graph.serialize().nodes.find((node) => node.id === saved.id).widgets_values[i] !== saved.widgets_values[i]) {
                            throw new Error(`Changed widget ${i} in ${saved.type}`);
                        }
                    }
                }
            }, graph);
            console.log(`WORKFLOW PASS ${filename}`);
        }
        assert.deepEqual(errors, []);
        console.log(`PASS ${count} model profiles plus physical mouse connections; zero page errors and no generation requests`);
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
