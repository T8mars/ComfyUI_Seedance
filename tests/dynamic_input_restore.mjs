import assert from "node:assert/strict";
import { setSeedanceInputVisible } from "../web/js/dynamic_widget_ui.js";

for (const modern of [false, true]) {
    const slots = Array.from({ length: 19 }, (_, index) => ({
        name: index < 15 ? `image${index + 1}` : index < 18 ? `audio${index - 14}` : "api_config",
        link: index === 0 ? 42 : null,
    }));
    const node = {
        inputs: [...slots],
        pos: [0, 0],
        computeSize() {
            if (this.failCompute) throw new Error("test size");
            return [440, this.inputs.length * 20];
        },
        getConnectionPos(isInput, slot) {
            if (this.failPosition) throw new Error("test position");
            return [10, slot * 20];
        },
        onSerialize() {},
    };
    if (modern) {
        const backing = node.inputs;
        Object.defineProperty(node, "inputs", {
            get() { return backing; },
            set(value) { backing.splice(0, backing.length, ...value); },
        });
    }
    for (const input of node.inputs) {
        setSeedanceInputVisible(node, input, input.name === "image1" || input.name === "api_config");
    }
    assert.deepEqual(node.computeSize(), [440, 40]);
    assert.deepEqual(node.inputs, slots);
    assert.deepEqual(node.getConnectionPos(true, 18), [10, 20]);
    assert.deepEqual(node.inputs, slots);
    node.failCompute = true;
    assert.throws(() => node.computeSize(), /test size/);
    assert.deepEqual(node.inputs, slots);
    node.failCompute = false;
    node.failPosition = true;
    assert.throws(() => node.getConnectionPos(true, 18), /test position/);
    assert.deepEqual(node.inputs, slots);
    node.failPosition = false;
    setSeedanceInputVisible(node, node.inputs[15], true);
    assert.deepEqual(node.computeSize(), [440, 60]);
    assert.deepEqual(node.getConnectionPos(true, 15), [10, 20]);
    assert.deepEqual(node.inputs, slots);
    assert.equal(node.inputs[0].link, 42);
    const serialized = { inputs: node.inputs.map((input) => ({ ...input })) };
    node.onSerialize(serialized);
    assert.equal(serialized.inputs.length, 19);
    assert.ok(serialized.inputs.every((input) => !input.widget && !input.pos));
}
console.log("Legacy and in-place ComfyUI setters preserve all 19 sockets after hiding, switching, and exceptions.");

for (const shared of [false, true]) {
for (const position of [[-100000, -100000], new Float32Array([-100000, -100000])]) {
    const media = { name: "image3", link: null, hidden: true, pos: position, widget: { name: "__seedance_hidden_input__" } };
    const converted = { name: "prompt", link: 9, pos: [12, 34], widget: { name: "prompt" } };
    const node = { inputs: [media, converted] };
    node._concreteInputs = shared ? node.inputs : [{ ...media }, { ...converted }];
    setSeedanceInputVisible(node, media, false);
    setSeedanceInputVisible(node, media, true);
    setSeedanceInputVisible(node, converted, false);
    assert.equal(media.pos, undefined);
    assert.equal(media.widget, undefined);
    assert.equal(node._concreteInputs[0].widget, undefined);
    assert.equal(node._concreteInputs[0].alwaysVisible, true);
    assert.deepEqual(converted.pos, [12, 34]);
    assert.deepEqual(converted.widget, { name: "prompt" });
    assert.equal(converted.link, 9);
    const serialized = { inputs: node.inputs.map((input) => ({ ...input })) };
    node.onSerialize(serialized);
    assert.equal(serialized.inputs[0].pos, undefined);
    assert.equal(serialized.inputs[0].widget, undefined);
    assert.deepEqual(serialized.inputs[1].widget, { name: "prompt" });
}
}
console.log("Old hidden presentation is discarded; real converted widgets, links and custom positions are preserved.");
