const CONVERTED_WIDGET_PREFIX = "converted-widget";
const DYNAMIC_HIDDEN_WIDGET_TYPE = `${CONVERTED_WIDGET_PREFIX}:seedance-hidden`;
const ORIGINAL_WIDGET_STATE = Symbol("seedanceDynamicWidgetOriginal");
const HIDDEN_WIDGET_SIZE = () => [0, -4];

function hasOwn(object, property) {
    return Object.prototype.hasOwnProperty.call(object ?? {}, property);
}

function isExternalConvertedWidget(widget) {
    const type = String(widget?.type ?? "");
    return (
        hasOwn(widget, "origType")
        || (
            type.startsWith(CONVERTED_WIDGET_PREFIX)
            && type !== DYNAMIC_HIDDEN_WIDGET_TYPE
        )
    );
}

export function setSeedanceWidgetVisible(widget, visible) {
    if (!widget || isExternalConvertedWidget(widget)) {
        return false;
    }

    if (!widget[ORIGINAL_WIDGET_STATE]) {
        widget[ORIGINAL_WIDGET_STATE] = {
            type: widget.type,
            computeSize: widget.computeSize,
        };
    }
    const original = widget[ORIGINAL_WIDGET_STATE];
    const nextType = visible ? original.type : DYNAMIC_HIDDEN_WIDGET_TYPE;
    const nextComputeSize = visible ? original.computeSize : HIDDEN_WIDGET_SIZE;
    const changed = (
        widget.type !== nextType
        || widget.computeSize !== nextComputeSize
    );

    widget.type = nextType;
    widget.computeSize = nextComputeSize;
    return changed;
}

export function resizeSeedanceNode(node, minimumWidth = 320) {
    if (!node) {
        return;
    }
    if (node.seedanceDynamicResizeFrame != null) {
        cancelAnimationFrame(node.seedanceDynamicResizeFrame);
    }
    node.seedanceDynamicResizeFrame = requestAnimationFrame(() => {
        node.seedanceDynamicResizeFrame = null;
        const computed = node.computeSize?.();
        if (computed) {
            const currentWidth = Number(node.size?.[0]) || minimumWidth;
            node.setSize?.([
                Math.max(currentWidth, Number(computed[0]) || 0, minimumWidth),
                Math.max(Number(computed[1]) || 0, 120),
            ]);
        }
        node.setDirtyCanvas?.(true, true);
    });
}

export const seedanceDynamicWidgetInternals = Object.freeze({
    convertedWidgetPrefix: CONVERTED_WIDGET_PREFIX,
    hiddenWidgetType: DYNAMIC_HIDDEN_WIDGET_TYPE,
});
