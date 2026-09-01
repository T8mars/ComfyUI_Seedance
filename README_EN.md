# ComfyUI_Seedance

**Language: [Simplified Chinese (Default)](README.md) | English**

ComfyUI nodes for video, image, audio, speech, music, and 3D generation through [api.seedance.nz](https://api.seedance.nz). The plugin supports local ComfyUI media inputs, asynchronous task polling, resilient result downloads, standard seed controls, error skipping, and optional concurrent execution.

## API Access

| Service | Audience | Open |
| --- | --- | --- |
| Seedance NZ | Domestic model workflows | <a href="https://api.seedance.nz/sign-up?aff=5f4w"><kbd>Open Seedance NZ</kbd></a> |
| T8star AI | Overseas model workflows | <a href="https://ai.t8star.org/register?aff=dP7j"><kbd>Open T8star AI</kbd></a> |
| RunningHub China | Domestic RunningHub API access | <a href="https://www.runninghub.cn/user-center/1819214514410942465/webapp?inviteCode=rh-v1121"><kbd>Open RunningHub China</kbd></a> |
| RunningHub Global | Overseas RunningHub API access | <a href="https://www.runninghub.ai/user-center/1907375370302308353/webapp?inviteCode=rh-v1121"><kbd>Open RunningHub Global</kbd></a> |

## Current Release

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
- MiniMax H3 OW and H3 OW Fast
- Vidu Q3
- Zhenzhen Video G, GK, and V3.1
- Midjourney video
- FlashVSR and Zhenzhen Upscaler

### Image and 3D

- Seedream v5 Pro and Dola Seedream 5.0 Pro
- Seedream layer decomposition
- Qwen Image 3.0 and Pro
- Zhenzhen Image G, GK v1.5, GK v2, and Nano Banana
- Wan 2.7 global image generation/editing
- Midjourney image generation and editing
- Hunyuan 3D v3.1

### Audio, Speech, and Music

- Doubao Seed Audio 1.0
- Qwen3 TTS
- MiniMax music, speech, and voice clone
- Mureka BGM
- Whisper 1 transcription
- Suno multi-action music workflows
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
| `Hailuo_H3_Max_Video` | Hailuo H3 Max T2V and first/optional-last-frame I2V |
| `Flux_3_Video` | FLUX 3 domestic/global T2V, I2V, V2V, and draft enhancement |
| `Minimax_H3_OW_Video` | MiniMax H3 OW T2V, I2V, and R2V |
| `Minimax_H3_OW_Fast_Video` | MiniMax H3 OW Fast video and audio-driven modes |
| `Minimax_H3_Context_IR` | Text, frame, or multimodal video prompt enhancement |
| `Vidu_Q3_Video` | Vidu Q3 T2V, I2V, start/end, and reference video |
| `Vidu_Q3_ShortPlay` | Vidu Q3 short-play generation |
| `Zhenzhen_Video_G_Omni_Flash` | Zhenzhen Video G Omni Flash |
| `Zhenzhen_Video_G_Omni_Flash_Lowprice` | Omni Flash Lowprice text, first-frame, reference-image, and reference-video generation |
| `Zhenzhen_Video_G_Omni_1_1_Flash_Lowprice` | Omni 1.1 Flash Lowprice text, first-frame, reference-image, and reference-video generation |
| `Zhenzhen_Video_GK_V15` | Zhenzhen Video GK v1.5 |
| `Zhenzhen_Video_V31` | Zhenzhen Video V3.1 Fast, Quality, and Lite |
| `FashVSR_Video_Upscale` | FlashVSR 480P video upscaling |
| `Zhenzhen_Upscaler_Video` | Zhenzhen video upscaling |
| `Seedream_V5_Pro_Image` | Seedream/Dola Seedream generation and editing |
| `Seedream_V5_Pro_Layer_Decomposition` | Seedream/Dola layer decomposition |
| `Qwen_Image_3_0` | Qwen Image 3.0/Pro generation and editing |
| `Zhenzhen_Image_G2` | Zhenzhen Image G generation and editing |
| `Zhenzhen_Image_GK_V15` | Zhenzhen Image GK v1.5 generation and editing |
| `Zhenzhen_Image_GK_V2` | Zhenzhen Image GK v2 text-to-image |
| `Zhenzhen_Image_GK_V2_Edit` | Zhenzhen Image GK v2 one-to-three-image editing |
| `Zhenzhen_Image_GK_V2_Segment` | Zhenzhen Image GK v2 segmentation |
| `Zhenzhen_Image_GK_V2_Region_Edit` | Zhenzhen Image GK v2 region editing |
| `Zhenzhen_Image_NB` | Zhenzhen Nano Banana generation and editing |
| `Wan_2_7_Global_Image` | Wan 2.7 global image generation and editing |
| `Hunyuan3D_V3_1` | Hunyuan 3D text or ordered multi-view image generation |
| `Doubao_Seed_Audio` | Doubao Seed Audio generation |
| `Qwen3_TTS` | Qwen3 text-to-speech |
| `Minimax_Audio` | MiniMax music, speech, and voice clone |
| `Mureka_BGM` | Mureka background music generation |
| `Whisper_Transcription` | Whisper transcription |
| `Suno_Music` | Suno multi-action music node |
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

## Example Workflows

The [`examples`](examples) directory contains safe workflows with empty API key fields and no saved runtime results. It includes:

- Seedance 2.0 and Seedance 2.5 T2V/I2V/Multi workflows.
- Eight Wan 3.0 standard/Prime domestic/global I2V/R2V workflows.
- Four Omni 1.1 Flash Lowprice workflows covering text, first-frame, reference-image, and reference-video generation.
- FLUX 3, Hailuo H3/H3 Max, MiniMax H3, Kling, Vidu, HappyHorse, and Zhenzhen Video workflows.
- Seedream, Qwen Image, Zhenzhen Image, Midjourney, segmentation, region-editing, and layer-decomposition workflows.
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
