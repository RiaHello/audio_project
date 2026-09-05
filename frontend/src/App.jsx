import { useEffect, useState } from "react";
import { getHealth } from "./api.js";
import CitySelect from "./components/CitySelect.jsx";
import RecordButton from "./components/RecordButton.jsx";

function App() {
  const [city, setCity] = useState("杭州");
  const [health, setHealth] = useState({ status: "checking" });

  useEffect(() => {
    let cancelled = false;

    getHealth()
      .then((response) => {
        if (cancelled) {
          return;
        }
        const payload = response.data;
        if (payload?.data?.status === "ok") {
          setHealth({
            status: "ok",
            requestId: payload.request_id,
          });
          return;
        }
        setHealth({ status: "error" });
      })
      .catch(() => {
        if (!cancelled) {
          setHealth({ status: "error" });
        }
      });

    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="page">
      <header className="mast">
        <p className="eyebrow">同一座城市 · 两个人</p>
        <h1>语音约碰面地点</h1>
        <p className="lede">
          按住说话，说明两个人的位置。本轮只做本地录音，不会上传或识别。
        </p>
      </header>

      <section className="ticket" aria-label="当前会话">
        <CitySelect value={city} onChange={setCity} />
        <div className="ticket-row">
          <span className="label">后端服务</span>
          <span className={`status status-${health.status}`}>
            {health.status === "checking" && "检测中"}
            {health.status === "ok" && "正常"}
            {health.status === "error" && "未连接"}
          </span>
        </div>
        {health.requestId ? (
          <p className="request-id">request_id：{health.requestId}</p>
        ) : null}
      </section>

      <RecordButton />
    </div>
  );
}

export default App;
