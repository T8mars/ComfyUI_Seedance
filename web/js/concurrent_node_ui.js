const WRAPPER_PREFIX = "SeedanceConcurrent_";
const WRAPPER_SUFFIX = "_Submit";

const SPECIAL_ALIASES = new Map([
    ["SeedanceConcurrent_Midjourney_Image_Submit", "Midjourney_Multi_Action"],
    ["SeedanceConcurrent_Midjourney_Video_Submit", "Midjourney_Multi_Action"],
]);

export function originalSeedanceNodeName(nodeName) {
    const name = String(nodeName ?? "");
    const special = SPECIAL_ALIASES.get(name);
    if (special) {
        return special;
    }
    if (name.startsWith(WRAPPER_PREFIX) && name.endsWith(WRAPPER_SUFFIX)) {
        return name.slice(WRAPPER_PREFIX.length, -WRAPPER_SUFFIX.length);
    }
    return name;
}
