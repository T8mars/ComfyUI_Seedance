// Real ComfyUI canvas checks. No generation or upload POSTs are made.
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
            if (route.request().method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(route.request().url())) return route.abort();
            return route.continue();
        });
        await page.goto(process.env.SEEDANCE_NOV19_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.__seedApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.__seedApp?.graph);
        await page.waitForTimeout(700);
        await page.keyboard.press("Escape");
        const directory = path.join(__dirname, "..", "examples");
        const candidates = fs.readdirSync(directory).filter((name) => /^(kling-v4-image-|mai-image-2-7-|qwen-audio-3\.1-tts-|zhenzhen-g6\.2-)/.test(name));
        assert.equal(candidates.length, 13);
        for (const filename of candidates) {
            const result = await page.evaluate(async (workflow) => {
                const app = window.__seedApp, settle = () => new Promise((r) => setTimeout(r, 110));
                await app.loadGraphData(workflow); await settle();
                const target = app.graph._nodes.find((n) => ["Kling_V4_Image", "MAI_Image_2_7", "Qwen_Audio_3_1_TTS", "Seedance_LLM_API"].includes(n.comfyClass));
                const linked = (node) => node.inputs.map((slot) => [slot.name, slot.link]);
                const before = linked(target);
                const widget = (name) => target.widgets.find((w) => w.name === name);
                const hidden = (name) => String(widget(name).type).includes("seedance-hidden");
                if (target.comfyClass === "Kling_V4_Image" && hidden("n") !== (widget("sequential_image_generation").value === "auto")) throw new Error("Kling count visibility wrong");
                if (target.comfyClass === "MAI_Image_2_7" && hidden("size") !== target.inputs.some((s) => s.name === "image1" && s.link != null)) throw new Error("MAI sizing visibility wrong");
                if (target.comfyClass === "Qwen_Audio_3_1_TTS") {
                    const model = widget("model").value;
                    if (hidden("voice") !== model.endsWith("-next")) throw new Error("Next voice widget visibility wrong");
                    if (!model.endsWith("-next")) {
                        const count = widget("voice").options.values.length;
                        if (count !== (model.endsWith("-plus") ? 5 : 70)) throw new Error("Wrong voice profile length: " + count);
                    }
                }
                for (const width of [900, 540]) { target.setSize([width, target.size[1]]); await settle(); }
                await app.loadGraphData(app.graph.serialize()); await settle();
                const restored = app.graph._nodes.find((n) => n.comfyClass === target.comfyClass);
                const prompt = await app.graphToPrompt();
                const validation = await (await fetch("/seedance_nov17_fixture/validate", { method: "POST",
                    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: prompt.output }) })).json();
                return { validation, before, after: linked(restored), inputs: prompt.output[String(restored.id)].inputs };
            }, JSON.parse(fs.readFileSync(path.join(directory, filename), "utf8")));
            assert.equal(result.validation.valid, true, filename + JSON.stringify(result.validation));
            assert.deepEqual(result.before, result.after, filename + " changed input names or links on reload");
            if (filename.includes("next-reference")) assert.ok(result.inputs.audio1);
            console.log("CANVAS PASS " + filename);
        }
        const count = await page.evaluate(async () => {
            const app = window.__seedApp, settle = () => new Promise((resolve) => setTimeout(resolve, 100));
            let connections = 0;
            for (const [type, family, cap] of [
                ["Kling_V4_Image", "image", 10], ["MAI_Image_2_7", "image", 5],
                ["SeedanceConcurrent_MAI_Image_2_7_Submit", "image", 5], ["Qwen_Audio_3_1_TTS", "audio", 3],
            ]) {
                app.graph.clear();
                const target = LiteGraph.createNode(type); app.graph.add(target); target.pos = [680, 60];
                const source = LiteGraph.createNode(family === "audio" ? "LoadAudio" : "LoadImage");
                app.graph.add(source); source.pos = [30, 60];
                const set = async (name, value) => {
                    const item = target.widgets.find((w) => w.name === name);
                    item.value = value; item.callback?.(value); await settle();
                };
                if (family === "audio") {
                    await set("model", "qwen-audio-3.1-tts-plus");
                    const voice = target.widgets.find((w) => w.name === "voice");
                    if (voice.options.values.length !== 5) throw new Error("Plus voice switch failed");
                    await set("output_format", "opus");
                    const rate = target.widgets.find((w) => w.name === "sample_rate");
                    if (rate.value !== "24000" || rate.options.values.includes("44100")) throw new Error("Opus rates not restricted");
                    await set("model", "qwen-audio-3.1-tts-next");
                    if (target.widgets.find((w) => w.name === "output_format").value === "opus") throw new Error("Next retained Opus");
                }
                await settle();
                for (let index = 1; index <= cap; index++) {
                    const at = target.inputs.findIndex((s) => s.name === family + index);
                    const slot = target.inputs[at], pos = target.getConnectionPos(true, at);
                    if (slot.hidden || pos[0] < target.pos[0] - 20 || pos[1] < target.pos[1]) throw new Error(type + ": missing " + slot.name);
                    source.connect(0, target, at); await settle();
                    if (slot.link == null) throw new Error(type + ": link not stored");
                    connections++;
                }
                target.setSize([560, target.size[1]]); await settle();
                const original = target.inputs.map((i) => [i.name, i.link]);
                const saved = app.graph.serialize();
                if (saved.nodes.some((n) => n.inputs?.some((i) => i.widget?.name === "__seedance_hidden_input__" || i.pos?.[0] === -100000))) throw new Error("Saved hidden marker");
                await app.loadGraphData(saved); await settle();
                const restored = app.graph._nodes.find((n) => n.comfyClass === type);
                if (JSON.stringify(restored.inputs.map((i) => [i.name, i.link])) !== JSON.stringify(original)) throw new Error(type + ": lost links");
            }
            return connections;
        });
        assert.equal(count, 23);
        assert.deepEqual(errors, []);
        console.log("CANVAS PASS 23 progressive connections, resize/reload, voice/format switching and no page errors.");
    } finally { await browser.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; });
