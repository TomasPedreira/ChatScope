import {
  $,
  formatMediaTime,
  createTextElement,
  showToast,
} from "./dom_helpers.js";
import { invokeTauriCommand } from "./tauri_client.js";

export function createClipProductionView(getSessionSnapshot) {
  let isProductionRunning = false;
  let lastProductionSignature = "";
  async function refreshProductionState() {
    try {
      const job = await invokeTauriCommand("get_production");
      if (!job) return;
      isProductionRunning = job.busy;
      $("render-selection").disabled =
        !getSessionSnapshot()?.source || isProductionRunning;
      $("render-all").disabled =
        !getSessionSnapshot()?.moments?.length || isProductionRunning;
      $("render-cancel").classList.toggle(
        "hidden",
        !isProductionRunning || job.writable === false,
      );
      $("render-retry").classList.toggle(
        "hidden",
        isProductionRunning ||
          !["interrupted", "cancelled", "error", "partial"].includes(
            job.status,
          ),
      );
      const clips = job.clips || [];
      const ready = clips.filter((clip) => clip.status === "ready").length;
      const labels = {
        idle: "sem uploads automáticos",
        running: "em curso",
        complete: "concluída",
        partial: "parcial",
        cancelled: "cancelada",
        interrupted: "interrompida",
        error: "erro",
      };
      $("production-summary").textContent =
        `Produção local · ${labels[job.status] || job.status}${clips.length ? ` · ${ready}/${clips.length} MP4 prontos` : ""}${job.detail ? ` · ${job.detail}` : ""}`;
      const key = JSON.stringify(clips);
      if (key === lastProductionSignature) return;
      lastProductionSignature = key;
      $("production-clips").replaceChildren(
        ...clips.map((clip, index) => {
          const row = document.createElement("div");
          row.className = "production-clip";
          const statuses = {
            queued: "em fila",
            acquiring: "a adquirir vídeo",
            rendering: "a editar",
            ready: "pronto",
            error: "erro",
            cancelled: "cancelado",
            interrupted: "interrompido",
          };
          row.append(
            createTextElement(
              "span",
              "",
              `${index + 1}. ${formatMediaTime(clip.moment?.start)} — ${formatMediaTime(clip.moment?.end)} · ${statuses[clip.status] || clip.status}${clip.error ? ` · ${clip.error}` : ""}`,
            ),
          );
          if (clip.status === "ready") {
            const open = createTextElement("button", "", "Rever MP4 ↗");
            open.type = "button";
            open.addEventListener("click", () =>
              invokeTauriCommand("open_media_output", { index }).catch(
                (error) => showToast(String(error)),
              ),
            );
            row.append(open);
          }
          return row;
        }),
      );
    } catch (error) {
      $("production-summary").textContent =
        `Produção indisponível: ${String(error)}`;
    }
  }
  for (const [id, all] of [
    ["render-selection", false],
    ["render-all", true],
  ])
    $(id).addEventListener("click", async () => {
      try {
        await invokeTauriCommand("create_clips", {
          start: $("render-start").value || null,
          end: $("render-end").value || null,
          all,
          renderProfile: {
            aspect: $("render-aspect").value,
            fit: $("render-fit").value,
            captions: $("render-captions").checked,
            captionProfile: {
              sourceLanguage: $("caption-source-language").value,
              targetLanguage: $("caption-target-language").value,
              model: "small",
            },
          },
          topic: $("render-topic").value,
        });
        $("production-results").open = true;
        await refreshProductionState();
      } catch (error) {
        showToast(String(error));
      }
    });
  $("render-cancel").addEventListener("click", () =>
    invokeTauriCommand("cancel_production")
      .then(refreshProductionState)
      .catch((error) => showToast(String(error))),
  );
  function updateCaptionLanguageControls() {
    $("caption-source-language").disabled = !$("render-captions").checked;
    $("caption-target-language").disabled = !$("render-captions").checked;
    const portugueseOption = $("caption-target-language").querySelector(
      'option[value="pt"]',
    );
    portugueseOption.disabled = $("caption-source-language").value === "en";
    if (
      portugueseOption.disabled &&
      $("caption-target-language").value === "pt"
    )
      $("caption-target-language").value = "en";
  }
  $("render-captions").addEventListener(
    "change",
    updateCaptionLanguageControls,
  );
  $("caption-source-language").addEventListener(
    "change",
    updateCaptionLanguageControls,
  );
  $("render-retry").addEventListener("click", () =>
    invokeTauriCommand("retry_production")
      .then(refreshProductionState)
      .catch((error) => showToast(String(error))),
  );
  $("open-output").addEventListener("click", () =>
    invokeTauriCommand("open_media_output").catch((error) =>
      showToast(String(error)),
    ),
  );

  refreshProductionState();
  setInterval(refreshProductionState, 1000);
  return { isRunning: () => isProductionRunning };
}
