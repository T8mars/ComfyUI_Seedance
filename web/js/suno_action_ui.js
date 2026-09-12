import { app } from "../../../scripts/app.js";
import {
    resizeSeedanceNode,
    setSeedanceInputVisible as setInputVisible,
    setSeedanceWidgetVisible as setWidgetVisible,
} from "./dynamic_widget_ui.js";

const SUNO_NODE_NAME = "Suno_Music";
const ALWAYS_VISIBLE = new Set(["operation", "skip_error"]);
const AUDIO_FIELDS = [
    "audio1",
    "audio_url1",
    "audio2",
    "audio_url2",
    "audio3",
    "audio_url3",
    "audio4",
    "audio_url4",
];
const MODEL_AUDIO_FIELDS = Array.from({ length: 24 }, (_, index) => {
    const slot = index + 1;
    return [`audio${slot}`, `audio_url${slot}`];
}).flat();
const V6_VERSIONS = ["v6", "v6-wild", "v6-mini"];
const ALL_VERSIONS = [
    ...V6_VERSIONS,
    "v3.5",
    "v4",
    "v4.5",
    "v4.5+",
    "v4.5-all",
    "v5",
    "v5.5",
];
const V6_ONLY_OPERATIONS = new Set(["suno-upload-cover", "suno-upload-extend"]);
const V6_ADVANCED_FIELDS = [
    "custom_model_id",
    "prompt",
    "tags",
    "title",
    "negative_tags",
    "style_weight",
    "weirdness",
    "audio_weight",
    "auto_lyrics",
    "vocal_gender",
    "persona_id",
    "target_duration_s",
    "variety",
    "max_mode",
    "audio_format",
];

const ACTION_FIELDS = {
    "suno-generation": ["prompt", "version", "custom", "instrumental", "title", "style", "vocal_gender"],
    "suno-create-model": ["name", ...MODEL_AUDIO_FIELDS],
    "suno-upload-cover": ["version", "custom", "instrumental", "gpt_description", ...V6_ADVANCED_FIELDS, "audio1", "audio_url1"],
    "suno-upload-extend": ["version", "continue_at", ...V6_ADVANCED_FIELDS, "audio1", "audio_url1"],
    "suno-lyrics": ["prompt"],
    "suno-upload": ["audio1", "audio_url1"],
    "suno-extend": ["version", "task_id", "audio_index", "continue_at"],
    "suno-cover-song": ["prompt", "version", "task_id", "audio_index"],
    "suno-inspo": ["version", ...AUDIO_FIELDS],
    "suno-mashup": ["prompt", "version", "task_id", "task_id_2"],
    "suno-upsample-tags": ["tags"],
    "suno-sounds": ["prompt", "version"],
    "suno-create-voice": ["audio1", "audio_url1"],
    "suno-stems": ["task_id", "audio_index"],
    "suno-stems-all": ["task_id", "audio_index"],
    "suno-wav": ["task_id", "audio_index"],
    "suno-generate-mp4": ["task_id", "audio_index"],
    "suno-concat": ["task_id", "audio_index"],
    "suno-crop": ["task_id", "audio_index", "start_s", "end_s"],
    "suno-fade-in": ["task_id", "audio_index", "duration_s"],
    "suno-fade-out": ["task_id", "audio_index", "duration_s"],
    "suno-remove-section": ["task_id", "audio_index", "start_s", "end_s"],
    "suno-replace-music": ["version", "task_id", "audio_index", "start_s", "end_s"],
    "suno-adjust-speed": ["task_id", "audio_index", "speed"],
    "suno-remaster": ["task_id", "audio_index"],
    "suno-midi": ["task_id", "audio_index"],
    "suno-bpm": ["task_id", "audio_index"],
    "suno-aligned-lyrics": ["task_id", "audio_index"],
    "suno-persona": ["task_id", "audio_index", "name"],
    "suno-vox": ["task_id", "audio_index"],
    "suno-sample": ["prompt", "version", "task_id", "audio_index", "start_s", "end_s"],
    "suno-add-vocals": ["prompt", "version", "task_id", "audio_index"],
    "suno-add-instrumental": ["prompt", "version", "task_id", "audio_index"],
    "suno-add-stem": ["prompt", "version", "task_id", "audio_index"],
};

