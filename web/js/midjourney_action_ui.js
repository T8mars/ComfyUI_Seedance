import { app } from "../../../scripts/app.js";

const MIDJOURNEY_NODE_NAME = "Midjourney_Multi_Action";
const CONVERTED_WIDGET_PREFIX = "converted-widget";
const ALWAYS_VISIBLE = new Set(["operation", "skip_error"]);
const OPERATION_LABELS = {
    "midjourney-imagine": "midjourney-imagine｜文生图 / 参考图生成",
    "midjourney-blend": "midjourney-blend｜2-4 张图片融合",
    "midjourney-describe": "midjourney-describe｜图片反推提示词",
    "midjourney-edits": "midjourney-edits｜图片编辑",
    "midjourney-upscale": "midjourney-upscale｜指定图片放大",
    "midjourney-variation": "midjourney-variation｜生成图片变体",
    "midjourney-high-variation": "midjourney-high-variation｜大幅变体",
    "midjourney-low-variation": "midjourney-low-variation｜轻微变体",
    "midjourney-reroll": "midjourney-reroll｜重新生成整组",
    "midjourney-zoom": "midjourney-zoom｜缩放扩图",
    "midjourney-pan": "midjourney-pan｜平移扩图",
    "midjourney-inpaint": "midjourney-inpaint｜进入局部重绘",
    "midjourney-modal": "midjourney-modal｜提交局部重绘",
    "midjourney-video": "midjourney-video｜图生视频 / 首尾帧",
    "midjourney-remix-strong": "midjourney-remix-strong｜强重塑",
    "midjourney-remix-subtle": "midjourney-remix-subtle｜弱重塑",
};
const OPERATION_BY_LABEL = Object.fromEntries(
    Object.entries(OPERATION_LABELS).map(([operation, label]) => [label, operation]),
);
const SIZE_OPTIONS = [
    "1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "custom",
];
const CUSTOM_SIZE_WIDGET_INDEX = 4;
const CURRENT_WIDGET_VALUE_COUNT = 48;
const LEGACY_DIMENSION_VALUES = new Set(["unset", "SQUARE", "PORTRAIT", "LANDSCAPE"]);
const FRIENDLY_COMBOS = {
    speed: { values: ["relax", "fast", "turbo"], fallback: "relax" },
    dimensions: { values: ["SQUARE", "PORTRAIT", "LANDSCAPE"], fallback: "SQUARE" },
    quality: { values: ["1", "0.25", "0.5", "2"], fallback: "1" },
    version: { values: ["8.2", "8.1", "7", "6.1", "6", "5.2", "5.1", "5"], fallback: "8.2" },
    direction: { values: ["right", "left", "up", "down"], fallback: "right" },
};
const IMAGE_FIELDS = [
    "image1", "image_url1",
    "image2", "image_url2",
    "image3", "image_url3",
    "image4", "image_url4",
];
const STRUCTURED_FIELDS = [
    "quality", "style", "version", "seed", "negative_prompt",
    "stylize", "chaos", "weird", "tile", "niji", "iw", "cw", "sw",
    "cref", "sref", "dref", "dw", "repeat", "raw", "draft", "hd",
    "stop", "extra",
];

const ACTION_FIELDS = {
    "midjourney-imagine": [
        "prompt", "speed", "size", "custom_size", ...STRUCTURED_FIELDS, ...IMAGE_FIELDS,
        "metadata_json",
    ],
    "midjourney-blend": [
        "speed", "size", "custom_size", ...IMAGE_FIELDS, "metadata_json",
    ],
    "midjourney-describe": [
        "speed", "image1", "image_url1", "metadata_json",
    ],
    "midjourney-edits": [
        "prompt", "speed", "size", "custom_size", ...STRUCTURED_FIELDS, ...IMAGE_FIELDS,
        "metadata_json",
    ],
    "midjourney-upscale": [
        "task_id", "index", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-variation": [
        "task_id", "index", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-high-variation": [
        "task_id", "index", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-low-variation": [
        "task_id", "index", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-reroll": [
        "task_id", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-zoom": [
        "task_id", "index", "custom_id", "zoom_ratio", "speed",
        "metadata_json",
    ],
    "midjourney-pan": [
        "task_id", "index", "custom_id", "direction", "speed",
        "metadata_json",
    ],
    "midjourney-inpaint": [
        "task_id", "index", "custom_id", "speed", "metadata_json",
    ],
    "midjourney-modal": [
        "task_id", "prompt", "speed", "modal_mode", "mask", "mask_url",
        "metadata_json",
    ],
    "midjourney-video": [
        "prompt", "image1", "image_url1", "task_id", "index",
        "video_type", "animate_mode", "motion", "batch_size",
        "end_image", "end_url",
    ],
    "midjourney-remix-strong": [
        "task_id", "index", "prompt", "speed",
    ],
    "midjourney-remix-subtle": [
        "task_id", "index", "prompt", "speed",
    ],
};

const MANAGED_FIELDS = new Set(
    Object.values(ACTION_FIELDS).flat().concat([...ALWAYS_VISIBLE]),
);

function isConvertedWidget(widget) {
    return (
        String(widget?.type ?? "").startsWith(CONVERTED_WIDGET_PREFIX)
        || Object.prototype.hasOwnProperty.call(widget ?? {}, "origType")
    );
}

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function setComboValues(widget, values) {
    if (!widget) {
        return;
    }
    widget.options = widget.options ?? {};
    widget.options.values = [...values];
}

