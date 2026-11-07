import { app } from "../../../scripts/app.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { resizeSeedanceNode, setSeedanceInputVisible, setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const NAMES = new Set(["Zhenzhen_Image_G26", "Krea_V3_Image"]);
const INSTALLED = Symbol("seedanceImage26");

function refresh(node, name) {
    const widget = (name) => node.widgets?.find((item) => item.name === name);
    const value = (name) => widget(name)?.value;
    const show = (names, visible) => names.forEach((name) => setSeedanceWidgetVisible(widget(name), visible));
    let maximum = 8;
    if (name === "Zhenzhen_Image_G26") {
        const lowprice = String(value("model")).endsWith("-lowprice");
        const gif = value("mode") === "gif";
        const size = widget("size");
        const sizes = ["auto", "1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16", "2:1", "1:2", "21:9", "9:21"];
        if (size?.options) size.options.values = lowprice ? sizes : [...sizes, "custom"];
        if (lowprice && size?.value === "custom" && !node.inputs?.some((input) => input.name === "size" && input.link != null)) size.value = "1:1";
        const custom = value("size") === "custom";
        show(["size"], !gif || lowprice);
        show(["width", "height"], !lowprice && !gif && custom);
        show(["resolution"], !lowprice && !gif && !custom);
        show(["quality"], !lowprice);
        show(["complexity", "n", "output_format", "mask_url", "markup_url"], !lowprice && !gif);
        show(["output_compression"], !lowprice && !gif && ["jpeg", "webp"].includes(value("output_format")));
        show(["frame_size", "frame_count", "frame_duration_ms"], !lowprice && gif);
        show(["frame_width", "frame_height"], !lowprice && gif && value("frame_size") === "custom");
        maximum = lowprice ? 10 : gif ? 0 : 16;
    } else {
        show(["width", "height"], value("size") === "custom");
        maximum = String(value("model")).endsWith("-i2i") ? 8 : 0;
    }
    let highest = 0;
    for (const input of node.inputs ?? []) {
        if (/^image\d+$/.test(input.name) && input.link != null) highest = Math.max(highest, Number(input.name.slice(5)));
    }
    for (const input of node.inputs ?? []) {
        if (/^image\d+$/.test(input.name)) {
            setSeedanceInputVisible(node, input, Number(input.name.slice(5)) <= Math.min(maximum, Math.max(1, highest + 1)));
        }
    }
    resizeSeedanceNode(node, 480, (node.inputs ?? []).filter((input) => !input.hidden || input.link != null).length);
}

function install(node, name) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    const schedule = () => {
        if (node.seedanceImage26Frame != null) cancelAnimationFrame(node.seedanceImage26Frame);
        node.seedanceImage26Frame = requestAnimationFrame(() => { node.seedanceImage26Frame = null; refresh(node, name); });
    };
    node.seedanceImage26Refresh = schedule;
    for (const field of ["model", "mode", "size", "frame_size", "output_format"]) {
        const widget = node.widgets?.find((item) => item.name === field);
        if (!widget) continue;
        const previous = widget.callback;
        widget.callback = function (...args) { const result = previous?.apply(this, args); schedule(); return result; };
    }
    schedule();
}

app.registerExtension({
    name: "ComfyUI_Seedance.Image26UI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        const name = originalSeedanceNodeName(nodeData.name);
        if (!NAMES.has(name)) return;
        const created = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () { const result = created?.apply(this, arguments); install(this, name); return result; };
        for (const hook of ["onConfigure", "onConnectionsChange", "onAfterGraphConfigured"]) {
            const previous = nodeType.prototype[hook];
            nodeType.prototype[hook] = function () { const result = previous?.apply(this, arguments); this.seedanceImage26Refresh?.(); return result; };
        }
    },
    async nodeCreated(node) {
        const name = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type ?? "");
        if (NAMES.has(name)) install(node, name);
    },
});
