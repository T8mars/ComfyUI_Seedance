import { app } from "../../../scripts/app.js";

const G2_NODE_NAME = "Zhenzhen_Image_G2";
const NB_NODE_NAME = "Zhenzhen_Image_NB";
const V31_NODE_NAME = "Zhenzhen_Video_V31";
const LOWPRICE_MODEL = "zhenzhen-image-g-v2-lowprice";
const CONVERTED_WIDGET_PREFIX = "converted-widget";

const STANDARD_SIZES = [
    "1:1", "2:3", "3:2", "3:4", "4:3",
    "4:5", "5:4", "9:16", "16:9", "21:9",
];
const LOWPRICE_SIZES = [...STANDARD_SIZES, "custom"];
const G2_CUSTOM_SIZE_WIDGET_INDEX = 5;
const G2_WIDGET_VALUE_COUNT = 7;
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

function setWidgetVisible(widget, visible) {
    if (!widget) {
        return;
    }
    const isConvertedInput = (
        String(widget.type ?? "").startsWith(CONVERTED_WIDGET_PREFIX)
        || Object.prototype.hasOwnProperty.call(widget, "origType")
    );
    if (isConvertedInput) {
        return;
    }
    if (!widget.seedanceZhenzhenOriginal) {
        widget.seedanceZhenzhenOriginal = {
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
    if (visible) {
        widget.type = widget.seedanceZhenzhenOriginal.type;
        widget.computeSize = widget.seedanceZhenzhenOriginal.computeSize;
    } else {
        widget.type = "hidden";
        widget.computeSize = () => [0, -4];
    }
}

function resizeNode(node, minimumWidth = 320) {
    requestAnimationFrame(() => {
        const computed = node.computeSize?.();
        if (computed) {
            node.setSize?.([
                Math.max(node.size?.[0] ?? minimumWidth, computed[0], minimumWidth),
                Math.max(computed[1], 120),
            ]);
        }
        node.setDirtyCanvas?.(true, true);
    });
}

function normalizeLowpriceSizeWidgets(node) {
    const sizeWidget = widgetByName(node, "size");
    const customWidget = widgetByName(node, "custom_size");
    if (!sizeWidget) {
        return;
    }
    const rawValue = String(sizeWidget.value ?? "").trim();
    if (LOWPRICE_SIZES.includes(rawValue)) {
        sizeWidget.value = rawValue;
    } else if (/^\d+\s*[:xX]\s*\d+$/.test(rawValue)) {
        sizeWidget.value = "custom";
        if (customWidget) {
            customWidget.value = rawValue;
        }
    } else {
        sizeWidget.value = "1:1";
    }
    updateCombo(sizeWidget, LOWPRICE_SIZES, "1:1");
}

function migrateLegacyG2WidgetValues(config) {
    const values = config?.widgets_values;
    if (!Array.isArray(values)) {
        return;
    }
    const looksLegacy = (
        values.length < G2_WIDGET_VALUE_COUNT
        || typeof values[G2_CUSTOM_SIZE_WIDGET_INDEX] === "number"
    );
    if (looksLegacy) {
        values.splice(G2_CUSTOM_SIZE_WIDGET_INDEX, 0, "");
    }
}

function refreshG2Node(node) {
    const model = String(widgetByName(node, "model")?.value ?? LOWPRICE_MODEL);
    const isLowprice = model === LOWPRICE_MODEL;
    normalizeLowpriceSizeWidgets(node);
    updateCombo(
        widgetByName(node, "resolution"),
        isLowprice ? ["1k", "2k", "4k"] : ["1k"],
        "1k",
    );
    setWidgetVisible(widgetByName(node, "ratio"), !isLowprice);
    setWidgetVisible(widgetByName(node, "size"), isLowprice);
    setWidgetVisible(
        widgetByName(node, "custom_size"),
        isLowprice && String(widgetByName(node, "size")?.value) === "custom",
    );
    setWidgetVisible(widgetByName(node, "n"), isLowprice);

    for (const input of node.inputs ?? []) {
        const match = /^image([1-9]|1[0-6])$/.exec(input.name);
        if (!match) {
            continue;
        }
        const index = Number(match[1]);
        const allowed = (
            isLowprice
            || (model === "zhenzhen-image-g2-i2i" && index <= 10)
        );
        input.hidden = !allowed && input.link == null;
    }
    resizeNode(node, 340);
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

function wrapRefresh(node, refresh, widgetName = "model") {
    const widget = widgetByName(node, widgetName);
    const callbackKey = `seedanceZhenzhenCallback_${widgetName}`;
    if (!widget || widget[callbackKey]) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const result = originalCallback?.apply(widget, args);
        refresh(node);
        return result;
    };
    widget[callbackKey] = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.ZhenzhenModelUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (![G2_NODE_NAME, NB_NODE_NAME, V31_NODE_NAME].includes(nodeData.name)) {
            return;
        }
        const refreshers = {
            [G2_NODE_NAME]: refreshG2Node,
            [NB_NODE_NAME]: refreshNBNode,
            [V31_NODE_NAME]: refreshV31Node,
        };
        const refresh = refreshers[nodeData.name];

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            wrapRefresh(this, refresh);
            if (nodeData.name === G2_NODE_NAME) {
                wrapRefresh(this, refresh, "size");
            }
            refresh(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            if (nodeData.name === G2_NODE_NAME) {
                migrateLegacyG2WidgetValues(arguments[0]);
            }
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
