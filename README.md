# ComfyUI_Seedance

## 入口导航

| 入口 | 适合用户 | 说明 | 打开 |
| --- | --- | --- | --- |
| 贞贞的平价AI小铺（国内版） | 国内用户、国内模型优先 | 主要调用国内模型，非盈利站点，仅保留 5-10% 网站维护费用；国内模型价格约为海外版的 7.5-8 折。 | <a href="https://api.seedance.nz/sign-up?aff=5f4w"><kbd>进入国内版平价AI小铺</kbd></a> |
| 贞贞的AI工坊（海外版） | 海外用户、海外模型优先 | 主要调用海外模型，也包含国内模型；整体成本更高，国内模型价格没有国内版优势。 | <a href="https://ai.t8star.org/register?aff=dP7j"><kbd>进入海外版AI工坊</kbd></a> |
| RunningHub APIKEY（国内版） | 需要适配更多 AI 应用的国内用户 | 适配更多 AI 应用，并可体验最新模型。 | <a href="https://www.runninghub.cn/user-center/1819214514410942465/webapp?inviteCode=rh-v1121"><kbd>获取国内版 APIKEY</kbd></a> |
| RunningHub APIKEY（海外版） | 海外模型、更宽松审核场景 | 审核更宽松，支持海外模型。 | <a href="https://www.runninghub.ai/user-center/1907375370302308353/webapp?inviteCode=rh-v1121"><kbd>获取海外版 APIKEY</kbd></a> |

# 👋🏻 Welcome to 贞贞的平价AI小屋

<img src="https://github.com/T8mars/Comfyui-zhenzhen/blob/main/pic/1.png" width="30%" alt="My favorite girl">
My favorite girl Go YounJung

# 网站价格和宗旨：

本站开设初衷是提供平价的API给粉丝朋友玩最新的海外模型，并非盈利目的，秉承这一理念，我们的价格毛利不到10%，去掉正常缴税和人工开发维护，服务器成本后几乎没有利润，所以并非盈利性质网站，没有任何议价空间，也不支持用于商业目的的二次开发，仅服务于粉丝朋友，望理解，每个月发票数量有限，需要自己承担所有税费5%

