import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import AdminApp from "./admin/AdminApp";
import "./index.css";

const isAdmin = window.location.pathname.startsWith("/admin");

function render() {
  createRoot(document.getElementById("root")!).render(
    <StrictMode>{isAdmin ? <AdminApp /> : <App />}</StrictMode>,
  );
}

if (isAdmin) {
  // The admin page (spec 010 US4) needs no owner cookie: it is authorised by its token.
  render();
} else {
  // The browser's owner cookie first (one request), so the history, the chat list and the WebSocket all carry the
  // same one: parallel first requests would each get a new owner, and the chat would belong to only one of them.
  fetch("/api/v1/session", { credentials: "same-origin" })
    .catch(() => undefined)
    .finally(render);
}
