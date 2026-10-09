import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const NODE_NAME = "Vidu_Q4_Preview_Video";
const INSTALL_MARKER = Symbol("seedanceViduQ4Installed");

function refresh(node) {
    const model = String(node.widgets?.find((widget) => widget.name === "model")?.value ?? "");
    const referenceMode = model.endsWith("-r2v");
    const highest = { image: 0, audio: 0 };
    for (const input of node.inputs ?? []) {
        const match = /^(image|audio)(\d+)$/.exec(input.name);
        if (match && input.link != null) {
            highest[match[1]] = Math.max(highest[match[1]], Number(match[2]));
        }
    }
    for (const input of node.inputs ?? []) {
        const match = /^(image|audio)(\d+)$/.exec(input.name);
        if (match) {
            const [family, index] = [match[1], Number(match[2])];
            const allowed = referenceMode
                ? index <= Math.min(highest[family] + 1, family === "image" ? 15 : 3)
                : family === "image" && index === 1;
            setInputVisible(node, input, allowed);
        }
    }
    for (const widget of node.widgets ?? []) {
        if (widget.name === "ratio" || /^audio_url[123]$/.test(widget.name)) {
            setWidgetVisible(widget, referenceMode);
        }
    }
    const visibleInputs = (node.inputs ?? []).filter(
        (input) => !input.hidden || input.link != null,
    );
    const slotStart = Number(node.constructor?.slot_start_y) || 0;
    visibleInputs.forEach((input, index) => {
        input.pos = [10, slotStart + (index + 0.7) * 20];
    });
    resizeSeedanceNode(node, 440, visibleInputs.length);
}

function schedule(node) {
    if (node.seedanceViduQ4Frame != null) {
        cancelAnimationFrame(node.seedanceViduQ4Frame);
    }
    node.seedanceViduQ4Frame = requestAnimationFrame(() => {
        node.seedanceViduQ4Frame = null;
        refresh(node);
    });
}

function install(node) {
    if (node[INSTALL_MARKER]) {
        return;
    }
    node[INSTALL_MARKER] = true;
    const model = node.widgets?.find((widget) => widget.name === "model");
    if (model) {
        const callback = model.callback;
        model.callback = (...args) => {
            const result = callback?.apply(model, args);
            schedule(node);
            return result;
        };
    }
    schedule(node);
}

app.registerExtension({
    name: "ComfyUI_Seedance.ViduQ4UI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (originalSeedanceNodeName(nodeData.name) !== NODE_NAME) {
            return;
        }
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = created?.apply(this, arguments);
            install(this);
            return result;
        };
        for (const name of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const original = nodeType.prototype[name];
            nodeType.prototype[name] = function () {
                const result = original?.apply(this, arguments);
                schedule(this);
                return result;
            };
        }
    },
    async nodeCreated(node) {
        const name = node.comfyClass ?? node.constructor?.comfyClass
            ?? node.constructor?.nodeData?.name ?? node.type ?? "";
        if (originalSeedanceNodeName(name) === NODE_NAME) {
            install(node);
        }
    },
});