Seedance 2.0 视频生成与 Seedream 图片生成 API 的 ComfyUI 节点插件，默认接入 [api.seedance.nz](https://api.seedance.nz)。

本插件提供文生视频、图生视频、多模态视频，以及 Seedream v5 Pro 文生图/图像编辑节点。图片、视频、音频参考素材会自动上传到 API，不需要额外准备图床或外链。

## 功能特点

- 支持文生视频、图生视频、多模态视频
- 支持 Seedream v5 Pro 文生图和图像编辑
- 图像编辑支持 1 到 10 张参考图
- 内置 18 个 Seedance 2.0 模型变体
- 支持国内线路和 `global` 海外线路
- 支持 `standard`、`fast`、`mini` 三档模型
- 自动上传 IMAGE、VIDEO、AUDIO 参考素材
- 生成过程中显示 ComfyUI 进度条
- 生成完成后自动下载结果视频并输出为 `VIDEO`
- 支持 `skip_error`，批量工作流失败时可返回占位错误视频
- API key 可来自配置节点、环境变量或本地 `config/.env`

## 节点列表

| 节点 | 用途 | 主要输入 |
| --- | --- | --- |
| `Seedance API Config` | API 连接配置 | `base_url`、`api_key` |
| `Seedance 文生视频 (Text to Video)` | 纯文本生成视频 | `model`、`prompt`、时长、分辨率、比例 |
| `Seedance 图生视频 (Image to Video)` | 首帧图生成视频，可选尾帧图 | `first_image`、可选 `last_image`、`prompt` |
| `Seedance 多模态视频 (Multimodal Video)` | 图片、视频、音频混合参考生成视频 | 最多 9 张图、3 个视频、3 段音频 |
| `Seedream v5 Pro 图像生成/编辑` | 无参考图时使用 `seedream-v5-pro-t2i`，有参考图时使用 `seedream-v5-pro-i2i` | `prompt`、分辨率、输出格式、可选参考图 |

视频生成节点输出：

| 输出 | 说明 |
| --- | --- |
| `video` | 已下载到本地的结果视频，可继续连接保存或预览节点 |
| `video_url` | API 返回的视频直链 |
| `task_id` | 远端任务 ID |
| `response` | 完整 JSON 响应文本 |

图片节点输出：

| 输出 | 说明 |
| --- | --- |
| `image` | 已下载并转换为 ComfyUI `IMAGE` 的结果，可连接预览或保存节点 |
| `image_url` | API 返回的临时图片直链 |
| `task_id` | 远端图片任务 ID |
| `response` | 完整 JSON 响应文本 |

## 安装

进入 ComfyUI 的 `custom_nodes` 目录并克隆插件：

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/T8mars/ComfyUI_Seedance.git
```

使用 ComfyUI 对应的 Python 安装依赖：

```bash
cd ComfyUI
python -m pip install -r custom_nodes/ComfyUI_Seedance/requirements.txt
```

如果你使用的是 ComfyUI 便携包，请用便携包自带的 Python 执行安装命令。安装完成后重启 ComfyUI，节点会出现在 `Seedance` 分类下。

## API Key 配置

在 [api.seedance.nz/console](https://api.seedance.nz/console) 创建 API 令牌后，任选一种方式配置。

### 方式一：配置节点

添加 `Seedance API Config` 节点：

- `base_url`: `https://api.seedance.nz`
- `api_key`: 你的 API 令牌

然后把它的 `api_config` 输出连接到生成节点。

### 方式二：环境变量

Windows CMD：

```cmd
set SEEDANCE_API_KEY=your_api_key_here
```

PowerShell：

```powershell
$env:SEEDANCE_API_KEY = "your_api_key_here"
```

macOS / Linux：

```bash
export SEEDANCE_API_KEY=your_api_key_here
```

设置后再启动 ComfyUI。

### 方式三：本地 `.env`

在插件目录下创建 `config/.env`：

```env
SEEDANCE_API_KEY=your_api_key_here
SEEDANCE_BASE_URL=https://api.seedance.nz
```

`config/.env` 已被 `.gitignore` 忽略，适合本机长期使用。

## 快速开始

1. 添加 `Seedance API Config`，填写 API key。
2. 添加一个生成节点：
   - `Seedance 文生视频 (Text to Video)`：只用文本生成视频
   - `Seedance 图生视频 (Image to Video)`：用首帧图、可选尾帧图生成视频
   - `Seedance 多模态视频 (Multimodal Video)`：混合图片、视频、音频参考
3. 选择 `model`，设置 `seconds`、`resolution`、`ratio`。
4. 运行工作流。
5. 将 `video` 输出连接到 `SaveVideo` 或其他视频节点。

图片生成或编辑：

1. 添加 `Seedream v5 Pro 图像生成/编辑`。
2. 填写 5 到 2000 字符的 `prompt`。
3. 不连接参考图时执行文生图；连接 `image1` 到 `image10` 中任意参考图时执行图像编辑。
4. 选择 `1k`、`2k`，或选择 `custom` 后设置 `width` 和 `height`。
5. 将 `image` 输出连接到 `Preview Image` 或 `Save Image`。

示例工作流位于：

- `examples/seedance_text_to_video.json`
- `examples/seedance_image_to_video.json`
- `examples/seedance_multimodal_video.json`

可以直接把 JSON 文件拖进 ComfyUI 加载。

## 模型选择

每个生成节点提供 6 个对应任务类型的模型：

| 档位 | 国内线路 | 海外线路 |
| --- | --- | --- |
| Standard | `seedance-2.0-standard-*` | `seedance-2.0-global-standard-*` |
| Fast | `seedance-2.0-fast-*` | `seedance-2.0-global-fast-*` |
| Mini | `seedance-2.0-mini-*` | `seedance-2.0-global-mini-*` |

`*` 由节点类型决定：

- `t2v`：文生视频
- `i2v`：图生视频
- `multi`：多模态视频

图片节点不连接参考图时提交 `seedream-v5-pro-t2i`，连接参考图时提交 `seedream-v5-pro-i2i`。图片请求使用独立的 `/v1/image/generations` 端点，不会改写或复用现有 Seedance 视频模型名。

建议第一次测试先用 `mini` 档、短时长、低分辨率，确认效果和成本后再切换高规格模型。

## 参数说明

| 参数 | 说明 |
| --- | --- |
| `model` | 当前任务类型下的 Seedance 模型 |
| `prompt` | 提示词，最多 20480 字符 |
| `seconds` | 视频时长，4 到 15 秒；`-1` 表示由模型决定 |
| `resolution` | `480p`、`720p`、`1080p`、`2k`、`4k`、`native1080p`、`native4k` |
| `ratio` | `adaptive`、`16:9`、`4:3`、`1:1`、`3:4`、`9:16`、`21:9` |
| `generate_audio` | 是否生成配音、音效或音频 |
| `seed` | `-1` 为随机种子；非负整数会透传给模型 |
| `api_config` | 可选，连接 `Seedance API Config` 节点 |
| `skip_error` | 开启后失败时返回占位错误视频，而不是中断整个工作流 |

`native1080p` 和 `native4k` 仅支持 Standard 档模型，插件会在提交前校验。

`1080p`、`2k`、`4k` 属于从 720p 超分的输出档位，可能产生额外按秒计费。

图片节点参数：

| 参数 | 说明 |
| --- | --- |
| `prompt` | 必填，5 到 2000 字符 |
| `resolution` | `1k`、`2k` 或 `custom`；选择预设时 API 会忽略宽高 |
| `width` / `height` | 仅 `custom` 时提交，范围 240 到 8192 |
| `output_format` | `png` 或 `jpeg` |
| `image1` ... `image10` | 可选参考图；未连接时文生图，连接后图像编辑 |
| `api_config` | 可选，复用 `Seedance API Config` 的地址与 API key |

## 多模态提示词

多模态节点支持：

- 最多 9 张图片
- 最多 3 个视频
- 最多 3 段音频

至少需要连接 1 个参考素材。

在提示词中使用下面的写法引用素材：

- `@Image 1`
- `@Video 1`
- `@Audio 1`

素材编号按连接的输入槽位顺序生成。如果连接了 `image1` 和 `image3`，但跳过 `image2`，插件会自动压缩编号为 `@Image 1`、`@Image 2`，并在控制台输出提示。

参考视频建议使用 MP4，单个文件不超过 50 MB。音频参考也建议控制在 50 MB 以内。

## 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `SEEDANCE_API_KEY` | 空 | 未连接配置节点时使用的 API 令牌 |
| `SEEDANCE_BASE_URL` | `https://api.seedance.nz` | API 网关地址 |
| `SEEDANCE_POLL_INTERVAL` | `4` | 轮询间隔，单位秒 |
| `SEEDANCE_MAX_POLL_TIME` | `1800` | 最大轮询时间，单位秒 |
| `SEEDANCE_TIMEOUT` | `60` | 提交任务请求超时，单位秒 |
| `SEEDANCE_UPLOAD_TIMEOUT` | `180` | 上传素材请求超时，单位秒 |
| `SEEDANCE_SSL_VERIFY` | `1` | 设为 `0` 可关闭 SSL 校验，仅建议临时排障使用 |

## 稳定性策略

- 提交任务时，网络错误、HTTP 429、HTTP 5xx 会自动重试。
- 参数错误、鉴权失败等业务错误会立即失败，不重复扣请求。
- 轮询任务时，会容忍短暂网络错误、非 200 响应和 JSON 解析失败。
- 上传素材遇到 API 限流时，会等待后继续重试。
- 下载结果视频失败时会自动重试。
- 图片任务使用独立状态规则轮询：`SUCCESS` 成功、`FAILURE` 失败，并自动下载临时结果直链。
- 下载图片失败时会自动重试，成功后返回标准 ComfyUI `IMAGE` 张量。
- `skip_error=True` 时会生成一个错误占位视频，方便批量流程继续往下跑。

## 常见问题

### 节点没有出现

确认插件路径是：

```text
ComfyUI/custom_nodes/ComfyUI_Seedance
```

安装依赖后需要重启 ComfyUI。

### 提示缺少 API key

请连接 `Seedance API Config`，或设置 `SEEDANCE_API_KEY`，或创建 `config/.env`。

### SSL 证书错误

先尝试在 ComfyUI 使用的 Python 环境中安装 `truststore`：

```bash
python -m pip install truststore
```

如果仍然无法连接，可以临时设置 `SEEDANCE_SSL_VERIFY=0` 跳过 SSL 校验。

### `native1080p` 或 `native4k` 被拒绝

请切换到 Standard 档模型，或改用 `480p`、`720p`、`1080p`、`2k`、`4k`。

### 多模态上传很慢

API 可能对单个令牌的上传频率限流。插件会自动等待和重试，大素材或多素材工作流开始生成前会更慢一些。

## 注意事项

- 本插件会把提示词和连接的参考素材发送到配置的 Seedance API endpoint。
- 远端 API 调用可能产生费用，请先用 `mini` 档和短时长测试。
- 结果直链可能有有效期，重要结果请及时保存。
- 不要把 API key 写进公开工作流或提交到仓库。
