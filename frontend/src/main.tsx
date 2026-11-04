import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

function render() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
}

// The browser's owner cookie first (one request), so the history, the chat list and the WebSocket all carry the
// same one: parallel first requests would each get a new owner, and the chat would belong to only one of them.
fetch("/api/v1/session", { credentials: "same-origin" })
  .catch(() => undefined)
  .finally(render);
