// Actual ComfyUI canvas; prohibit queue submission and validate serialized graphs locally.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(process.env.SEEDANCE_BROWSER_MODULE_DIR, "playwright"));

async function main() {
    const browser = await chromium.launch({ headless: true, executablePath: process.env.SEEDANCE_BROWSER_EXECUTABLE });
    try {
        const page = await browser.newPage({ viewport: { width: 1600, height: 1000 } });
        await page.route("**/*", (route) =>
            route.request().method() === "POST" && /\/prompt(?:\?|$)|\/v1\/|\/upload\//.test(route.request().url())
                ? route.abort() : route.continue());
        await page.goto(process.env.SEEDANCE_MAGI2_UI_URL, { waitUntil: "networkidle", timeout: 90000 });
        await page.evaluate(async () => { window.magiApp = (await import("/scripts/app.js")).app; });
        await page.waitForFunction(() => window.magiApp?.graph);
        await page.keyboard.press("Escape");
        const examples = path.join(__dirname, "..", "examples");
        const files = fs.readdirSync(examples).filter((f) =>
            /^magi-2(?:-global)?-(?:t2v|i2v|r2v)\.json$/.test(f)
            || f === "moonshotai-kimi-k3.1-pro-text.json" || f === "zhenzhen-gk-4.7-vision.json");
        assert.equal(files.length, 8);
        for (const name of files) {
            const workflow = JSON.parse(fs.readFileSync(path.join(examples, name), "utf-8"));
            const check = await page.evaluate(async (workflow) => {
                const app = window.magiApp;
                const settle = () => new Promise((resolve) => setTimeout(resolve, 125));
                await app.loadGraphData(workflow);
                await settle();
                const node = app.graph._nodes.find((n) => ["Magi_2_Video", "Seedance_LLM_API"].includes(n.comfyClass));
                const signature = (target) => target.inputs.map((s) => [s.name, s.link]);
                const before = signature(node);
                if (node.comfyClass === "Magi_2_Video") {
                    const clone = LiteGraph.createNode("SeedanceConcurrent_Magi_2_Video_Submit");
                    const receiver = LiteGraph.createNode("SeedanceConcurrent_Video_Await");
                    const save = LiteGraph.createNode("SaveVideo");
                    for (const extra of [clone, receiver, save]) app.graph.add(extra);
                    clone.pos = [1500, 30]; receiver.pos = [2050, 30]; save.pos = [2500, 30];
                    for (const widget of clone.widgets) {
                        const original = node.widgets.find((w) => w.name === widget.name && w.type !== "button");
                        if (original) { widget.value = original.value; widget.callback?.(widget.value); }
                    }
                    for (const slot of node.inputs.filter((item) => item.link != null)) {
                        const link = app.graph.links.get(slot.link);
                        app.graph.getNodeById(link.origin_id).connect(link.origin_slot, clone, clone.inputs.findIndex((i) => i.name === slot.name));
                    }
                    clone.connect(0, receiver, receiver.inputs.findIndex((i) => i.name === "future_1"));
                    receiver.connect(0, save, 0);
                    for (const width of [850, 490]) {
                        for (const test of [node, clone]) test.setSize([width, test.size[1]]);
                        await settle();
                    }
                }
                const saved = app.graph.serialize();
                const leaked = saved.nodes.some((n) => n.inputs?.some((slot) =>
                    slot.widget?.name === "__seedance_hidden_input__" || slot.pos?.[0] === -100000));
                await app.loadGraphData(saved);
                await settle();
                const { output } = await app.graphToPrompt();
                const validation = await (await fetch("/seedance_nov17_fixture/validate", { method: "POST",
                    headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: output }) })).json();
                return { before, after: signature(app.graph.getNodeById(node.id)), leaked, validation };
            }, workflow);
            assert.equal(check.leaked, false, name);
            assert.deepEqual(check.before, check.after, name);
            assert.equal(check.validation.valid, true, name + " " + JSON.stringify(check.validation));
            console.log("CANVAS PASS " + name);
        }
        const count = await page.evaluate(async () => {
            const app = window.magiApp, settle = () => new Promise((r) => setTimeout(r, 90));
            let count = 0;
            for (const kind of ["Magi_2_Video", "SeedanceConcurrent_Magi_2_Video_Submit"]) {
                app.graph.clear();
                const target = LiteGraph.createNode(kind);
                app.graph.add(target); target.pos = [620, 40];
                const mode = target.widgets.find((w) => w.name === "generation_type");
                const set = async (value) => { mode.value = value; mode.callback?.(value); await settle(); };
                const slotIndex = (name) => target.inputs.findIndex((slot) => slot.name === name);
                const show = (name) => {
                    const i = slotIndex(name);
                    return !target.inputs[i].hidden && target.getConnectionPos(true, i)[0] > 0;
                };
                await set("text");
                if (show("image1") || show("video1") || show("audio1")) throw new Error(kind + " text exposes unused inputs");
                await set("frame");
                if (!show("image1") || show("image2") || show("video1")) throw new Error(kind + " frame layout");
                await set("reference");
                for (const [family, cap, loader] of [["image", 10, "LoadImage"], ["video", 5, "LoadVideo"], ["audio", 5, "LoadAudio"]]) {
                    const source = LiteGraph.createNode(loader);
                    app.graph.add(source);
                    for (let i = 1; i <= cap; i++) {
                        const name = family + i;
                        if (!show(name)) throw new Error(kind + " did not reveal " + name);
                        source.connect(0, target, slotIndex(name));
                        await settle();
                        if (target.inputs[slotIndex(name)].link == null) throw new Error(kind + " could not connect " + name);
                        count++;
                    }
                }
                await set("text");
                if (!show("image10") || !show("video5") || !show("audio5")) throw new Error(kind + " hid an invalid linked socket");
                await set("reference");
                const id = target.id, graph = app.graph.serialize();
                await app.loadGraphData(graph);
                await settle();
                if (app.graph.getNodeById(id).inputs.filter((slot) => slot.link != null).length !== 20) {
                    throw new Error(kind + " lost references on reload");
                }
            }
            return count;
        });
        assert.equal(count, 40);
        console.log("CANVAS PASS " + count + " progressive media connections across serial and concurrent nodes");
    } finally {
        await browser.close();
    }
}

main().catch((err) => { console.error(err); process.exitCode = 1; });