function normalizeOperationWidget(node) {
    const widget = widgetByName(node, "operation");
    if (!widget) {
        return;
    }
    const rawValue = String(widget.value ?? "");
    const operation = OPERATION_BY_LABEL[rawValue] ?? rawValue;
    widget.value = OPERATION_LABELS[operation] ?? OPERATION_LABELS["midjourney-imagine"];
    setComboValues(widget, Object.values(OPERATION_LABELS));
}

function normalizeSizeWidget(node) {
    const widget = widgetByName(node, "size");
    const customWidget = widgetByName(node, "custom_size");
    if (!widget) {
        return;
    }
    const rawValue = String(widget.value ?? "").trim();
    if (SIZE_OPTIONS.includes(rawValue)) {
        widget.value = rawValue;
    } else if (/^\d+:\d+$/.test(rawValue)) {
        widget.value = "custom";
        if (customWidget) {
            customWidget.value = rawValue;
        }
    } else {
        widget.value = "1:1";
    }
    setComboValues(widget, SIZE_OPTIONS);
}

function normalizeFriendlyWidgets(node) {
    normalizeOperationWidget(node);
    normalizeSizeWidget(node);
    for (const [name, config] of Object.entries(FRIENDLY_COMBOS)) {
        const widget = widgetByName(node, name);
        if (!widget) {
            continue;
        }
        if (!config.values.includes(String(widget.value ?? ""))) {
            widget.value = config.fallback;
        }
        setComboValues(widget, config.values);
    }
}

function migrateLegacyWidgetValues(config) {
    const values = config?.widgets_values;
    if (!Array.isArray(values)) {
        return;
    }
    const looksLegacy = (
        values.length < CURRENT_WIDGET_VALUE_COUNT
        || LEGACY_DIMENSION_VALUES.has(String(values[CUSTOM_SIZE_WIDGET_INDEX] ?? ""))
    );
    if (!looksLegacy) {
        return;
    }
    values.splice(CUSTOM_SIZE_WIDGET_INDEX, 0, "");
}

function setWidgetVisible(widget, visible) {
    if (!widget || !MANAGED_FIELDS.has(widget.name) || isConvertedWidget(widget)) {
        return;
    }
    if (!widget.seedanceMidjourneyOriginal) {
        widget.seedanceMidjourneyOriginal = {
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
    const original = widget.seedanceMidjourneyOriginal;
    if (visible) {
        widget.type = original.type;
        widget.computeSize = original.computeSize;
    } else {
        widget.type = "hidden";
        widget.computeSize = () => [0, -4];
    }
}

function activeFields(node) {
    const operationWidget = widgetByName(node, "operation");
    const operationValue = String(
        operationWidget?.value ?? OPERATION_LABELS["midjourney-imagine"],
    );
    const operation = OPERATION_BY_LABEL[operationValue] ?? operationValue;
    const fields = new Set(ACTION_FIELDS[operation] ?? []);
    for (const name of ALWAYS_VISIBLE) {
        fields.add(name);
    }

    if (operation === "midjourney-modal") {
        const modeWidget = widgetByName(node, "modal_mode");
        if (String(modeWidget?.value ?? "region") === "outpaint") {
            fields.delete("mask");
            fields.delete("mask_url");
        }
    }
    if (String(widgetByName(node, "size")?.value ?? "1:1") !== "custom") {
        fields.delete("custom_size");
    }
    return fields;
}

function refreshMidjourneyNode(node) {
    const fields = activeFields(node);
    for (const widget of node.widgets ?? []) {
        setWidgetVisible(widget, fields.has(widget.name));
    }

    for (const input of node.inputs ?? []) {
        if (!MANAGED_FIELDS.has(input.name)) {
            continue;
        }
        const connected = input.link != null;
        input.hidden = !fields.has(input.name) && !connected;
    }

    requestAnimationFrame(() => {
        const computed = node.computeSize?.();
        if (computed) {
            node.setSize?.([
                Math.max(node.size?.[0] ?? 340, computed[0], 340),
                Math.max(computed[1], 120),
            ]);
        }
        node.setDirtyCanvas?.(true, true);
    });
}

function wrapRefreshWidget(node, name) {
    const widget = node.widgets?.find((candidate) => candidate.name === name);
    if (!widget || widget.seedanceMidjourneyCallback) {
        return;
    }
    const originalCallback = widget.callback;
    widget.callback = (...args) => {
        const callbackResult = originalCallback?.apply(widget, args);
        refreshMidjourneyNode(node);
        return callbackResult;
    };
    widget.seedanceMidjourneyCallback = true;
}

app.registerExtension({
    name: "ComfyUI_Seedance.MidjourneyActionUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== MIDJOURNEY_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            normalizeFriendlyWidgets(this);
            wrapRefreshWidget(this, "operation");
            wrapRefreshWidget(this, "modal_mode");
            wrapRefreshWidget(this, "size");
            refreshMidjourneyNode(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            migrateLegacyWidgetValues(arguments[0]);
            const result = originalOnConfigure?.apply(this, arguments);
            normalizeFriendlyWidgets(this);
            refreshMidjourneyNode(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refreshMidjourneyNode(this);
            return result;
        };
    },
});
