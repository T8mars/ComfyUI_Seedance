// Actual ComfyUI canvas validation; no upstream task creation or uploads.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

(async () => {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE,
        args: ["--enable-unsafe-swiftshader"] });
    try {
        const page = await browser.newPage({ viewport: { width: 1700, height: 1100 } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.route("**/*", (route) => {
            if (route.request().method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(route.request().url())) return route.abort();
            return route.continue();
        });
        await page.goto(process.env.SEEDANCE_NOV21_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__nov21 = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__nov21?.graph);
        await page.waitForTimeout(700);
        await page.keyboard.press("Escape");
        const directory = path.join(__dirname, "..", "examples");
        const candidates = fs.readdirSync(directory).filter((n) => /^(kling-v4-long-image-|heygen-avatar-6-|miora-3d-|zhenzhen-gm-2\.5-|zhenzhen-gm-4-(hydrogen|carbon|neon)-|zhenzhen-hy-4-)/.test(n)
            || n.startsWith("minimax-h3-comfyui-") && n.includes("-token"));
        assert.equal(candidates.length, 21);
        for (const name of candidates) {
            const result = await page.evaluate(async (workflow) => {
                const app = window.__nov21, settle = () => new Promise((r) => setTimeout(r, 110));
                await app.loadGraphData(workflow); await settle();
                const target = app.graph._nodes.find((node) => /^(Kling_V4_Long_Image|HeyGen_Avatar_6|Miora_3D|Gemini_2_5_TTS|Seedance_LLM_API|Minimax_H3_ComfyUI_.*_Token)$/.test(node.comfyClass));
                const linked = (node) => node.inputs.map((slot) => [slot.name, slot.link]);
                const before = linked(target);
                const widget = (name) => target.widgets.find((item) => item.name === name);
                const hidden = (name) => String(widget(name).type).includes("seedance-hidden");
                if (target.comfyClass === "Kling_V4_Long_Image" && hidden("length") !== (widget("skill").value === "webpage")) throw new Error("Wrong mode controls");
                if (target.comfyClass === "HeyGen_Avatar_6" && hidden("voice") !== target.inputs.some((s) => s.name === "audio" && s.link != null)) throw new Error("Wrong HeyGen voice visibility");
                if (target.comfyClass === "Minimax_H3_ComfyUI_CharSwap_Token" && hidden("seconds") !== (widget("duration_mode").value === "frames")) throw new Error("Wrong duration mode controls");
                const kind = target.comfyClass === "Kling_V4_Long_Image" ? "Image"
                    : /^(HeyGen_Avatar_6|Minimax_H3_ComfyUI_.*_Token)$/.test(target.comfyClass) ? "Video" : null;
                if (kind) {
                    const submit = LiteGraph.createNode(`SeedanceConcurrent_${target.comfyClass}_Submit`);
                    app.graph.add(submit); submit.pos = [1580, 60];
                    for (const original of target.widgets) {
                        const copy = submit.widgets.find((item) => item.name === original.name);
                        if (copy && original.type !== "button") { copy.value = original.value; copy.callback?.(copy.value); }
                    }
                    for (const input of target.inputs.filter((item) => item.link != null)) {
                        const link = app.graph.links.get(input.link), source = app.graph.getNodeById(link.origin_id);
                        source.connect(link.origin_slot, submit, submit.inputs.findIndex((item) => item.name === input.name));
                    }
                    const awaited = LiteGraph.createNode(`SeedanceConcurrent_${kind}_Await`);
                    app.graph.add(awaited); awaited.pos = [2180, 60];
                    submit.connect(0, awaited, awaited.inputs.findIndex((item) => item.name === "future_1"));
                    const save = LiteGraph.createNode(`Save${kind}`);
                    app.graph.add(save); save.pos = [2700, 60]; awaited.connect(0, save, 0);
                }
                for (const width of [880, 540]) { target.setSize([width, target.size[1]]); await settle(); }
                const saved = app.graph.serialize();
                if (saved.nodes.some((n) => n.inputs?.some((i) => i.widget?.name === "__seedance_hidden_input__" || i.pos?.[0] === -100000))) throw new Error("Serialized hidden runtime state");
                await app.loadGraphData(saved); await settle();
                const restored = app.graph.getNodeById(target.id);
                const prompt = await app.graphToPrompt();
                const validation = await (await fetch("/seedance_nov17_fixture/validate", { method: "POST",
                    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output }) })).json();
                return { before, after: linked(restored), validation };
            }, JSON.parse(fs.readFileSync(path.join(directory, name), "utf8")));
            assert.equal(result.validation.valid, true, name + JSON.stringify(result.validation));
            assert.deepEqual(result.before, result.after, name + " lost links");
            console.log("CANVAS PASS " + name);
        }
        const connections = await page.evaluate(async () => {
            const app = window.__nov21, settle = () => new Promise((r) => setTimeout(r, 80));
            let count = 0;
            for (const [type, cap] of [["Kling_V4_Long_Image", 3], ["SeedanceConcurrent_Kling_V4_Long_Image_Submit", 3],
                ["Miora_3D", 8], ["Minimax_H3_ComfyUI_Max_10020_Token", 6],
                ["SeedanceConcurrent_Minimax_H3_ComfyUI_Max_10021_Token_Submit", 6],
                ["SeedanceConcurrent_Minimax_H3_ComfyUI_CharSwap_Token_Submit", 5]]) {
                app.graph.clear();
                const target = LiteGraph.createNode(type), source = LiteGraph.createNode("LoadImage");
                app.graph.add(target); app.graph.add(source); target.pos = [640, 50]; source.pos = [20, 50];
                await settle();
                for (let i = 1; i <= cap; i++) {
                    const index = target.inputs.findIndex((s) => s.name === "image" + i), slot = target.inputs[index];
                    const position = target.getConnectionPos(true, index);
                    if (slot.hidden || position[0] < target.pos[0] - 30 || position[1] < target.pos[1]) throw new Error(type + " cannot reach " + slot.name);
                    source.connect(0, target, index); await settle(); count++;
                    if (slot.link == null) throw new Error(type + " connection did not stick");
                }
                const links = target.inputs.map((i) => [i.name, i.link]);
                if (type.includes("Kling")) {
                    const mode = target.widgets.find((item) => item.name === "skill");
                    mode.value = "webpage"; mode.callback?.("webpage"); await settle();
                    const stillVisible = target.inputs.filter((i) => /^image\d+$/.test(i.name)).every((i) => !i.hidden);
                    const style = target.inputs.find((i) => i.name === "style_image");
                    if (!stillVisible || style.hidden) throw new Error("Mode change hid already connected inputs");
                    mode.value = "ecommerce"; mode.callback?.("ecommerce"); await settle();
                }
                target.setSize([500, target.size[1]]); await settle();
                await app.loadGraphData(app.graph.serialize()); await settle();
                const restored = app.graph._nodes.find((node) => node.comfyClass === type);
                if (JSON.stringify(restored.inputs.map((i) => [i.name, i.link])) !== JSON.stringify(links)) throw new Error(type + " lost references after reload");
                if (type === "Miora_3D" && restored.inputs.find((i) => i.name === "image3").label !== "image3 (right)") throw new Error("Miora view label order");
            }
            return count;
        });
        assert.equal(connections, 31);
        const sample = process.env.SEEDANCE_NOV21_GLB_SAMPLE;
        if (sample) {
            const id = await page.evaluate(async () => {
                const app = window.__nov21;
                app.graph.clear();
                const preview = LiteGraph.createNode("Preview3D");
                app.graph.add(preview); preview.pos = [420, 110]; preview.setSize([650, 650]);
                app.canvas.ds.scale = .84; app.canvas.ds.offset = [60, 50]; app.canvas.setDirty(true, true);
                await new Promise((r) => setTimeout(r, 300));
                return String(preview.id);
            });
            // Only the local, built-in viewer is queued here; example generation stays blocked.
            const sent = await page.request.post(new URL("/prompt", page.url()).href, { data: {
                prompt: { [id]: { class_type: "Preview3D", inputs: { model_file: sample } } },
            } });
            assert.ok(sent.ok(), await sent.text());
            const { prompt_id: queueId } = await sent.json();
            let record;
            for (let i = 0; i < 50; i++) {
                record = (await (await page.request.get(new URL(`/history/${queueId}`, page.url()).href)).json())[queueId];
                if (record?.status?.completed) break;
                await page.waitForTimeout(250);
            }
            assert.equal(record?.status?.status_str, "success", JSON.stringify(record?.status));
            await Promise.all([page.waitForResponse((response) => response.url().includes(sample) && response.ok(), { timeout: 30000 }),
                page.evaluate(({ id, output }) => window.__nov21.graph.getNodeById(id).onExecuted(output), { id, output: record.outputs[id] })]);
            await page.waitForTimeout(2500);
            const viewport = await page.evaluate(() => Array.from(document.querySelectorAll("canvas")).map((canvas) => {
                const r = canvas.getBoundingClientRect(); return { x: r.x, y: r.y, width: r.width, height: r.height };
            }).find((r) => r.width > 300 && r.width < 800 && r.x > 280 && r.height > 300));
            assert.ok(viewport, "Native Miora viewer wasn't visible");
            const before = await page.screenshot({ clip: viewport });
            await page.mouse.move(viewport.x + viewport.width * .48, viewport.y + viewport.height * .48);
            await page.mouse.down();
            await page.mouse.move(viewport.x + viewport.width * .68, viewport.y + viewport.height * .55, { steps: 14 });
            await page.mouse.up(); await page.waitForTimeout(450);
            const after = await page.screenshot({ clip: viewport });
            assert.notDeepEqual(before, after, "Native preview didn't respond to orbit drag");
            if (process.env.SEEDANCE_NOV21_SCREENSHOT) fs.writeFileSync(process.env.SEEDANCE_NOV21_SCREENSHOT, after);
            console.log("NATIVE PASS actual Miora GLB loaded and orbit drag changed visible preview pixels");
        }
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS 31 progressive inputs, mode controls, native prompt validation and zero JS errors");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
