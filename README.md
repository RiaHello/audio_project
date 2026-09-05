# 语音约碰面地点

按住说话，找出同一座城市里两个人之间的碰面地点。当前版本包含健康检查、本地录音、上传和语音识别。前端尚未调用 `/asr`。

## 环境

- Python 3.11
- Node.js 22.12 及以上的 22.x
- 后端端口 `8003`，前端端口 `5175`
- 本机需安装 FFmpeg（提供 `ffprobe`）。后端用它探测真实容器、编码和时长，不转码。Chrome 的 WebM 常缺少 Duration 元数据，`ffprobe` 可从音频流或 packet 时间戳读取时长。

macOS 安装（请自行执行，不要跳过）：

```bash
brew install ffmpeg
ffprobe -version
```

## 配置

```bash
cp backend/.env.example backend/.env
```

外部服务密钥可先留空。健康检查不调用百炼、DeepSeek 或高德。

## 启动后端

```bash
cd backend
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --host 127.0.0.1 --port 8003
```

若本机开启了 SOCKS 代理（Clash / V2Ray 等），需要 `httpx[socks]`。依赖清单已包含该项；若启动过旧环境，请重新执行上面的 `pip install -r requirements.txt` 后再启动。
```

接口文档：<http://localhost:8003/docs>  
健康检查：<http://localhost:8003/health>

## 启动前端

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

页面：<http://localhost:5175>

## 如何验证录音

前端需已启动。建议使用支持 WebM/Opus 的 Chrome 或 Edge。本轮不调用上传或其他业务接口。

1. 打开 <http://localhost:5175>，确认城市默认为「杭州」，可修改。
2. 按住「按住说话」，允许麦克风；按钮应变为「松开结束」，并显示秒数。
3. 松开后出现试听播放器和「下载录音文件」。页面会显示 MIME 类型、大小和时长。
4. 点一下松开（不足 1 秒）应提示时长不合规，不生成可下载文件。
5. 录音中按 Esc 或点「取消录音」，应回到未完成状态并释放麦克风（浏览器麦克风图标消失）。
6. 按住后把指针移出按钮再松开，也应结束录音并释放麦克风。
7. 按住直到 60 秒，应自动结束并保留录音。

下载后检查格式、大小和时长（将路径换成你的下载文件）：

```bash
ls -lh ~/Downloads/meetup-recording-*.webm

ffprobe -v error -show_entries format=format_name,filename,size,duration \
  -show_entries stream=codec_name,codec_type,codec_mime \
  -of default=nw=1 \
  ~/Downloads/meetup-recording-*.webm
```

Chrome 的 WebM 常常没有容器级 Duration。若 `duration=N/A`，不要当成文件损坏，可改用数据包时间戳：

```bash
ffprobe -v error -select_streams a:0 \
  -show_entries packet=pts_time \
  -of csv=p=0 \
  ~/Downloads/meetup-recording-*.webm | tail -n 1
```

预期：容器为 `webm`/`matroska`，音频编码为 `opus`，大小不超过 5MB，时长大约在 1–60 秒（与页面显示接近）。

## 如何验证 POST /upload

后端改代码后需重启 `uvicorn`。先确认 `ffprobe` 可用。本轮未接前端，请用 `/docs` 或 curl。

1. 打开 <http://localhost:8003/docs>
2. 找到 `POST /upload`，点 Try it out
3. 在 `file` 选择上一轮下载的 `meetup-recording-*.webm`
4. Execute

或：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@$HOME/Downloads/meetup-recording-XXXX.webm;type=audio/webm"
```

把文件名换成你的下载文件。

### 正常上传

- 状态码：`200`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "data": {
    "audio_id": "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
  }
}
```

`audio_id` 是 UUID，不是路径。录音保存在 `backend/storage/audio/<audio_id>/recording.webm`，同目录 `meta.json` 含 `created_at`（UTC），供之后 24 小时过期校验使用。

### 格式不支持

上传任意非 WebM/Opus 文件，例如一个 `.txt` 或 `.mp3`：

```bash
echo 'not audio' > /tmp/not-audio.txt
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/not-audio.txt;type=text/plain"
```

- 状态码：`415`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "UNSUPPORTED_MEDIA_TYPE",
    "message": "仅支持 WebM/Opus 录音，请更换浏览器后重试。",
    "stage": "upload"
  }
}
```

### 文件过大

大小校验在格式探测之前，可用大于 5MB 的任意文件：

