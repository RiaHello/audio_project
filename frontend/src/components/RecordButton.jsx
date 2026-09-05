import { useEffect, useRef, useState } from "react";
import {
  MAX_DURATION_MS,
  MAX_FILE_BYTES,
  MIN_DURATION_MS,
  detectRecordingMimeType,
  formatDuration,
  formatFileSize,
  recordingFileName,
  releaseMediaStream,
} from "../audio/recording.js";

function microphoneErrorMessage(error) {
  const name = error?.name;
  if (name === "NotAllowedError" || name === "PermissionDeniedError") {
    return "麦克风未授权，请在浏览器中允许后重试。";
  }
  if (name === "NotFoundError" || name === "DevicesNotFoundError") {
    return "未找到可用麦克风，请接好设备后重试。";
  }
  if (name === "NotReadableError" || name === "TrackStartError") {
    return "无法使用麦克风，请确认没有被其他应用占用。";
  }
  return "无法开始录音，请检查麦克风后重试。";
}

export default function RecordButton() {
  const supportedMimeType = detectRecordingMimeType();
  const [phase, setPhase] = useState("idle");
  const [elapsedMs, setElapsedMs] = useState(0);
  const [error, setError] = useState(
    supportedMimeType
      ? null
      : "当前浏览器不支持 WebM/Opus 录音，请更换 Chrome 或 Edge 后重试。",
  );
  const [clip, setClip] = useState(null);

  const intentRef = useRef("idle");
  const pointerIdRef = useRef(null);
  const recorderRef = useRef(null);
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const startedAtRef = useRef(0);
  const mimeTypeRef = useRef(supportedMimeType);
  const stopReasonRef = useRef("complete");
  const maxTimerRef = useRef(0);
  const tickTimerRef = useRef(0);
  const clipUrlRef = useRef(null);
  const listeningRef = useRef(false);
  const requestStopRef = useRef(() => {});
  const listenersRef = useRef({ bind() {}, unbind() {} });

  function clearTimers() {
    window.clearTimeout(maxTimerRef.current);
    window.clearInterval(tickTimerRef.current);
    maxTimerRef.current = 0;
    tickTimerRef.current = 0;
  }

  function revokeClipUrl() {
    if (clipUrlRef.current) {
      URL.revokeObjectURL(clipUrlRef.current);
      clipUrlRef.current = null;
    }
  }

  function cleanupStream() {
    clearTimers();
    releaseMediaStream(streamRef.current);
    streamRef.current = null;
    recorderRef.current = null;
    chunksRef.current = [];
    pointerIdRef.current = null;
  }

  function finishRecorder() {
    const recorder = recorderRef.current;
    if (recorder && recorder.state !== "inactive") {
      recorder.stop();
      return;
    }
    cleanupStream();
    listenersRef.current.unbind();
    intentRef.current = "idle";
    setPhase("idle");
  }

  function requestStop(reason) {
    if (intentRef.current === "starting") {
      intentRef.current = "idle";
      stopReasonRef.current = reason;
      cleanupStream();
      listenersRef.current.unbind();
      setPhase("idle");
      setElapsedMs(0);
      return;
    }
    if (intentRef.current !== "recording") {
      return;
    }
    intentRef.current = "stopping";
    stopReasonRef.current = reason;
    setPhase("stopping");
    finishRecorder();
  }

  requestStopRef.current = requestStop;

  useEffect(() => {
    function onPointerUp(event) {
      if (pointerIdRef.current !== null && event.pointerId !== pointerIdRef.current) {
        return;
      }
      requestStopRef.current("complete");
    }

    function onPointerCancel(event) {
      if (pointerIdRef.current !== null && event.pointerId !== pointerIdRef.current) {
        return;
      }
      requestStopRef.current("cancel");
    }

    function onKeyDown(event) {
      if (event.key === "Escape") {
        requestStopRef.current("cancel");
      }
    }

    function onVisibilityChange() {
      if (document.visibilityState === "hidden") {
        requestStopRef.current("complete");
      }
    }

    function onPageHide() {
      requestStopRef.current("cancel");
    }

    listenersRef.current = {
      bind() {
        if (listeningRef.current) {
          return;
        }
        listeningRef.current = true;
        window.addEventListener("pointerup", onPointerUp);
        window.addEventListener("pointercancel", onPointerCancel);
        window.addEventListener("keydown", onKeyDown);
        document.addEventListener("visibilitychange", onVisibilityChange);
        window.addEventListener("pagehide", onPageHide);
      },
      unbind() {
        if (!listeningRef.current) {
          return;
        }
        listeningRef.current = false;
        window.removeEventListener("pointerup", onPointerUp);
        window.removeEventListener("pointercancel", onPointerCancel);
        window.removeEventListener("keydown", onKeyDown);
        document.removeEventListener("visibilitychange", onVisibilityChange);
        window.removeEventListener("pagehide", onPageHide);
      },
    };

    return () => {
      intentRef.current = "idle";
      listenersRef.current.unbind();
      cleanupStream();
      revokeClipUrl();
    };
    // Mount/unmount only.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function startRecording(event) {
    if (event.button !== undefined && event.button !== 0) {
      return;
    }
    event.preventDefault();
    if (intentRef.current !== "idle") {
      return;
    }
    if (!supportedMimeType) {
      setError("当前浏览器不支持 WebM/Opus 录音，请更换 Chrome 或 Edge 后重试。");
      return;
    }

    intentRef.current = "starting";
    stopReasonRef.current = "complete";
    chunksRef.current = [];
    mimeTypeRef.current = supportedMimeType;
    pointerIdRef.current = event.pointerId;
    setError(null);
    setElapsedMs(0);
    setPhase("starting");
    listenersRef.current.bind();

    if (event.currentTarget.setPointerCapture) {
      try {
        event.currentTarget.setPointerCapture(event.pointerId);
      } catch {
        // Capture is optional; window pointerup still ends the take.
      }
    }

    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (intentRef.current !== "starting") {
        releaseMediaStream(stream);
        return;
      }

      streamRef.current = stream;
      const recorder = new MediaRecorder(stream, { mimeType: supportedMimeType });
      recorderRef.current = recorder;

      recorder.ondataavailable = (blobEvent) => {
        if (blobEvent.data && blobEvent.data.size > 0) {
          chunksRef.current.push(blobEvent.data);
        }
      };

      recorder.onerror = () => {
        setError("录制失败，请重新按住按钮尝试。");
        requestStopRef.current("cancel");
      };

      recorder.onstop = () => {
        const durationMs = startedAtRef.current ? Date.now() - startedAtRef.current : 0;
        const reason = stopReasonRef.current;
        const recordedType = mimeTypeRef.current || "audio/webm";
        const blob = new Blob(chunksRef.current, { type: recordedType });
        cleanupStream();
        listenersRef.current.unbind();
        intentRef.current = "idle";
        setPhase("idle");
        setElapsedMs(0);

        if (reason === "cancel") {
          return;
        }
        if (durationMs < MIN_DURATION_MS) {
          setError("录音时长需在 1 到 60 秒之间，请重新按住说话。");
          return;
        }
        if (blob.size === 0) {
          setError("录制失败，请重新按住按钮尝试。");
          return;
        }
        if (blob.size > MAX_FILE_BYTES) {
          setError("录音文件超过 5MB，请缩短录音后重试。");
          return;
        }

        revokeClipUrl();
        const url = URL.createObjectURL(blob);
        clipUrlRef.current = url;
        setClip({
          url,
          mimeType: recordedType,
          size: blob.size,
          durationMs: Math.min(durationMs, MAX_DURATION_MS),
          fileName: recordingFileName(),
        });
      };

      startedAtRef.current = Date.now();
      recorder.start();
      intentRef.current = "recording";
      setPhase("recording");

      tickTimerRef.current = window.setInterval(() => {
        setElapsedMs(Math.min(Date.now() - startedAtRef.current, MAX_DURATION_MS));
      }, 100);

      maxTimerRef.current = window.setTimeout(() => {
        requestStopRef.current("complete");
      }, MAX_DURATION_MS);
    } catch (err) {
      cleanupStream();
      listenersRef.current.unbind();
      intentRef.current = "idle";
      setPhase("idle");
      setError(microphoneErrorMessage(err));
    }
  }

  const isBusy = phase === "starting" || phase === "recording" || phase === "stopping";

  return (
    <section className="recorder" aria-label="录音">
      <button
        type="button"
        className={`record-button ${isBusy ? "is-recording" : ""}`}
        disabled={!supportedMimeType}
        onPointerDown={startRecording}
        onContextMenu={(event) => event.preventDefault()}
      >
        {phase === "recording" ? "松开结束" : "按住说话"}
      </button>

      <p className="recorder-hint">
        {phase === "recording"
          ? `录音中 ${formatDuration(elapsedMs)} / 01:00`
          : "按住按钮说话，松开结束。Esc 取消。最长 60 秒。"}
      </p>

      {phase === "recording" ? (
        <button type="button" className="text-button" onClick={() => requestStop("cancel")}>
          取消录音
        </button>
      ) : null}

      {error ? (
        <p className="recorder-error" role="alert">
          {error}
        </p>
      ) : null}

      {clip ? (
        <div className="clip">
          <p className="clip-meta">
            本地录音已就绪 · {clip.mimeType} · {formatFileSize(clip.size)} ·{" "}
            {formatDuration(clip.durationMs)}
          </p>
          <audio className="clip-player" controls src={clip.url} />
          <a className="download-link" href={clip.url} download={clip.fileName}>
            下载录音文件
          </a>
        </div>
      ) : null}
    </section>
  );
}
