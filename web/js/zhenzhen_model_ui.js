import { app } from "../../../scripts/app.js";

const NB_NODE_NAME = "Zhenzhen_Image_NB";
const V31_NODE_NAME = "Zhenzhen_Video_V31";

const STANDARD_SIZES = [
    "1:1", "2:3", "3:2", "3:4", "4:3",
    "4:5", "5:4", "9:16", "16:9", "21:9",
];
const EXTREME_SIZES = [
    "1:1", "1:4", "1:8", "2:3", "3:2", "3:4", "4:1",
    "4:3", "4:5", "5:4", "8:1", "9:16", "16:9", "21:9",
];

const NB_MODEL_OPTIONS = {
    "zhenzhen-image-nb-flash": {
        resolutions: ["1k"],
        sizes: ["auto", ...STANDARD_SIZES],
        maxN: 1,
    },
    "zhenzhen-image-nb-2": {
        resolutions: ["0.5k", "1k", "2k", "4k"],
        sizes: EXTREME_SIZES,
        maxN: 1,
    },
    "zhenzhen-image-nb-2-lite": {
        resolutions: ["1k"],
        sizes: EXTREME_SIZES,
        maxN: 4,
    },
    "zhenzhen-image-nb-pro": {
        resolutions: ["1k", "2k", "4k"],
        sizes: STANDARD_SIZES,
        maxN: 1,
    },
};

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function updateCombo(widget, values, preferred = values[0]) {
    if (!widget) {
        return;
    }
    widget.options ??= {};
    widget.options.values = [...values];
    if (!values.includes(String(widget.value))) {
        widget.value = values.includes(preferred) ? preferred : values[0];
        widget.callback?.(widget.value);
    }
}

function updateInteger(widget, maximum) {
    if (!widget) {
        return;
    }
    widget.options ??= {};
    widget.options.min = 1;
    widget.options.max = maximum;
    const nextValue = Math.min(maximum, Math.max(1, Number(widget.value) || 1));
    if (widget.value !== nextValue) {
        widget.value = nextValue;
        widget.callback?.(nextValue);
    }
}

function refreshNBNode(node) {
    const model = String(widgetByName(node, "model")?.value ?? "");
    const options = NB_MODEL_OPTIONS[model] ?? NB_MODEL_OPTIONS["zhenzhen-image-nb-flash"];
    updateCombo(widgetByName(node, "resolution"), options.resolutions, "1k");
    updateCombo(widgetByName(node, "size"), options.sizes, "1:1");
    updateInteger(widgetByName(node, "n"), options.maxN);
    node.setDirtyCanvas?.(true, true);
}

function refreshV31Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? "");
    for (const input of node.inputs ?? []) {
        if (!/^image[1-3]$/.test(input.name)) {
            continue;
        }
        const allowed = (
            model !== "zhenzhen-video-v31-lite"
            && !(model === "zhenzhen-video-v31-quality" && input.name === "image3")
        );
        input.hidden = !allowed && input.link == null;
    }
    node.setDirtyCanvas?.(true, true);
}

function wrapRefresh(node, refresh) {
    const widget = widgetByName(node, "model");
    if (!widget || widget.seedanceZhenzhenCallback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refresh(node);
        return result;
    };
    widget.seedanceZhenzhenCallback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.ZhenzhenModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (![NB_NODE_NAME, V31_NODE_NAME].includes(nodeData.name)) {
            return;
        }
        const refresh = nodeData.name === NB_NODE_NAME ? refreshNBNode : refreshV31Node;

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapRefresh(this, refresh);
            refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refresh(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refresh(this);
            return result;
        };
    },
});