```bash
dd if=/dev/zero of=/tmp/huge.webm bs=1048576 count=6
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/huge.webm;type=audio/webm"
```

- 状态码：`413`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "FILE_TOO_LARGE",
    "message": "录音文件超过 5MB，请缩短录音后重试。",
    "stage": "upload"
  }
}
```

### 时长不合规

需要真实的 WebM/Opus，否则会先变成 415。若已安装 ffmpeg：

```bash
ffmpeg -y -f lavfi -i anullsrc=r=48000:cl=mono -t 0.5 -c:a libopus /tmp/short.webm
curl -sS -D - -X POST http://127.0.0.1:8003/upload \
  -F "file=@/tmp/short.webm;type=audio/webm"
```

- 状态码：`422`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "AUDIO_DURATION_INVALID",
    "message": "录音时长需在 1 到 60 秒之间，请重新录制。",
    "stage": "upload"
  }
}
```

超过 60 秒把上面的 `-t 0.5` 改成 `-t 61`，状态码和 `code` 相同。

缺少 `file` 字段时状态码 `422`，`code` 为 `VALIDATION_ERROR`。

可选 Mock 测试（不调用真实 ffprobe，不能代替真实录音上传）：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_upload.py
```

## 如何验证 POST /asr

后端改代码后需重启 `uvicorn`。本轮未接前端。

### Mock（无费用）

不调用百炼，不能证明真实识别已跑通：

```bash
cd backend
source .venv/bin/activate
pytest tests/test_asr.py
```

覆盖：识别成功、编号不存在、已过期、识别为空、超时 504、上游失败 502、缺字段 422。

本地也可不填密钥、用一个不存在的 `audio_id` 测 404，这不会产生调用费用：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{"audio_id":"00000000-0000-0000-0000-000000000000"}'
```

- 状态码：`404`
- 响应：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "error": {
    "code": "AUDIO_NOT_FOUND",
    "message": "录音不存在或已过期，请重新录音。",
    "stage": "asr"
  }
}
```

缺字段：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{}'
```

- 状态码：`422`，`code` 为 `VALIDATION_ERROR`

### 真实识别（需要 BAILIAN_API_KEY，会产生调用费用）

请你确认后再执行。密钥填在 `backend/.env` 的 `BAILIAN_API_KEY`，使用北京地域；`BAILIAN_ASR_URL` 与 `BAILIAN_ASR_MODEL` 保持默认。

1. 先上传录音，记下返回的 `audio_id`：

```bash
curl -sS -X POST http://127.0.0.1:8003/upload \
  -F "file=@$HOME/Downloads/meetup-recording-XXXX.webm;type=audio/webm"
```

或在 <http://localhost:8003/docs> 执行 `POST /upload`。

2. 把该 `audio_id` 填入 `POST /asr`（/docs 里 Try it out，或 curl）：

```bash
curl -sS -D - -X POST http://127.0.0.1:8003/asr \
  -H "Content-Type: application/json" \
  -d '{"audio_id":"粘贴上传返回的audio_id"}'
```

正常时应为 `200`，`data.text` 是这段录音的真实识别结果，而不是固定文案：

```json
{
  "request_id": "8f1a2b3c-4d5e-6789-abcd-ef0123456789",
  "data": {
    "text": "我在杭州东站，朋友在西湖龙翔桥地铁站，帮我们找个中间的咖啡店。"
  }
}
```

上面的 `text` 仅为结构示例；你应看到自己说的话。

若识别结果为空：`422` / `ASR_EMPTY`。  
若百炼超时：`504` / `UPSTREAM_TIMEOUT`。  
若百炼 HTTP 或业务失败：`502` / `UPSTREAM_ERROR`。  
若返回结构无法解析：`502` / `MODEL_OUTPUT_INVALID`。

## 健康检查

1. 浏览器打开 <http://localhost:8003/docs>，执行 `GET /health`。
2. 浏览器打开 <http://localhost:5175>；后端已启动时，「后端服务」显示「正常」。
3. 可选：在 `backend` 目录、已激活虚拟环境后执行 `pytest tests/test_health.py`。

预期 `GET /health`：HTTP `200`，响应形如：

```json
{
  "request_id": "uuid-string",
  "data": {
    "status": "ok"
  }
}
```

## 测试说明

自动化测试目前只用 Mock / 本地应用，不调用付费接口。Mock 通过不能证明真实 ASR、DeepSeek、高德、TTS 已跑通；真实验收需在填写密钥并由你确认后再做。
