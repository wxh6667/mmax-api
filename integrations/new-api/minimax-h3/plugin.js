export const meta = {
  apiVersion: 1,
  key: "mmax-h3",
  name: "mmax MiniMax H3",
  description: {
    zh: "通过标准 OpenAI Video 协议调用 mmax-api 的 MiniMax H3，支持文生视频、首帧、尾帧和关键帧。",
    en: "MiniMax H3 through the standard OpenAI Video protocol, with text-to-video and keyframe conditioning.",
  },
  version: "1.0.0",
  channelTypes: [1],
  author: { name: "wxh6667" },
  models: ["minimax-h3"],
  fetchMode: "per_task",
  usageSchema: {
    seconds: {
      type: "number",
      unit: "second",
      description: { zh: "请求的视频时长（秒）。", en: "Requested video duration in seconds." },
    },
    size: {
      enum: ["720x1280", "1280x720", "1792x1024", "1024x1792"],
      description: { zh: "输出视频尺寸。", en: "Requested output video size." },
    },
  },
  protocols: ["openai_video"],
};

function requestValues(req, model) {
  const values = Object.assign({}, req || {});
  values.model = model;
  return values;
}

export function buildSubmitRequest(ctx) {
  const req = ctx.requestBody || {};
  if (!String(req.prompt || "").trim()) throw new Error("field prompt is required");

  const headers = { Authorization: "Bearer " + ctx.apiKey };
  if ((ctx.files || []).length) {
    const parts = [];
    const values = requestValues(req, ctx.upstreamModel);
    for (const key of Object.keys(values)) {
      const value = values[key];
      if (value === undefined || value === null) continue;
      if (typeof value === "object") parts.push({ name: key, value: JSON.stringify(value) });
      else parts.push({ name: key, value: value });
    }
    for (const file of ctx.files) {
      parts.push({ name: file.field, fileRef: file.ref, filename: file.filename });
    }
    return {
      url: ctx.baseUrl + "/v1/videos",
      method: "POST",
      headers,
      bodyType: "multipart",
      parts,
    };
  }

  headers["Content-Type"] = "application/json";
  return {
    url: ctx.baseUrl + "/v1/videos",
    method: "POST",
    headers,
    body: requestValues(req, ctx.upstreamModel),
  };
}

export function parseSubmitResponse(ctx, resp) {
  const body = resp.body || {};
  const taskId = body.id || body.task_id;
  if (!taskId) throw new Error("task_id is empty");
  return { taskId, taskData: body };
}

export function extractUsage(ctx) {
  const req = ctx.requestBody || {};
  let seconds = Number(req.seconds || req.duration || 4);
  if (!Number.isFinite(seconds) || seconds <= 0) seconds = 4;
  return { seconds, size: req.size || "1280x720" };
}

export function buildQueryRequest(ctx) {
  return {
    url: ctx.baseUrl + "/v1/videos/" + encodeURIComponent(ctx.taskId),
    method: "GET",
    headers: { Authorization: "Bearer " + ctx.apiKey },
  };
}

export function parseTaskResult(ctx, body) {
  const statuses = {
    queued: "QUEUED",
    pending: "QUEUED",
    processing: "IN_PROGRESS",
    in_progress: "IN_PROGRESS",
    completed: "SUCCESS",
    failed: "FAILURE",
    cancelled: "FAILURE",
  };
  const mapped = statuses[body.status];
  const result = { status: mapped || "UNKNOWN" };
  if (!mapped) result.reason = "unrecognized status: " + String(body.status || "");
  if (body.progress > 0 && body.progress < 100) result.progress = body.progress + "%";
  if (result.status === "FAILURE") {
    result.reason = body.error && body.error.message ? body.error.message : "task failed";
  }
  return result;
}

export function listArtifacts(task) {
  return task.status === "SUCCESS" ? [{ key: "video", type: "video" }] : [];
}

export function buildContentRequest(ctx) {
  if (ctx.artifactKey !== "video") throw new Error("artifact_not_found");
  return {
    url: ctx.baseUrl + "/v1/videos/" + encodeURIComponent(ctx.upstreamTaskId) + "/content",
    method: ctx.clientRequest.method,
    headers: { Authorization: "Bearer " + ctx.apiKey },
  };
}

function renderOpenAIVideo(task) {
  const statuses = {
    NOT_START: "queued",
    SUBMITTED: "queued",
    QUEUED: "queued",
    IN_PROGRESS: "in_progress",
    SUCCESS: "completed",
    FAILURE: "failed",
  };
  const output = {
    id: task.task_id,
    object: "video",
    model: (task.properties || {}).origin_model_name || "minimax-h3",
    status: statuses[task.status] || "unknown",
    progress: Number(String(task.progress || "0").replace("%", "")),
    created_at: Number(task.created_at || 0),
  };
  const completedAt = Number(task.finished_at || task.updated_at || 0);
  if (completedAt > 0) output.completed_at = completedAt;
  if (task.status === "FAILURE") {
    output.error = {
      code: "video_generation_failed",
      message: task.fail_reason || "The video generation task failed.",
    };
  }
  return output;
}

export const protocols = {
  openai_video: {
    decodeRequest: function (ctx) {
      if (!ctx.body || (ctx.body.kind !== "json" && ctx.body.kind !== "multipart")) {
        throw new Error("JSON or multipart body required");
      }

      if (ctx.body.kind === "json") {
        const req = ctx.body.value;
        if (!req || typeof req !== "object" || Array.isArray(req)) throw new Error("JSON object required");
        if (!String(req.prompt || "").trim()) throw new Error("prompt is required");
        return {
          kind: "submit",
          model: ctx.model,
          action: req.input_reference ? "image_to_video" : "text_to_video",
          requestBody: Object.assign({}, req, { model: ctx.model }),
        };
      }

      const first = function (name) {
        const values = (ctx.body.fields || {})[name] || [];
        if (values.length > 1) throw new Error(name + " must be provided once");
        return values[0];
      };
      const req = {};
      const fields = ctx.body.fields || {};
      for (const name of Object.keys(fields)) req[name] = first(name);

      const files = ctx.body.files || [];
      let hasFrameFile = false;
      for (const file of files) {
        if (!["input_reference", "end_reference"].includes(file.field)) {
          throw new Error("unexpected file field: " + file.field);
        }
        hasFrameFile = true;
      }

      if (!String(req.prompt || "").trim()) throw new Error("prompt is required");
      if (req.seconds !== undefined) req.seconds = Number(req.seconds);
      else if (req.duration !== undefined) req.seconds = Number(req.duration);

      return {
        kind: "submit",
        model: ctx.model,
        action: hasFrameFile || req.input_reference ? "image_to_video" : "text_to_video",
        requestBody: Object.assign({}, req, { model: ctx.model }),
      };
    },
    render: function (ctx, task) {
      return renderOpenAIVideo(task);
    },
  },
};
