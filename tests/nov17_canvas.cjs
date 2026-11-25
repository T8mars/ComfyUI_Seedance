// Isolated real-canvas validation only; generation and upload requests are blocked.
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
        await page.route("**/*", (route) => {
            const request = route.request();
            if (request.method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(request.url())) return route.abort("blockedbyclient");
            return route.continue();
        });
        await page.goto(process.env.SEEDANCE_NOV17_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__nov17app = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__nov17app?.graph);
        await page.waitForTimeout(1000); await page.keyboard.press("Escape");
        const directory = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(directory).filter((name) => /^seedance-2\.5-.*flash-/.test(name)
            || /^minimax-h3-comfyui-(charswap|wuxi|max-10020|max-10021)-/.test(name) && !name.includes("-token")
            || /^(zhenzhen-fb-5\.2|doubao-seed-tts-2\.0)-/.test(name));
        assert.equal(files.length, 21);
        const legacy = fs.readdirSync(directory).filter((name) => /^seedance-2\.5-(global-)?standard-/.test(name)
            && JSON.parse(fs.readFileSync(path.join(directory, name), "utf8")).nodes.some((node) => node.type === "Seedance_2_5_Video"));
        assert.equal(legacy.length, 8);
        for (const filename of process.argv.includes("--references-only") ? [] : [...files, ...legacy]) {
            const report = await page.evaluate(async (workflow) => {
                const app = window.__nov17app, settle = () => new Promise((resolve) => setTimeout(resolve, 100));
                await app.loadGraphData(workflow); await settle();
                for (const source of app.graph._nodes) {
                    const fixture = { LoadImage: "example.png", LoadVideo: "example.mp4", LoadAudio: "example.wav" }[source.comfyClass];
                    if (fixture) source.widgets[0].value = fixture;
                }
                const target = app.graph._nodes.find((node) => !/^(Load|Save|Preview|Seedance_Config)/.test(node.comfyClass));
                if (!target) throw new Error("Generation node not found");
                const before = target.inputs.map((input) => ({ name: input.name, link: input.link }));
                const widget = (name) => target.widgets.find((item) => item.name === name);
                const change = async (name, value) => { const item = widget(name); item.value = value; item.callback?.(value); await settle(); };
                if (target.comfyClass === "Seedance_2_5_Video" && widget("model").value.includes("flash-")) {
                    const original = widget("model").value;
                    await change("model", original.replace("flash-", "standard-"));
                    await change("resolution", "4k"); await change("draft", true);
                    await change("model", original);
                    if (widget("resolution").value !== "480p" || widget("draft").value !== false) throw new Error("Flash stale Standard controls were not normalized");
                    if (JSON.stringify(widget("resolution").options.values) !== JSON.stringify(["480p", "720p"])) throw new Error("Flash resolution options are wrong");
                    if (!String(widget("draft").type).includes("seedance-hidden")) throw new Error("Flash draft control remains visible");
                    if (original.endsWith("i2v") && JSON.stringify(widget("ratio").options.values) !== JSON.stringify(["adaptive"])) throw new Error("Flash I2V ratio must be adaptive");
                    if (original.endsWith("multi") && !target.inputs.find((input) => input.name === "image11").hidden) throw new Error("Flash exposes images beyond its cap");
                }
                if (target.comfyClass === "Minimax_H3_ComfyUI_CharSwap") {
                    const original = widget("duration_mode").value;
                    await change("duration_mode", original === "frames" ? "seconds" : "frames");
                    await change("duration_mode", original);
                    await change("resolution", "768p");
                    if (!widget("ratio").options.values.includes("21:9")) throw new Error("Missing 768p ratios");
                    await change("resolution", "480p");
                    if (widget("ratio").options.values.includes("21:9")) throw new Error("Unsupported 480p ratios");
                }
                const wrapperName = `SeedanceConcurrent_${target.comfyClass}_Submit`;
                if (target.comfyClass.startsWith("Minimax_H3_ComfyUI_") || target.comfyClass === "Seedance_2_5_Video") {
                    const submit = LiteGraph.createNode(wrapperName); app.graph.add(submit); submit.pos = [1600, 40];
                    for (const targetWidget of target.widgets) {
                        const item = submit.widgets.find((widget) => widget.name === targetWidget.name);
                        if (item && targetWidget.type !== "button") { item.value = targetWidget.value; item.callback?.(item.value); }
                    }
                    for (const input of target.inputs.filter((input) => input.link != null)) {
                        const link = app.graph.links.get(input.link), source = app.graph.getNodeById(link.origin_id);
                        const slot = submit.inputs.findIndex((item) => item.name === input.name);
                        source.connect(link.origin_slot, submit, slot);
                    }
                    const awaitNode = LiteGraph.createNode("SeedanceConcurrent_Video_Await"); app.graph.add(awaitNode); awaitNode.pos = [2200, 40];
                    submit.connect(0, awaitNode, awaitNode.inputs.findIndex((input) => input.name === "future_1"));
                    const save = LiteGraph.createNode("SaveVideo"); app.graph.add(save); save.pos = [2700, 40]; awaitNode.connect(0, save, 0);
                }
                for (const width of [900, 530]) { target.setSize([width, target.size[1]]); await settle(); }
                const id = target.id;
                await app.loadGraphData(app.graph.serialize()); await settle();
                const restored = app.graph.getNodeById(id);
                const prompt = await app.graphToPrompt();
                const validation = await (await fetch("/seedance_nov17_fixture/validate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output }) })).json();
                return { before, after: restored.inputs.map((input) => ({ name: input.name, link: input.link })), validation };
            }, JSON.parse(fs.readFileSync(path.join(directory, filename), "utf8")));
            assert.deepEqual(report.before, report.after, filename + ": input names/order/links changed");
            assert.equal(report.validation.valid, true, filename + JSON.stringify(report.validation));
            console.log("CANVAS PASS " + filename + ": controls, serial/concurrent, resize, reload and backend validation");
        }
        const referenceReport = await page.evaluate(async () => {
            const app = window.__nov17app, settle = () => new Promise((resolve) => setTimeout(resolve, 35));
            const cases = [
                ["Minimax_H3_ComfyUI_CharSwap", null, { image: 9, video: 1 }],
                ["Minimax_H3_ComfyUI_Wuxi", null, { image: 9, video: 3, audio: 3 }],
                ["Minimax_H3_ComfyUI_Max_10020", null, { image: 6, audio: 3 }],
                ["Minimax_H3_ComfyUI_Max_10021", null, { image: 9, audio: 3 }],
                ["Seedance_2_5_Video", "seedance-2.5-flash-i2v", { image: 2 }],
                ["Seedance_2_5_Video", "seedance-2.5-global-flash-i2v", { image: 2 }],
                ["Seedance_2_5_Video", "seedance-2.5-flash-multi", { image: 10, video: 5, audio: 5 }],
                ["Seedance_2_5_Video", "seedance-2.5-global-flash-multi", { image: 10, video: 5, audio: 5 }],
            ];
            let ports = 0;
            for (const [key, model, caps] of cases) for (const concurrent of [false, true]) {
                app.graph.clear();
                const target = LiteGraph.createNode(concurrent ? `SeedanceConcurrent_${key}_Submit` : key);
                app.graph.add(target); target.pos = [700, 60];
                if (model) { const widget = target.widgets.find((item) => item.name === "model"); widget.value = model; widget.callback?.(model); }
                await settle();
                for (const [family, cap] of Object.entries(caps)) {
                    const source = LiteGraph.createNode({ image: "LoadImage", video: "LoadVideo", audio: "LoadAudio" }[family]);
                    app.graph.add(source); source.pos = [0, 50];
                    for (let index = 1; index <= cap; index++) {
                        const slot = target.inputs.findIndex((input) => input.name === family + index), input = target.inputs[slot];
                        const position = target.getConnectionPos(true, slot);
                        if (input.hidden || position[0] < target.pos[0] - 30 || position[1] < target.pos[1] || position[1] > target.pos[1] + target.size[1]) throw new Error(`${key}/${model}: ${family + index} is not connectable on canvas`);
                        source.connect(0, target, slot); await settle(); ports++;
                        if (input.link == null) throw new Error("Reference connection was not retained");
                    }
                    const beyond = target.inputs.find((input) => input.name === family + (cap + 1));
                    if (beyond && !beyond.hidden) throw new Error("Port exceeds model capacity");
                }
                const before = target.inputs.map((input) => ({ name: input.name, link: input.link }));
                const id = target.id;
                target.setSize([530, target.size[1]]); await settle();
                const serialized = app.graph.serialize();
                const saved = serialized.nodes.find((node) => String(node.id) === String(id));
                if (!saved) throw new Error(`Serialized target missing ${key}/${id}: ${JSON.stringify(serialized.nodes.map((node) => [node.id, node.type]))}`);
                if (saved.inputs.some((input) => input.widget?.name === "__seedance_hidden_input__" || input.pos?.[0] === -100000)) throw new Error("Temporary hiding state serialized");
                await app.loadGraphData(serialized); await settle();
                const restored = app.graph.getNodeById(id);
                if (JSON.stringify(before) !== JSON.stringify(restored.inputs.map((input) => ({ name: input.name, link: input.link })))) throw new Error("Reference links changed after reload");
                for (const [family, cap] of Object.entries(caps)) for (let index = 1; index <= cap; index++) {
                    if (restored.inputs.find((input) => input.name === family + index).hidden) throw new Error("Linked reference hidden after reload");
                }
            }
            return { profiles: cases.length * 2, ports };
        });
        console.log("PASS progressive reference canvas " + JSON.stringify(referenceReport));
        const voiceWorkflow = JSON.parse(fs.readFileSync(path.join(directory, "doubao-seed-tts-2.0-vivi.json"), "utf8"));
        await page.evaluate(async (workflow) => {
            const app = window.__nov17app; await app.loadGraphData(workflow); await new Promise((resolve) => setTimeout(resolve, 100));
            const node = app.graph._nodes.find((node) => node.comfyClass === "Doubao_Seed_TTS_2_0");
            await node.widgets.find((widget) => widget.name === "Voice Library").callback();
        }, voiceWorkflow);
        const dialog = page.getByRole("dialog", { name: "Doubao voice library" });
        await dialog.waitFor();
        const voices = dialog.getByRole("listbox", { name: "Voices" });
        assert.equal(await voices.getByRole("option").count(), 473);
        await dialog.getByRole("searchbox", { name: "Search voices" }).fill("zh_male_lubanqihao_uranus_bigtts");
        assert.equal(await voices.getByRole("option").count(), 1);
        await voices.getByRole("option").click();
        assert.equal(await page.evaluate(() => window.__nov17app.graph._nodes.find((node) => node.comfyClass === "Doubao_Seed_TTS_2_0").widgets.find((widget) => widget.name === "speaker").value), "zh_male_lubanqihao_uranus_bigtts");
        await page.evaluate(async () => { await window.__nov17app.graph._nodes.find((node) => node.comfyClass === "Doubao_Seed_TTS_2_0").widgets.find((widget) => widget.name === "Voice Library").callback(); });
        await dialog.getByRole("combobox", { name: "All genders" }).selectOption("female");
        await dialog.getByRole("combobox", { name: "All languages" }).selectOption("zh");
        await dialog.getByRole("combobox", { name: "All uses" }).selectOption("general");
        assert.ok(await voices.getByRole("option").count() > 1);
        for (const viewport of [{ width: 1440, height: 1000 }, { width: 390, height: 844 }]) {
            await page.setViewportSize(viewport);
            const bounds = await dialog.boundingBox();
            assert.ok(bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= viewport.width + 1 && bounds.y + bounds.height <= viewport.height + 1);
            if (process.env.SEEDANCE_NOV17_SCREENSHOTS) {
                fs.mkdirSync(process.env.SEEDANCE_NOV17_SCREENSHOTS, { recursive: true });
                await page.screenshot({ path: path.join(process.env.SEEDANCE_NOV17_SCREENSHOTS, `voices-${viewport.width}.png`) });
            }
        }
        await dialog.getByRole("button", { name: "Close", exact: true }).click();
        await page.setViewportSize({ width: 1700, height: 1100 });
        const preserved = await page.evaluate(async () => {
            const app = window.__nov17app;
            const node = app.graph._nodes.find((node) => node.comfyClass === "Doubao_Seed_TTS_2_0");
            const values = node.serialize().widgets_values;
            if (values.includes("Voice Library")) throw new Error("UI-only button serialized");
            await app.loadGraphData(app.graph.serialize()); await new Promise((resolve) => setTimeout(resolve, 100));
            const restored = app.graph._nodes.find((node) => node.comfyClass === "Doubao_Seed_TTS_2_0");
            return restored.widgets.find((widget) => widget.name === "speaker").value;
        });
        assert.equal(preserved, "zh_male_lubanqihao_uranus_bigtts");
        assert.deepEqual(errors, []);
        console.log("PASS full 473-voice library, search, filters, selected raw ID, desktop/mobile bounds, reload and zero page errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
