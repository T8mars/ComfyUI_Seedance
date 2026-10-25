# ComfyUI_Seedance

**Language: [Simplified Chinese (Default)](README.md) | English**

ComfyUI nodes for video, image, audio, speech, music, and 3D generation through [api.seedance.nz](https://api.seedance.nz). The plugin supports local ComfyUI media inputs, asynchronous task polling, resilient result downloads, standard seed controls, error skipping, and optional concurrent execution.

## v0.23.0 - 2026-10-25

- Added independent `Zhenzhen_Motion_Video` with Standard/Pro selection, creation and completed-task revision, without changing existing video nodes.
- Supports 15/30/45/60 seconds, three ratios, 720p/1080p, ten templates, text assets, and up to four persistent public image URLs. Temporary upload URLs are not used.
- Includes video, optional cover/preview/HTML/subtitle URLs and storyboard/fallback outputs, cache-only seeds, `skip_error`, resilient downloads and existing 10-slot video concurrency.
- Four credential-free workflows cover Standard/Pro generation and connected revision.
- Both models completed actual 15-second, 720p generation and revision, downloading and full decoding. Pro revision confirmed all four persistent image URLs reached the API, but actual reference-image rendering remains unresolved as noted below. All 548 offline tests, 245 workflow audits, 20 frontend scripts and real-canvas checks passed. Upstream scene-layout checks can still reject generated scenes; previews are never treated as completed videos.

## v0.22.0 - 2026-10-23

- Added independent `Moss_Image` for `moss-image` text generation and single-reference editing, with eight ratios (default 9:16), resilient downloads, cache-only seeds, `skip_error`, and existing 30-slot image concurrency. Resolution, batch-count, output-format, and API seed fields are not submitted. Includes two credential-free examples.
- Actual Moss text generation and local-reference editing completed submission, polling, download, and decoding, returning two 1456x1456 images. Both downloads recovered TLS failures through the existing official Tencent COS hostname fallback. All 531 offline tests, 241 workflows, and 19 frontend scripts passed checks; real serial/concurrent canvas resizing and save/reload passed as well.
- Added independent `Zhenzhen_Image_NB_Lowprice` for the Pro/2.1 Lowprice models: text generation, editing, up to 14 ordered references, 1k/2k/4k, and model-specific ratios. Existing NB nodes are unchanged.
- Added independent `Doubao_Voice_Clone_ICL` for local/URL voice training, preview downloads, returned speaker IDs, and downstream ICL synthesis, with mode-specific controls and expandable advanced settings.
- Both nodes include cache seeds and `skip_error`; NB uses existing 30-slot image concurrency. Nine credential-free workflows cover all image modes, training, synthesis, and the connected training-to-synthesis pipeline.
- Both NB models completed actual 1k text, one-reference, and full-14-reference checks, returning six decoded 1024x1024 images. Doubao completed English-parameter training and connected ICL synthesis; preview WAV and synthesized MP3 downloaded and decoded at 24 kHz. All 519 offline tests, 239 workflows, and 19 frontend scripts passed, alongside actual canvas switching, resizing, and save/reload checks.

## v0.21.0 - 2026-10-11

- Added independent `MAI_Image_2_6`, combining `mai-image-2-6` and `mai-image-2-6-flash` for text generation, single-image editing, and up-to-five-image composition. Each task returns one PNG.
- Text generation supports 1k/2k, common/custom aspect ratios, exact pixel dimensions, automatic aspect ratio, and Bing web grounding. Reference mode hides and omits inactive sizing fields. Includes cache seeds, `skip_error`, and 30-slot image concurrency.
- Added six credential-free examples. Both models' text, single-reference, and two-reference paths completed actual upload (where applicable), submission, polling, download, and decoding, returning 1024x1024 images.
- All 497 offline tests, 230 workflows, and 18 frontend scripts passed checks. Actual ComfyUI canvas verification covered serial/concurrent sizing changes, reference links, resizing, and save/reload.

## v0.20.0 - 2026-10-11

- Added independent `Topaz_Video_Upscale` restoration with `Topaz-Upscale-LowPirce`, one local MP4 or public URL, four output resolutions, and five restoration models. Defaults are `1080p / Max`; no prompt or duration is needed.
- Reuses resilient video downloads, `skip_error`, standard cache seeds, and 10-way video submission. Includes credential-free local-input and URL-input workflows.
- Real node verification uploaded a one-second local MP4 with `720p / Low`, completed submission, polling, download, and full decoding, and returned a 1112x832 H.264 video with 24 frames. All 484 offline tests, 224 workflows, and 17 frontend scripts passed validation.

## v0.19.0 - 2026-10-10

- Added an independent `Zhenzhen_Image_NB_2_1` node for text generation and up-to-14-image editing, 5-5000 prompt characters, 1k/2k/4k, and standard ratios plus `auto`. It generates one image and never submits output-format fields.
- Added an independent `Flux_3_Image` node for text generation and up-to-ten-image editing, five resolutions, and 15 fixed aspect ratios plus `auto`.
- Added an independent four-model `Vidu_Q4_Preview_Video` node for domestic/global I2V and R2V: 3-16 seconds, 540p through 4k, and up to 15 images plus three MP3 audio references in R2V. Local AUDIO inputs are encoded and uploaded automatically.
- All three nodes reuse standard cache seeds, `skip_error`, resilient downloads, and existing image/video concurrent submission. Fixed hidden input loss during temporary layout calculations on current ComfyUI without changing socket or link order.
- Added eight credential-free workflows. NB 2.1 and FLUX text/edit plus all four Vidu model paths completed real submission, polling, download, and decoding checks. Both NB 2.1 paths returned 1024x1024 images; video checks requested 3 seconds at 540p.
- The complete offline suite passed 470 tests; all 222 workflows and 17 frontend scripts passed validation.

## v0.18.0 - 2026-10-02

- Extended the existing Seedream/Dola Seedream image node with domestic and overseas V5 Flash text-to-image and image-to-image models while retaining Pro as the default. Flash accepts 5-5000 prompt characters, 1k/1.5k/2k or custom dimensions, and up to ten references of at most 30 MB each.
- Extended the layer-decomposition node with domestic `seedream-v5-flash-layer-decomposition` and overseas `dola-seedream-5.0-flash-layer-decomposition`, preserving the complete ordered IMAGE/MASK list output.
- Added six credential-free workflows covering domestic and overseas Flash text generation, single-image editing, and layer decomposition.
- All six model paths completed real node verification. The complete offline suite passed 448 tests; all 214 workflows and 16 frontend scripts passed validation.

## v0.17.0 - 2026-09-21

- Added independent `Qwen_Image_Global_2_1` generation/editing node: text or up to 10 ordered reference images, 1k/2k/4k, eight ratios, and optional native seed. It does not send the obsolete `megapixels` or multi-image count fields.
- Added independent `Animate_Motion_Transfer` node: exactly one character image and one motion video, each from a local ComfyUI input or public URL. It exposes the documented frame, pose, camera, and expression controls without a prompt or API seed.
- Both nodes reuse `skip_error`, resilient downloads, and the shared image/video concurrent submit collectors. Four credential-free examples cover Qwen text/edit and Animate local/URL inputs.

## v0.16.0 - 2026-09-12

- Extended the Suno node to 34 operations with `suno-create-model`, `suno-upload-cover`, and `suno-upload-extend`, plus three credential-free workflows.
- All three new paths completed real node checks; the offline suite passed 433 tests and all 204 example workflows parsed successfully.

## v0.15.0 - 2026-09-09

- Added an independent `Zhenzhen Image G v2.5 LowPrice` generation/editing node with text-to-image, up to 15 reference images, 1K/2K/4K, and the documented fixed aspect ratios.
- Added a two-model `Zhenzhen Image G v2.5 Official` generation/editing node for Flare and Sunburst with up to 16 references, 1-4 result images, quality, format, background, and exact-pixel controls.
- Both nodes include resilient image downloads, `skip_error`, standard ComfyUI cache seeds, optional 30-way image submission, and separate generation/editing workflows for every model.
- All three models completed real node-path checks: LowPrice and Flare generated images, while Sunburst uploaded and edited one reference image. Every result downloaded as a valid ComfyUI IMAGE. The complete offline suite passed 425 tests, and all 201 workflows passed JSON and sensitive-data audits.

## API Access

| Service | Audience | Open |
| --- | --- | --- |
| Seedance NZ | Domestic model workflows | <a href="https://api.seedance.nz/sign-up?aff=5f4w"><kbd>Open Seedance NZ</kbd></a> |
| T8star AI | Overseas model workflows | <a href="https://ai.t8star.org/register?aff=dP7j"><kbd>Open T8star AI</kbd></a> |
| RunningHub China | Domestic RunningHub API access | <a href="https://www.runninghub.cn/user-center/1819214514410942465/webapp?inviteCode=rh-v1121"><kbd>Open RunningHub China</kbd></a> |
| RunningHub Global | Overseas RunningHub API access | <a href="https://www.runninghub.ai/user-center/1907375370302308353/webapp?inviteCode=rh-v1121"><kbd>Open RunningHub Global</kbd></a> |

## Earlier Releases

### v0.14.0 - 2026-09-09

- Added independent `VOSR2 4K Image Upscale` and `VOSR2 2K Video Upscale` nodes using the exact `vosr2-image-upscale` and `vosr2-video-upscale` endpoint contracts.
- Supports local images, local videos, and public video URLs with resilient media downloads, `skip_error`, standard seed caching, optional 30-way image submission, and optional 10-way video submission.
- Added two credential-free example workflows. Both nodes completed real upload, submit, poll, download, and media-validity checks.
- The complete offline suite passed 413 tests, and all 195 example workflows passed JSON and sensitive-data audits.

### v0.13.0 - 2026-09-06

- Added an independent `MiniMax-H3 V2 Multimodal Video` node using the exact `MiniMax-H3` model and V2 submit, query, and result contracts without changing existing MiniMax H3 OW nodes or workflows.
- Supports text-to-video, first/last-frame, multimodal-reference, and drive-audio modes with up to nine reference images, three reference videos, three reference audio clips, and optional 10-way video submission.
- Added 480P/768P controls, standard seed caching, `skip_error`, dynamic media widgets, resilient downloads, and four credential-free example workflows.
- Completed a real 4-second, 480P text-to-video upload, submit, poll, download, and MP4 validation. The complete offline suite passed 402 tests.

### v0.12.0 - 2026-09-04

- Expanded the Hailuo H3 Max node to four models with `hailuo-h3-max-turbo-t2v` and `hailuo-h3-max-turbo-i2v`, while preserving its registration name and existing workflows.
- Enforced model-specific resolution casing: original H3 Max uses `480P/768P`, while Max Turbo uses `480p/768p`; the frontend automatically selects a valid value when switching models.
- Added two credential-free Turbo workflows for text-to-video and required-first/optional-last-frame image-to-video.
- Completed real 5-second, 480p upload, submit, poll, download, and MP4 validation for both Turbo models. The complete offline suite passed 391 tests.

### v0.11.0 - 2026-09-01

- Added an independent `Hailuo H3 Max Video (2-in-1)` node for `hailuo-h3-max-t2v` and `hailuo-h3-max-i2v` without changing the existing Hailuo H3 node or saved workflows.
- Kept model contracts separate: T2V sends a fixed aspect ratio, while I2V accepts a required first frame and optional last frame without sending a ratio; both support 5 to 15 seconds and 480P/768P.
- Added standard seed caching, `skip_error`, dynamic media controls, optional 10-way video submission, and two credential-free example workflows.
- Completed real 5-second, 480P upload, submit, poll, download, and MP4 validation for both models. The complete offline suite passed 390 tests.

### v0.10.0 - 2026-08-30

- Added an independent `Zhenzhen Video G Omni 1.1 Flash Lowprice (4 modes)` node with its exact model ID while preserving the original Omni Flash Lowprice node and saved workflows.
- Supports text, first-frame, one/three-image reference, and reference-video generation with 4/6/8/10 seconds, 720p/1080p/4k, 16:9/9:16, dynamic media inputs, `skip_error`, standard seed controls, and 10-way video submission.
- Added four credential-free example workflows covering every generation mode.
- Completed a real 4-second, 720p text-to-video node-path check. Passed 382 offline tests, audited 185 workflows, and validated all 15 frontend scripts.

### v0.9.0 - 2026-08-25

- Expanded the Wan 3.0 node from four to eight models with domestic/global Prime I2V and R2V variants while preserving existing workflows.
- Restricted `enable_thinking` to the documented standard global models; Prime global requests omit it.
- Added four Prime example workflows and resilient Tencent COS result-domain recovery shared by image, video, audio, and generic file downloads.
- Completed real 2-second, 480P node-path checks for all four Prime models. Passed 381 offline tests, audited 181 workflows, and validated all 15 frontend scripts.

### v0.8.1 - 2026-08-25

- Added this complete English README.
- Added language links to both README files while keeping `README.md` as the default GitHub and Comfy Registry document.
- Passed 376 offline tests, audited 177 example workflows, and validated all 15 frontend scripts.

### v0.8.0 - 2026-08-24

- Added one four-model Wan 3.0 node for domestic and global I2V/R2V workflows.
- I2V supports a required first frame and optional last frame. R2V supports up to 10 images, 5 videos, and 5 audio inputs.
- Added model-aware controls, native seed handling, `skip_error`, video concurrency, and four example workflows.
- All four Wan 3.0 model paths completed real 2-second, 480P end-to-end checks with valid H.264 MP4 outputs.

The full historical changelog remains in the [Chinese README](README.md).

## Highlights

- Text-to-video, image-to-video, start/end-frame video, multimodal reference video, and video editing.
- Text-to-image, multi-image editing, segmentation, region editing, and layer decomposition.
- Speech synthesis, voice cloning, audio generation, transcription, music generation, music editing, stems, and media export.
- Text-to-3D and ordered multi-view image-to-3D with native ComfyUI GLB outputs.
- Automatic upload of connected ComfyUI `IMAGE`, `VIDEO`, and `AUDIO` inputs.
- Automatic task submission, progress polling, result download, and ComfyUI media decoding.
- Up to 30 image workers and 10 video workers through optional submit/await nodes.
- Standard ComfyUI seed controls: `fixed`, `randomize`, `increment`, and `decrement`.
- `skip_error` support for continuing batch workflows with valid placeholders.
- Dynamic widgets that show only the controls and media sockets used by the selected model or operation.
- API configuration through a node, environment variables, or a local ignored `.env` file.
- Python 3.9+ with no required `truststore` dependency.

## Supported Families

### Video

- Seedance 2.0 and Seedance 2.5 Standard
- Wan 2.7 and Wan 3.0
- FLUX 3 Video
- HappyHorse 1.1
- Kling 3.0 and Kling O3
- Hailuo 2.3, Hailuo H3, and Hailuo H3 Max
- MiniMax-H3 V2 multimodal video generation
- MiniMax H3 OW and H3 OW Fast
- Vidu Q3
- Animate Motion Transfer
- Zhenzhen Video G, GK, and V3.1
- Midjourney video
- FlashVSR, VOSR2 image/video upscaling, and Zhenzhen Upscaler

### Image and 3D

- Seedream V5 Pro/Flash and Dola Seedream 5.0 Pro/Flash
- Seedream Pro/Flash layer decomposition
- Qwen Image 3.0/Pro and Qwen Image Global 2.1
- Zhenzhen Image G v2.5, G, GK v1.5, GK v2, and Nano Banana
- Wan 2.7 global image generation/editing
- Midjourney image generation and editing
- Hunyuan 3D v3.1

### Audio, Speech, and Music

- Doubao Seed Audio 1.0
- Qwen3 TTS
- MiniMax music, speech, and voice clone
- Mureka BGM
- Whisper 1 transcription
- Suno 34-action music workflows, including V6 custom models and direct audio cover/extend
- Flow Music multi-action workflows

## Node Catalog

All nodes appear under the `Seedance` category. The table uses stable node registration names so workflows remain easy to identify across UI languages.

| Node | Purpose |
| --- | --- |
| `Seedance_Config` | Shared API endpoint and API key configuration |
| `Seedance_TextToVideo` | Seedance text-to-video |
| `Seedance_ImageToVideo` | Seedance first-frame and optional last-frame video |
| `Seedance_MultimodalVideo` | Seedance image/video/audio reference generation |
| `Seedance_2_5_Video` | Six Seedance 2.5 domestic/global T2V, I2V, and Multi models |
| `Wan_3_0_Video` | Eight Wan 3.0 standard/Prime domestic/global I2V and R2V models |
| `Wan_2_7_Spicy_I2V` | Wan 2.7 Spicy image-to-video |
| `HappyHorse_1_1_Video` | HappyHorse T2V, I2V, and reference video |
| `Kling_Video` | Kling T2V, I2V, start/end, and O3 reference video |
| `Kling_Edit_Video` | Kling O3 video editing |
| `Hailuo_2_3_Video` | Hailuo 2.3 T2V and I2V |
| `Hailuo_H3_Video` | Hailuo H3 domestic/global T2V, I2V, and Multi |
| `Hailuo_H3_Max_Video` | Four Hailuo H3 Max/Max Turbo T2V and first/optional-last-frame I2V models |
| `Minimax_H3_V2_Video` | MiniMax-H3 V2 text, keyframe, multimodal-reference, and drive-audio video generation |
| `Flux_3_Video` | FLUX 3 domestic/global T2V, I2V, V2V, and draft enhancement |
| `Minimax_H3_OW_Video` | MiniMax H3 OW T2V, I2V, and R2V |
| `Minimax_H3_OW_Fast_Video` | MiniMax H3 OW Fast video and audio-driven modes |
| `Minimax_H3_Context_IR` | Text, frame, or multimodal video prompt enhancement |
| `Vidu_Q3_Video` | Vidu Q3 T2V, I2V, start/end, and reference video |
| `Vidu_Q3_ShortPlay` | Vidu Q3 short-play generation |
| `Vidu_Q4_Preview_Video` | Four domestic/global I2V/R2V models; up to 15 images and three MP3 audio references |
| `Flux_3_Image` | FLUX 3 text generation and up-to-ten-image editing |
| `Zhenzhen_Video_G_Omni_Flash` | Zhenzhen Video G Omni Flash |
| `Zhenzhen_Video_G_Omni_Flash_Lowprice` | Omni Flash Lowprice text, first-frame, reference-image, and reference-video generation |
| `Zhenzhen_Video_G_Omni_1_1_Flash_Lowprice` | Omni 1.1 Flash Lowprice text, first-frame, reference-image, and reference-video generation |
| `Zhenzhen_Video_GK_V15` | Zhenzhen Video GK v1.5 |
| `Zhenzhen_Video_V31` | Zhenzhen Video V3.1 Fast, Quality, and Lite |
| `Zhenzhen_Motion_Video` | Standard/Pro Canvas 2D motion graphics and completed-task revision |
| `FashVSR_Video_Upscale` | FlashVSR 480P video upscaling |
| `VOSR2_Image_Upscale` | VOSR2 single-image 4K upscaling |
| `VOSR2_Video_Upscale` | VOSR2 single-video 2K upscaling |
| `Topaz_Video_Upscale` | Single-MP4 restoration with four resolutions and five restoration models |
| `Animate_Motion_Transfer` | Single-image, single-video motion transfer with local or URL inputs |
| `Zhenzhen_Upscaler_Video` | Zhenzhen video upscaling |
| `Seedream_V5_Pro_Image` | Seedream/Dola Seedream V5 Pro/Flash generation and editing |
| `Seedream_V5_Pro_Layer_Decomposition` | Seedream/Dola V5 Pro/Flash layer decomposition |
| `Qwen_Image_3_0` | Qwen Image 3.0/Pro generation and editing |
| `Qwen_Image_Global_2_1` | Qwen Global 2.1 text-to-image or up to ten-image editing |
| `Zhenzhen_Image_G2` | Zhenzhen Image G generation and editing |
| `Zhenzhen_Image_G25_Lowprice` | Zhenzhen Image G v2.5 LowPrice generation and up-to-15-image editing |
| `Zhenzhen_Image_G25_Official` | Flare/Sunburst Image G v2.5 generation and up-to-16-image editing |
| `Zhenzhen_Image_GK_V15` | Zhenzhen Image GK v1.5 generation and editing |
| `Zhenzhen_Image_GK_V2` | Zhenzhen Image GK v2 text-to-image |
| `Zhenzhen_Image_GK_V2_Edit` | Zhenzhen Image GK v2 one-to-three-image editing |
| `Zhenzhen_Image_GK_V2_Segment` | Zhenzhen Image GK v2 segmentation |
| `Zhenzhen_Image_GK_V2_Region_Edit` | Zhenzhen Image GK v2 region editing |
| `Zhenzhen_Image_NB` | Zhenzhen Nano Banana generation and editing |
| `Zhenzhen_Image_NB_2_1` | Independent NB 2.1 text generation and up-to-14-image editing |
| `Zhenzhen_Image_NB_Lowprice` | Pro/2.1 Lowprice text generation and up-to-14-image editing |
| `MAI_Image_2_6` | MAI 2.6/Flash text generation, editing, and up-to-five-image composition |
| `Moss_Image` | Moss text generation or single-reference image editing, with eight aspect ratios |
| `Wan_2_7_Global_Image` | Wan 2.7 global image generation and editing |
| `Hunyuan3D_V3_1` | Hunyuan 3D text or ordered multi-view image generation |
| `Doubao_Seed_Audio` | Doubao Seed Audio generation |
| `Doubao_Voice_Clone_ICL` | Voice training, preview downloads, and ICL synthesis with trained speaker IDs |
| `Qwen3_TTS` | Qwen3 text-to-speech |
| `Minimax_Audio` | MiniMax music, speech, and voice clone |
| `Mureka_BGM` | Mureka background music generation |
| `Whisper_Transcription` | Whisper transcription |
| `Suno_Music` | 34 Suno actions, including custom-model creation and V6 upload cover/extend |
| `Flow_Music` | Flow Music multi-action node |
| `Midjourney_Multi_Action` | Midjourney image and video operations |

Pure image and pure video generation nodes also receive matching `Concurrent Submit | ...` wrappers. Shared await nodes collect up to 30 image futures or 10 video futures while preserving input-slot order.

## Installation

### ComfyUI-Manager

Search for `ComfyUI Seedance` or `seedance` in ComfyUI-Manager, install it, and restart ComfyUI.

You can also use the official Comfy CLI:

```bash
comfy node install seedance
```

### Manual Installation

Clone the repository inside the ComfyUI `custom_nodes` directory:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/T8mars/ComfyUI_Seedance.git
```

Install dependencies with the Python interpreter used by ComfyUI:

```bash
cd ComfyUI
python -m pip install -r custom_nodes/ComfyUI_Seedance/requirements.txt
```

Portable ComfyUI installations should use their bundled Python interpreter. Restart ComfyUI after installation.

## VOSR2 Upscaling

`VOSR2_Image_Upscale` accepts exactly one connected ComfyUI image, uploads it, and sends only `model=vosr2-image-upscale` with a one-item `images` array to `POST /v1/image/generations`. It downloads the 4K result as a standard ComfyUI `IMAGE`.

`VOSR2_Video_Upscale` accepts either one connected ComfyUI video or one public URL, then sends only `model=vosr2-video-upscale` with `metadata.video_url` to `POST /v1/video/generations`. It downloads the 2K result as a standard ComfyUI `VIDEO`. Both nodes include `skip_error`, cache-only seed controls, resilient result downloads, concurrent submit wrappers, and credential-free example workflows.

## Motion Video

`Zhenzhen_Motion_Video` combines `zhenzhen/motion-video` and `zhenzhen/motion-video-pro` for Canvas 2D motion graphics, typography, intros and data stories, not live-action footage. Choose `generate` or `revise`.

Duration is 15/30/45/60 seconds, ratio is 16:9/9:16/1:1, and resolution is 720p/1080p. Select an API-default or one of ten documented templates; optional title, subtitle, keywords, signature, language and automatic music are omitted when blank/API-default. Keywords accept one item per line or a JSON string array.

`assets` accepts up to four persistent public HTTP(S) image URLs, one per line or a JSON string array. Local files and temporary upload links are not supported. Revision requires your own completed `revise_from` task ID and `revision_instruction`; connect the original node's `task_id` directly when chaining revisions. Inactive revision values are never submitted.

Only final success triggers downloading `content.video_url`; `preview_ready` is intermediate. Connect `video` to core Save Video. Optional cover, preview, HTML preview and subtitle URLs remain blank when absent; storyboard and fallback-scene values are JSON text. The seed is cache-only, never sent upstream. The generated submit wrapper uses the existing 10-slot video collector and `skip_error` policy.

When the upstream reports fallback scenes, the node preserves the completed video and logs a warning. Task success does not guarantee that every supplied image is used in the render.

Examples: [Standard](examples/MotionVideoStandard动效生成.json), [Pro](examples/MotionVideoPro动效生成.json), [Standard revision chain](examples/MotionVideoStandard成片修订.json), [Pro revision chain](examples/MotionVideoPro成片修订.json). Keys and runtime results are blank; revision task IDs are connected, not hardcoded.

Observed limitation: explicitly targeted scene-text revision took effect, but the reference image appeared as a geometric placeholder. Server-side `request_data.motion.assets` retained all four URLs and the storyboard included image instructions. Parameter delivery and video generation are verified; reference-image rendering is not. API-side asset loading/rendering still needs investigation. Default end-card edits also did not fully follow the instruction; target an explicit main-content scene when revising.

## Moss Image

`Moss_Image` uses exactly `moss-image`. A non-empty prompt is required. Leave `image1` disconnected for text generation or connect one local IMAGE for editing; the reference is uploaded as PNG. Image batches are rejected instead of silently selecting their first item.

`ratio` accepts 1:1, 2:3, 3:2, 3:4, 4:3, 9:16, 16:9, and 21:9, defaulting to 9:16, and maps to `metadata.ratio`. There are no custom resolution, batch-count, or output-format controls. The standard seed only controls ComfyUI caching and is never submitted to this model.

Four outputs retain the standard image/image_url/task_id/response contract. Resilient downloading, `skip_error`, and the existing 30-slot concurrent image collector remain available. Examples: [text generation](examples/moss-image文生图.json), [single-reference editing](examples/moss-image图像编辑.json). Keys are blank; core Load Image and Save Image handle input and saving.

## MAI Image 2.6 / Flash

Select either model in `MAI_Image_2_6`. Supply a non-empty prompt and optionally connect one image to each of `image1..image5`. References are uploaded as PNG in slot order; no references means text generation. Each task produces one PNG, with no mask or output-format parameters.

Text controls provide `resolution=1k|2k`, common `size` ratios, `auto`, `custom_ratio`, and `custom_pixels`. Custom ratios are positive integer W:H values between 1:4 and 4:1. Exact width/height require each side >=768 and total pixels <=2359296, rounded down to multiples of 32; pixel dimensions replace size/resolution. `auto_aspect_ratio=true` lets the model choose the ratio. Optional `web_grounding` uses Bing. Both booleans default to false.

Connected references determine output sizing upstream, so text-sizing controls are hidden and omitted from the request. The seed is cache-only. Standard error skipping and the shared 30-slot image concurrent collector remain available.

Examples: [standard text](examples/mai-image-2-6文生图.json), [standard edit](examples/mai-image-2-6图像编辑.json), [standard composition](examples/mai-image-2-6多图合成.json), [Flash text](examples/mai-image-2-6-flash文生图.json), [Flash edit](examples/mai-image-2-6-flash图像编辑.json), [Flash composition](examples/mai-image-2-6-flash多图合成.json).

## NB Pro / 2.1 Lowprice

`Zhenzhen_Image_NB_Lowprice` combines both Lowprice models. A 1-5000-character prompt is required; each task produces one image. Zero references means text generation, while up to 14 one-image sockets enable editing in slot order. Resolution supports 1k/2k/4k. Both models offer standard ratios plus `auto`; only 2.1 adds 1:4, 4:1, 1:8, and 8:1. Output-format and cache-seed fields are never submitted.

Progressive reference sockets preserve serialization indexes. Existing cache controls, error skipping, and the 30-slot image collector remain available. Examples: [Pro text](examples/zhenzhen-image-nb-pro-lowprice文生图.json), [Pro edit](examples/zhenzhen-image-nb-pro-lowprice图像编辑.json), [Pro composition](examples/zhenzhen-image-nb-pro-lowprice多图合成.json), [2.1 text](examples/zhenzhen-image-nb-2.1-lowprice文生图.json), [2.1 edit](examples/zhenzhen-image-nb-2.1-lowprice图像编辑.json), [2.1 composition](examples/zhenzhen-image-nb-2.1-lowprice多图合成.json).

## Doubao Voice Training / ICL 2.0

Select `doubao-voice-clone`, supply either one local AUDIO or public `audio_url`, and enter 4-300 preview characters. Encoded local WAV must not exceed 10 MB; remote samples are validated upstream, and raw PCM requires 24 kHz mono. Optional `custom_speaker_id` is 8-256 characters starting with an English letter; blank lets the service assign it. `reference_text` is at most 2000 characters, and language must match the sample. Advanced `training_speaker_id` maps to the provider's `metadata.speaker_id`, not the custom ID.

Training language codes include 0 for Chinese and 1 for English. `api_default` omits the language field; it does not promise automatic language detection. The node downloads the preview and returns `data.result_text` through `speaker`. Connect it to a second node's `speaker` input and select `doubao-seed-icl-2.0`, sharing the same account's API config. The standalone synthesis example needs an existing trained voice ID.

Synthesis supports 1-10000 characters, standard/expressive or API-default voice models, mp3/wav/pcm/ogg_opus, seven sample rates, and rate/loudness/pitch. Specified voice models omit `context_texts`; API-default mode allows up to 500 instruction characters. `advanced_mode` only expands controls: bitrate, timestamps, filters, silence, LaTeX, tone fidelity, and AIGC metadata. Optional booleans use `api_default` to omit or `enabled`/`disabled` to send true/false. LaTeX v2 requires Markdown filtering; bitrate 0 omits the field, and explicit values require 16000-160000.

Examples: [training](examples/doubao-voice-clone音色训练.json), [existing-voice synthesis](examples/doubao-seed-icl-2.0语音合成.json), [connected training and synthesis](examples/doubao音色训练到ICL语音合成.json). Core Save Audio saves and previews results. Seeds are cache-only; skipped failures return one second of silence and empty runtime fields.

## Topaz Video Restoration

`Topaz_Video_Upscale` accepts exactly one source: a connected `input_video` MP4 (up to 50 MB for upload), or an HTTP(S) `video_url`. Resolution is `720p / 1080p / 2K / 4K`, defaulting to `1080p`. The `model` control selects `Ultra / Max / High / Medium / Low`, defaults to `Max`, and maps to `metadata.quality`; the API model remains exactly `Topaz-Upscale-LowPirce`.

Submission and polling use `/v1/video/generations`. The payload contains a one-item `metadata.video_url` array, resolution, and quality only. No prompt, duration, aspect ratio, or cache seed is submitted. Output pixel budgets preserve the source aspect ratio.

The node includes `skip_error`, standard cache seeds, resilient downloads, and the existing 10-slot video concurrent collector. Examples: [local MP4](examples/Topaz视频高清修复本地素材.json), [public URL](examples/Topaz视频高清修复网址素材.json).

## Zhenzhen Image G v2.5

`Zhenzhen_Image_G25_Lowprice` exposes only its documented contract: required prompt, `1k|2k|4k`, a fixed aspect-ratio selector, optional `nsfw_check`, `n=1`, and up to 15 connected reference images.

`Zhenzhen_Image_G25_Official` combines Flare and Sunburst. It supports up to 16 connected references, `n=1..4`, `1k|2k|4k`, quality, PNG/JPEG/WebP, background and moderation controls, plus exact `WIDTHxHEIGHT` sizing. Exact sizes use multiples of 16, each edge at most 3840 pixels, a maximum 3:1 aspect ratio, and 655360-8294400 total pixels. Selecting `preserve_reference` omits `size`; PNG omits compression; transparent backgrounds require PNG or WebP.

Both nodes submit and poll `/v1/image/generations`, return all downloaded results as a ComfyUI IMAGE batch, preserve the existing shared download recovery, and provide serial plus 30-way concurrent submit paths.

## MiniMax-H3 V2

The independent `Minimax_H3_V2_Video` node uses `POST /v2/video_generation`, polls `GET /v2/query/video_generation/{task_id}`, and downloads the successful `task.content.url`. The case-sensitive model name is fixed to `MiniMax-H3`.

It accepts required text, 480P/768P output, fixed or keyframe-adaptive ratios, optional first/last frames, up to nine reference images, three reference videos with per-video start offsets, three reference audios, and one separate drive audio. Normal requests support 4-15 seconds; drive-audio requests support 4-60 seconds. The node also provides `skip_error`, a cache-only ComfyUI seed, a 10-way video submit wrapper, and four credential-free example workflows.

## API Key Setup

Create an API key from [api.seedance.nz/console](https://api.seedance.nz/console), then use one of the following methods.

### Option 1: Configuration Node

Add `Seedance API Config` and set:

- `base_url`: `https://api.seedance.nz`
- `api_key`: your API key

Connect its `api_config` output to generation nodes.

### Option 2: Environment Variable

Windows CMD:

```cmd
set SEEDANCE_API_KEY=your_api_key_here
```

PowerShell:

```powershell
$env:SEEDANCE_API_KEY = "your_api_key_here"
```

macOS or Linux:

```bash
export SEEDANCE_API_KEY=your_api_key_here
```

Start ComfyUI from the same environment.

### Option 3: Local `.env`

Create `config/.env` inside the plugin directory:

```env
SEEDANCE_API_KEY=your_api_key_here
SEEDANCE_BASE_URL=https://api.seedance.nz
```

This file is ignored by Git.

## Quick Start

1. Add `Seedance API Config` and enter your API key.
2. Add a generation node such as `Seedance_TextToVideo`, `Seedance_ImageToVideo`, `Seedance_MultimodalVideo`, or a model-family node.
3. Select the model and configure the visible duration, resolution, ratio, and media inputs.
4. Queue the workflow.
5. Connect the downloaded `VIDEO`, `IMAGE`, `AUDIO`, or GLB output to the appropriate preview/save node.

### Wan 3.0

- I2V models require `image1` as the first frame and accept `image2` as an optional last frame.
- R2V models require a prompt and accept up to 10 images, 5 videos, and 5 audio inputs.
- R2V may also use either `file_url` or `link_url`, but not both.
- Only standard global models expose `enable_thinking`; standard Global R2V enables it automatically for file or web references. Prime global models omit it.
- Supported duration values are `auto` or 2-30 seconds. Resolutions are `480P`, `720P`, and `1080P`.

### Concurrent Image and Video Generation

1. Add multiple nodes whose names begin with `Concurrent Submit |`.
2. Connect image futures to the 30-slot image await node or video futures to the 10-slot video await node.
3. Connect each future to `future_1`, `future_2`, and so on.
4. The await node runs tasks concurrently and restores result order by input slot.
5. Use `failure_mode=raise` for strict behavior or `placeholder` to preserve successful siblings.

Different submit node families can share the same media-type await node. For example, Seedream, Qwen Image, and Zhenzhen Image futures may be mixed in one image await node. The original serial nodes remain available, and existing workflows require no migration.

Worker limits can be reduced with `SEEDANCE_IMAGE_CONCURRENCY` and `SEEDANCE_VIDEO_CONCURRENCY`. These settings do not change the fixed 30-image and 10-video socket contracts.

## Seeds and ComfyUI Caching

Generation and processing nodes expose a standard `seed` widget with ComfyUI's control-after-generate selector:

- `fixed`: unchanged inputs reuse a completed cached result.
- `randomize`: choose a new seed after generation.
- `increment`: increase the seed after generation.
- `decrement`: decrease the seed after generation.

Native model seeds are sent only when supported by the selected API model. Other nodes use a cache-only seed that changes ComfyUI execution caching without modifying the request payload.

## Dynamic Inputs

Model and operation selectors update the node UI automatically:

- T2V modes hide media inputs.
- I2V modes show required and optional frame inputs.
- Multimodal modes progressively reveal image, video, and audio sockets as they are connected.
- Suno, Flow Music, and Midjourney show only fields accepted by the selected operation.
- Connected hidden inputs are preserved when loading existing workflows.

### Suno V6 Actions

- `suno-create-model` accepts 6-24 local audio inputs or public audio URLs and exposes the completed `model_id` as a connectable output.
- `suno-upload-cover` and `suno-upload-extend` accept one local audio input or public URL and support `v6`, `v6-wild`, and `v6-mini`.
- The node omits `version` when `custom_model_id` is connected and rejects the documented `custom_model_id`/`persona_id` conflict before submission.
- V6 controls include mode-specific prompt fields, style weights, target duration, variety, Max mode, and MP3/M4A/WAV output selection.
- Three matching example workflows keep the API key and all runtime values empty.
- All three paths completed real node-level verification. The full offline suite passes 433 tests, and all 204 workflows pass JSON and credential/runtime-value checks.

## Outputs

Common video outputs:

| Output | Description |
| --- | --- |
| `video` | Downloaded ComfyUI `VIDEO` output |
| `video_url` | Temporary result URL returned by the API |
| `task_id` | Asynchronous task identifier |
| `response` | Formatted task response |

Common image outputs:

| Output | Description |
| --- | --- |
| `image` | Downloaded ComfyUI `IMAGE` output |
| `image_url` | Temporary result URL returned by the API |
| `task_id` | Asynchronous task identifier |
| `response` | Formatted task response |

Common audio outputs:

| Output | Description |
| --- | --- |
| `audio` | Downloaded and decoded ComfyUI `AUDIO` output |
| `audio_url` | Temporary result URL returned by the API |
| `audio_path` | Local output path |
| `task_id` | Asynchronous task identifier |
| `response` | Formatted task response |

Specialized nodes may expose multiple images, videos, audio tracks, masks, text, local paths, operation buttons, or native `FILE_3D_GLB` outputs.

## Nano Banana 2.1

The independent NB 2.1 node uses `zhenzhen-image-nb-2.1` and the shared `/v1/image/generations` submit/poll/download path. Prompt length is 5-5000 characters. Choose `1k` (default), `2k`, or `4k`, and `auto` or one of ten standard aspect ratios (default `1:1`). No reference images means text generation; connect up to 14 ordered single-image references for editing. Each request generates exactly one image and omits all output-format fields.

The existing four-model NB node remains unchanged. NB 2.1 supports standard cache-only seeds, default-off `skip_error`, resilient downloads, and the optional 30-way image concurrent submit wrapper.

## FLUX 3 Image and Vidu Q4

FLUX requires a non-empty prompt and accepts up to ten ordered local images. Resolution is `768sq`, `1k` (default), `1.5k`, `2k`, or `4k`. Select `auto` or one of 15 fixed aspect ratios; `grounding` defaults to true and `safety_tolerance` accepts 0-4 (default 2). The request uses `/v1/image/generations` and produces one IMAGE result.

Vidu Q4 keeps domestic/global I2V and R2V in one independent node. I2V requires exactly `image1` and allows an empty prompt. R2V requires a prompt and 1-15 images, optionally with up to three local AUDIO inputs or public MP3 URLs. Choose only one source per audio slot. Local audio requires FFmpeg, optionally configured with `SEEDANCE_FFMPEG`.

Vidu supports 3-16 seconds (default 5) and `540p`, `720p` (default), `1080p`, `2k`, or `4k`. Only R2V submits a ratio: `16:9` (default), `9:16`, `1:1`, `4:3`, or `3:4`. `generate_audio` and `is_rec` default to true; `watermark` defaults to false. The node uses `/v1/video/generations`, not Q3's request contract. Both new nodes use cache-only seeds and do not send undocumented seed fields to the API.

## Example Workflows

The [`examples`](examples) directory contains safe workflows with empty API key fields and no saved runtime results. It includes:

- Seedance 2.0 and Seedance 2.5 T2V/I2V/Multi workflows.
- Eight Wan 3.0 standard/Prime domestic/global I2V/R2V workflows.
- Four Omni 1.1 Flash Lowprice workflows covering text, first-frame, reference-image, and reference-video generation.
- FLUX 3, Hailuo H3/H3 Max, MiniMax H3, Kling, Vidu, HappyHorse, and Zhenzhen Video workflows.
- `flux-3-image*.json`: two FLUX image generation/editing workflows.
- `vidu-q4-preview*.json`: four domestic/global I2V and image-plus-audio R2V workflows.
- `zhenzhen-image-nb-2.1*.json`: independent NB 2.1 text generation and local-image editing workflows.
- Seedream Pro/Flash, Qwen Image, Zhenzhen Image including six G v2.5 generation/editing examples, Midjourney, segmentation, region-editing, and layer-decomposition workflows.
- Hunyuan 3D preview/save workflows.
- Doubao, Qwen3 TTS, MiniMax Audio, Mureka, Whisper, Suno, and Flow Music workflows.
- Serial and concurrent generation examples.

## Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `SEEDANCE_API_KEY` | empty | API key used when no configuration node is connected |
| `SEEDANCE_BASE_URL` | `https://api.seedance.nz` | API gateway base URL |
| `SEEDANCE_POLL_INTERVAL` | `4` | Polling interval in seconds |
| `SEEDANCE_MAX_POLL_TIME` | `1800` | Maximum polling duration in seconds |
| `SEEDANCE_TIMEOUT` | `60` | Task submission request timeout |
| `SEEDANCE_UPLOAD_TIMEOUT` | `180` | Media upload timeout |
| `SEEDANCE_CA_BUNDLE` | empty | Optional custom CA bundle path |
| `SEEDANCE_FFMPEG` | auto | Optional FFmpeg executable path |
| `SEEDANCE_CURL` | auto | Optional system curl executable path |
| `SEEDANCE_SSL_VERIFY` | `1` | Set to `0` only for temporary TLS troubleshooting |
| `SEEDANCE_IMAGE_CONCURRENCY` | `30` | Image worker count from 1 to 30 |
| `SEEDANCE_VIDEO_CONCURRENCY` | `10` | Video worker count from 1 to 10 |

Generated-result size limits can also be adjusted with `SEEDANCE_IMAGE_MAX_MIB`, `SEEDANCE_AUDIO_MAX_MIB`, `SEEDANCE_FILE_MAX_MIB`, and `SEEDANCE_VIDEO_MAX_MIB`.

## Reliability

- Task creation avoids replaying ambiguous requests that may already have reached the upstream provider.
- Polling tolerates temporary network, response, and JSON failures.
- Media downloads use streaming reads, browser-compatible headers, integrity checks, and media-specific limits.
- Failed direct downloads retry without environment proxy settings and can fall back to system curl.
- File downloads use atomic temporary files and remove partial results after failure.
- Video results require a valid MP4 `ftyp` header; audio must decode successfully before returning.
- Each worker thread owns its HTTP session, preventing mutable session state from crossing concurrent tasks.
- `skip_error=true` returns contract-compatible placeholders so later batch items can continue.

## Troubleshooting

### Nodes Do Not Appear

Confirm the plugin path is:

```text
ComfyUI/custom_nodes/ComfyUI_Seedance
```

Install dependencies and restart ComfyUI.

### Missing API Key

Connect `Seedance API Config`, set `SEEDANCE_API_KEY`, or create `config/.env`.

### TLS Certificate Errors

The plugin does not require `truststore`. It uses Requests certificate verification and can read the Windows ROOT/CA store for portable Python environments.

First update the networking packages in ComfyUI's Python environment:

```bash
python -m pip install -U requests certifi
```

You may also point `SEEDANCE_CA_BUNDLE` to a custom CA bundle. `SEEDANCE_SSL_VERIFY=0` is a temporary compatibility option and should not be used as a permanent configuration.

### `native1080p` or `native4k` Is Rejected

Seedance 2.0 requires a Standard model for `native1080p` or `native4k`. Seedance 2.5 Standard supports `native1080p` but not `native4k`. Select a documented resolution for the active model.

### Multimodal Uploads Start Slowly

Large or numerous local media inputs must finish uploading before generation begins. The plugin reports upload progress and retries temporary upload failures.

### Generated Media Is Visible Remotely but Not in ComfyUI

Result delivery may be slower on some networks. The plugin uses direct, no-proxy, and system download paths with a 60-second read timeout and media-specific total limits. Check the ComfyUI console for sanitized transport diagnostics.

## Security and Data Handling

- Prompts and connected reference media are sent to the configured API endpoint.
- Never place API keys in public workflows or commits.
- Example workflows keep API keys and runtime fields empty.
- Temporary result URLs may expire; save important outputs locally.
- Runtime task identifiers, signed URLs, and generated media are not stored in this repository.

## Links

- [Chinese README (Default)](README.md)
- [API Documentation](https://api.seedance.nz/docs/)
- [GitHub Repository](https://github.com/T8mars/ComfyUI_Seedance)
- [Issue Tracker](https://github.com/T8mars/ComfyUI_Seedance/issues)
