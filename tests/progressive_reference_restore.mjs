import assert from "node:assert/strict";
import fs from "node:fs";
import vm from "node:vm";
import contract from "./reference_input_cases.cjs";
import { originalSeedanceNodeName } from "../web/js/concurrent_node_ui.js";
import * as helpers from "../web/js/dynamic_widget_ui.js";

const schemas = process.argv.includes("--backend-schema") ? JSON.parse(fs.readFileSync(0, "utf8")) : null;
let profiles = 0;
for (const [file, key, capacity, fallbackModels] of contract.cases) {
    const aliases = schemas ? [key, `SeedanceConcurrent_${key}_Submit`].filter((name) => schemas[name])
        : [key, ...(/^(Hitem3D|Meshy|Tripo)/.test(key) || key === "Kling_V4_Custom_Element" ? [] : [`SeedanceConcurrent_${key}_Submit`])];
    for (const name of aliases) {
        let extension, id = 0;
        const frames = new Map();
        const context = vm.createContext({
            ...helpers, originalSeedanceNodeName, resizeSeedanceNode() {},
            setWidgetVisible: helpers.setSeedanceWidgetVisible, setInputVisible: helpers.setSeedanceInputVisible,
            app: { registerExtension(value) { extension = value; } },
            requestAnimationFrame(callback) { frames.set(++id, callback); return id; },
            cancelAnimationFrame(frame) { frames.delete(frame); },
        });
        vm.runInContext(fs.readFileSync(new URL(`../web/js/${file}`, import.meta.url), "utf8").replace(/^import[\s\S]*?;\r?\n/gm, ""), context);
        const schema = schemas?.[name];
        const fields = { ...schema?.required, ...schema?.optional };
        const models = Array.isArray(fields.model?.[0]) ? fields.model[0] : fallbackModels.length ? fallbackModels : [""];
        const inputNames = Object.entries(capacity).flatMap(([family, max]) => Array.from({ length: max }, (_, i) => `${family}${i + 1}`));
        if (schema) {
            const actual = Object.keys(fields).filter((field) => /^(image|video|audio)[1-9]\d*$/.test(field));
            assert.deepEqual(actual.sort(), [...inputNames].sort(), `${name}: UI capacity must match backend schema`);
        }
        const flush = () => {
            for (let round = 0; frames.size && round < 10; round++) {
                for (const [frame, callback] of [...frames]) { frames.delete(frame); callback(); }
            }
            assert.equal(frames.size, 0);
        };
        class Node {
            constructor() {
                const defaults = { model: models[0], mode: "image", input_mode: "images", reference_type: "image_refer", video_urls: "", resolution: "1k", output_format: "png" };
                const names = new Set([...Object.keys(fields), ...Object.keys(defaults), "size", "seed", "control_after_generate"]);
                this.widgets = [...names].filter((field) => !inputNames.includes(field) && field !== "api_config").map((field) => ({
                    name: field, type: "combo", value: defaults[field] ?? fields[field]?.[1]?.default ?? "api_default", options: {}, callback() {},
                }));
                this.inputs = [...inputNames.map((field) => ({ name: field, type: "IMAGE", link: null,
                    pos: [-100000, -100000], widget: { name: "__seedance_hidden_input__" }, hidden: true })),
                { name: "api_config", link: 500 }, { name: "prompt", link: 501, widget: { name: "prompt" }, pos: [12, 34] }];
                this._concreteInputs = this.inputs.map((input) => ({ ...input }));
                this.comfyClass = name;
            }
            getConnectionPos(isInput, slot) { return this.inputs[slot].pos ?? [10, slot * 20]; }
            computeSize() { return [500, this.inputs.length * 20]; }
            addWidget(type, name, value, callback) { const w = { type, name, value, callback }; this.widgets.push(w); return w; }
        }
        await extension.beforeRegisterNodeDef(Node, { name, python_module: "custom_nodes.ComfyUI_Seedance" });
        for (const model of models) {
            const node = new Node();
            const widget = (field) => node.widgets.find((w) => w.name === field);
            widget("model").value = model;
            node.onNodeCreated(); flush();
            const originalNames = node.inputs.map((input) => input.name);
            const modes = key === "Zhenzhen_Image_G26" ? ["image", "gif", "image"] : ["image"];
            for (const mode of modes) {
                widget("mode").value = mode; widget("mode").callback?.(); node.onConfigure?.(); flush();
                const limits = contract.limitsFor(key, model, capacity, mode);
                const flash = key === "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice" || model === "zhenzhen-video-kling-v4-flash";
                const check = (family, count) => {
                    const inputs = node.inputs.filter((input) => new RegExp(`^${family}\\d+$`).test(input.name));
                    assert.equal(inputs.filter((input) => !input.hidden).length, count, `${name}/${model}/${mode}/${family}`);
                    for (const input of inputs.filter((input) => !input.hidden)) {
                        assert.notEqual(input.pos?.[0], -100000, `${name}/${input.name}: restored raw position`);
                        assert.notEqual(input.widget?.name, "__seedance_hidden_input__", `${name}/${input.name}: restored raw widget`);
                        assert.notEqual(node.getConnectionPos(true, node.inputs.indexOf(input))[0], -100000);
                        const concrete = node._concreteInputs.find((item) => item.name === input.name);
                        assert.notEqual(concrete.widget?.name, "__seedance_hidden_input__", `${name}/${input.name}: restored concrete widget`);
                    }
                };
                for (const [family, maximum] of Object.entries(limits)) {
                    if (flash && family === "video") continue;
                    const initial = key === "Tripo_Generate" ? 4
                        : family === "image" && (key.startsWith("Hitem3D") || key === "Kling_V4_Custom_Element") ? 2
                        : family === "image" && (key === "Wan_3_0_Video" || key === "Seedance_2_5_Video") && model.endsWith("-i2v") ? 2 : 1;
                    check(family, Math.min(maximum, initial));
                    for (let index = 1; index <= maximum; index++) {
                        const input = node.inputs.find((item) => item.name === `${family}${index}`);
                        assert.equal(input.hidden, false, `${name}/${input.name}: next slot is available`);
                        input.link = ++id; node.onConnectionsChange?.(); flush();
                        check(family, Math.min(maximum, Math.max(initial, index + 1)));
                    }
                    node.onConfigure?.(); node.onAfterGraphConfigured?.(); flush(); check(family, maximum);
                    for (const input of node.inputs.filter((item) => new RegExp(`^${family}\\d+$`).test(item.name))) input.link = null;
                    node.onConnectionsChange?.(); flush(); check(family, Math.min(maximum, initial));
                }
                const serialized = { inputs: node.inputs.map((input) => ({ ...input })) };
                node.onSerialize(serialized);
                assert.ok(serialized.inputs.every((input) => input.widget?.name !== "__seedance_hidden_input__" && input.pos?.[0] !== -100000));
                assert.deepEqual(node.inputs.map((input) => input.name), originalNames);
                assert.equal(node.inputs.at(-1).link, 501);
                assert.deepEqual(node.inputs.at(-1).widget, { name: "prompt" });
                assert.ok(node.inputs.at(-1).pos.every(Number.isFinite));
                profiles++;
            }
        }
    }
}
console.log(`Progressive restore: ${contract.cases.length} families, ${profiles} model/mode/serial/concurrent profiles; all slots reached, legacy markers removed, converted links preserved.`);
