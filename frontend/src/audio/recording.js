export const MIN_DURATION_MS = 1000;
export const MAX_DURATION_MS = 60_000;
export const MAX_FILE_BYTES = 5 * 1024 * 1024;

const MIME_CANDIDATES = ["audio/webm;codecs=opus", "audio/webm"];

export function detectRecordingMimeType() {
  if (
    typeof MediaRecorder === "undefined" ||
    typeof MediaRecorder.isTypeSupported !== "function"
  ) {
    return null;
  }
  return MIME_CANDIDATES.find((type) => MediaRecorder.isTypeSupported(type)) ?? null;
}

export function releaseMediaStream(stream) {
  if (!stream) {
    return;
  }
  for (const track of stream.getTracks()) {
    track.stop();
  }
}

export function formatDuration(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const minutes = String(Math.floor(totalSeconds / 60)).padStart(2, "0");
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  return `${minutes}:${seconds}`;
}

export function formatFileSize(bytes) {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  return `${(bytes / 1024).toFixed(1)} KB`;
}

export function recordingFileName() {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  return `meetup-recording-${stamp}.webm`;
}