const MANAGED_FIELDS = new Set(
    Object.values(ACTION_FIELDS).flat().concat([...ALWAYS_VISIBLE]),
);

function widgetByName(node, name) {
    return node.widgets?.find((widget) => widget.name === name);
}

function setVersionChoices(node, operation) {
    const versionWidget = widgetByName(node, "version");
    if (!versionWidget?.options) {
        return;
    }
    const choices = V6_ONLY_OPERATIONS.has(operation) ? V6_VERSIONS : ALL_VERSIONS;
    versionWidget.options.values = [...choices];
    if (!choices.includes(String(versionWidget.value ?? ""))) {
        versionWidget.value = choices[0];
    }
}

function refreshSunoNode(node) {
    const operationWidget = widgetByName(node, "operation");
    const operation = String(operationWidget?.value ?? "suno-generation");
    const fields = new Set(ACTION_FIELDS[operation] ?? []);
    setVersionChoices(node, operation);

    const customModelId = String(widgetByName(node, "custom_model_id")?.value ?? "").trim();
    if (customModelId && V6_ONLY_OPERATIONS.has(operation)) {
        fields.delete("version");
        fields.delete("persona_id");
    }

    if (operation === "suno-upload-cover") {
        const custom = Boolean(widgetByName(node, "custom")?.value);
        const instrumental = Boolean(widgetByName(node, "instrumental")?.value);
        if (custom) {
            fields.delete("gpt_description");
            if (instrumental) {
                fields.delete("prompt");
            }
        } else {
            for (const name of [
                "prompt",
                "tags",
                "title",
                "negative_tags",
                "style_weight",
                "weirdness",
                "audio_weight",
                "auto_lyrics",
                "persona_id",
                "target_duration_s",
                "max_mode",
            ]) {
                fields.delete(name);
            }
        }
    }

    for (const name of ALWAYS_VISIBLE) {
        fields.add(name);
    }

    for (const widget of node.widgets ?? []) {
        if (MANAGED_FIELDS.has(widget.name)) {
            setWidgetVisible(widget, fields.has(widget.name));
        }
    }

    for (const input of node.inputs ?? []) {
        if (!MANAGED_FIELDS.has(input.name)) {
            continue;
        }
        setInputVisible(node, input, fields.has(input.name));
    }

    resizeSeedanceNode(node, 320);
}

app.registerExtension({
    name: "ComfyUI_Seedance.SunoActionUI",
    async beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== SUNO_NODE_NAME) {
            return;
        }

        const originalOnNodeCreated = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            const result = originalOnNodeCreated?.apply(this, arguments);
            const operationWidget = this.widgets?.find(
                (widget) => widget.name === "operation",
            );
            if (operationWidget && !operationWidget.seedanceSunoCallback) {
                const originalCallback = operationWidget.callback;
                operationWidget.callback = (...args) => {
                    const callbackResult = originalCallback?.apply(operationWidget, args);
                    refreshSunoNode(this);
                    return callbackResult;
                };
                operationWidget.seedanceSunoCallback = true;
            }
            for (const name of ["custom", "instrumental", "custom_model_id"] ) {
                const widget = widgetByName(this, name);
                if (!widget || widget.seedanceSunoCallback) {
                    continue;
                }
                const originalCallback = widget.callback;
                widget.callback = (...args) => {
                    const callbackResult = originalCallback?.apply(widget, args);
                    refreshSunoNode(this);
                    return callbackResult;
                };
                widget.seedanceSunoCallback = true;
            }
            refreshSunoNode(this);
            return result;
        };

        const originalOnConfigure = nodeType.prototype.onConfigure;
        nodeType.prototype.onConfigure = function () {
            const result = originalOnConfigure?.apply(this, arguments);
            refreshSunoNode(this);
            return result;
        };

        const originalOnConnectionsChange = nodeType.prototype.onConnectionsChange;
        nodeType.prototype.onConnectionsChange = function () {
            const result = originalOnConnectionsChange?.apply(this, arguments);
            refreshSunoNode(this);
            return result;
        };
    },
});
