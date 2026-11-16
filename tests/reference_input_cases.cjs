const cases = [
    ["seedance_api_key_link.js", "Seedance_2_5_Video", { image: 30, video: 10, audio: 10 }, ["seedance-2.5-standard-multi", "seedance-2.5-standard-i2v", "seedance-2.5-standard-t2v"]],
    ["wan30_model_ui.js", "Wan_3_0_Video", { image: 10, video: 5, audio: 5 }, ["wan-3.0-r2v", "wan-3.0-i2v"]],
    ["flux3_model_ui.js", "Flux_3_Video", { image: 10 }, ["flux-3-video-i2v", "flux-3-video-t2v", "flux-3-video-v2v", "flux-3-video-draft-enhance"]],
    ["vidu_q4_ui.js", "Vidu_Q4_Preview_Video", { image: 15, audio: 3 }, ["vidu-q4-preview-r2v", "vidu-q4-preview-i2v"]],
    ["image_models_26_ui.js", "Zhenzhen_Image_G26", { image: 16 }, ["zhenzhen-image-g-v2.6-lowprice", "zhenzhen-image-g-v2.6-flare", "zhenzhen-image-g-v2.6-sunburst"]],
    ["image_models_26_ui.js", "Krea_V3_Image", { image: 8 }, ["krea-v3-i2i", "krea-v3-t2i"]],
    ["preview_muse_flux_ui.js", "HY_Image_3_5_Preview", { image: 5 }, ["zhenzhen-image-hy-v3.5-preview"]],
    ["preview_muse_flux_ui.js", "Muse_Image", { image: 9 }, ["zhenzhen-image-muse"]],
    ["preview_muse_flux_ui.js", "Muse_Video", { image: 9 }, ["zhenzhen-video-muse"]],
    ["preview_muse_flux_ui.js", "Flux_3_Image_Variants", { image: 10 }, ["flux-3-image-i2i", "flux-3-image-klein-i2i", "flux-3-image-t2i", "flux-3-image-klein-t2i"]],
    ["nb_lowprice_doubao_ui.js", "Zhenzhen_Image_NB_Lowprice", { image: 14 }, ["zhenzhen-image-nb-pro-lowprice", "zhenzhen-image-nb-2.1-lowprice"]],
    ["h3_turbo_ui.js", "Minimax_H3_ComfyUI_Max", { image: 9, audio: 3 }, []],
    ["h3_turbo_ui.js", "Minimax_H3_Image", { image: 16 }, []],
    ["h3_turbo_ui.js", "Qwen_Image_2_1_Turbo", { image: 4 }, []],
    ["hitem_meshy_ui.js", "Hitem3D_V2", { image: 4 }, ["hitem3d-v2-multi-image-to-3d", "hitem3d-v2-image-to-3d"]],
    ["hitem_meshy_ui.js", "Hitem3D_Portrait_V2_1", { image: 4 }, ["hitem3d-portrait-v2.1-multi-image-to-3d", "hitem3d-portrait-v2.1-image-to-3d"]],
    ["hitem_meshy_ui.js", "Meshy_6_Global", { image: 1 }, ["meshy-6-global-image-to-3d", "meshy-6-global-text-to-3d"]],
    ["kling_v4_ui.js", "Kling_V4_Omni", { image: 10, video: 5 }, ["kling-v4-omni", "zhenzhen-video-kling-v4-flash"]],
    ["kling_v4_ui.js", "Kling_V4_Custom_Element", { image: 4 }, []],
    ["kling_v4_ui.js", "Zhenzhen_Video_G_Omni_1_2_Flash_Lowprice", { image: 10, video: 1 }, []],
    ["tripo_ui.js", "Tripo_Generate", { image: 4 }, ["tripo-h-v3.1-multiview-to-3d", "tripo-h-v3.1-image-to-3d", "tripo-h-v3.1-text-to-3d"]],
    ["seedream55_ui.js", "Seedream_5_5_Image", { image: 10 }, ["seedream-v5.5-i2i", "dola-seedream-5.5-i2i", "seedream-v5.5-t2i", "dola-seedream-5.5-t2i"]],
];

function limitsFor(key, model, capacity, mode = "image") {
    const empty = Object.fromEntries(Object.keys(capacity).map((family) => [family, 0]));
    if (key === "Seedance_2_5_Video") return model.endsWith("-multi") ? capacity : { ...empty, image: model.endsWith("-i2v") ? 2 : 0 };
    if (key === "Wan_3_0_Video") return model.endsWith("-r2v") ? capacity : { ...empty, image: 2 };
    if (key === "Flux_3_Video" || key === "Krea_V3_Image" || key === "Flux_3_Image_Variants" || key === "Seedream_5_5_Image") {
        return model.endsWith("-i2v") || model.endsWith("-i2i") ? capacity : empty;
    }
    if (key === "Vidu_Q4_Preview_Video") return model.endsWith("-r2v") ? capacity : { image: 1, audio: 0 };
    if (key === "Zhenzhen_Image_G26") return mode === "gif" ? empty : capacity;
    if (key.startsWith("Hitem3D") || key === "Tripo_Generate") return { image: model.includes("text-to") ? 0 : model.includes("multi") ? 4 : 1 };
    if (key === "Meshy_6_Global") return { image: model.includes("text-to") ? 0 : 1 };
    return capacity;
}

module.exports = { cases, limitsFor };
