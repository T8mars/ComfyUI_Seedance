import { app } from "../../../scripts/app.js";
import { api } from "../../../scripts/api.js";
import { originalSeedanceNodeName } from "./concurrent_node_ui.js";
import { setSeedanceWidgetVisible } from "./dynamic_widget_ui.js";

const INSTALLED = Symbol("seedanceGifPreview");
const TARGETS = new Set(["Zhenzhen_Image_G26", "SeedanceConcurrent_Image_Await"]);
const isGif = (entry) => typeof entry?.filename === "string" && /\.gif$/i.test(entry.filename);

function render(node, entries) {
    if (!entries.length) {
        if (node.seedanceGifWidget) {
            setSeedanceWidgetVisible(node.seedanceGifWidget, false);
            node.seedanceGifContainer.replaceChildren();
            node.seedanceGifContainer.style.display = "none";
        }
        return;
    }
    if (!node.seedanceGifWidget) {
        const container = document.createElement("div");
        container.className = "seedance-gif-preview";
        container.style.cssText = "width:100%;height:100%;display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:8px;overflow:auto;background:#202020";
        const widget = node.addDOMWidget("seedance_gif_preview", "preview", container, { serialize: false, hideOnZoom: false });
        widget.serialize = false;
        widget.computeSize = (width) => [width, 330];
        node.seedanceGifWidget = widget;
        node.seedanceGifContainer = container;
    }
    setSeedanceWidgetVisible(node.seedanceGifWidget, true);
    const container = node.seedanceGifContainer;
    container.style.display = "grid";
    container.replaceChildren();
    for (const [index, entry] of entries.entries()) {
        const url = api.apiURL("/view?" + new URLSearchParams({ filename: entry.filename,
            subfolder: entry.subfolder ?? "", type: entry.type ?? "output" }));
        const item = document.createElement("div");
        item.style.cssText = "min-width:0;display:flex;flex-direction:column;gap:4px;align-items:center";
        const image = document.createElement("img");
        image.src = url;
        image.alt = `GIF ${index + 1}`;
        image.style.cssText = "width:100%;min-height:0;flex:1;object-fit:contain";
        const save = document.createElement("a");
        save.href = url;
        save.download = entry.filename;
        save.textContent = `GIF ${index + 1} · 保存 / Save`;
        save.style.cssText = "color:#93c5fd;font:12px sans-serif;padding:4px;text-align:center";
        item.append(image, save);
        container.append(item);
    }
    node.setSize([node.size[0], Math.max(node.size[1], node.computeSize()[1])]);
    node.graph?.setDirtyCanvas(true, true);
}

function install(node) {
    if (node[INSTALLED]) return;
    node[INSTALLED] = true;
    const previous = node.onExecuted;
    node.onExecuted = function (message) {
        const gifs = message?.seedance_gifs ?? (message?.images ?? []).filter(isGif);
        if (!gifs.length) {
            render(this, []);
            return previous?.apply(this, arguments);
        }
        // Current ComfyUI treats animated .gif as video. Keep its native renderer
        // for other results, and play original GIF bytes in an HTML image instead.
        const native = { ...message, images: (message.images ?? []).filter((entry) => !isGif(entry)), seedance_gifs: gifs };
        delete native.animated;
        if (app.nodeOutputs) app.nodeOutputs[String(this.id)] = native;
        const result = previous?.call(this, native);
        this.previewMediaType = "image";
        render(this, gifs);
        return result;
    };
    const configured = node.onConfigure;
    node.onConfigure = function () {
        const result = configured?.apply(this, arguments);
        requestAnimationFrame(() => {
            const cached = app.nodeOutputs?.[String(this.id)];
            if (cached?.seedance_gifs?.length) render(this, cached.seedance_gifs);
        });
        return result;
    };
}

app.registerExtension({
    name: "ComfyUI_Seedance.GIFPreview",
    async nodeCreated(node) {
        const name = originalSeedanceNodeName(node.comfyClass ?? node.constructor?.comfyClass ?? node.type ?? "");
        if (TARGETS.has(name)) install(node);
    },
});
