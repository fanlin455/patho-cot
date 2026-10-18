"""
@file app.py
@brief Patho-COT Web 诊断系统入口（FastAPI）
       提供统一五级流水线页面 + SSE 进度推送
"""
import os
import uuid
import shutil
import json
import asyncio
import queue
import sqlite3
import datetime
import warnings
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from fastapi import FastAPI, File, Form, UploadFile, Request
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse, StreamingResponse, Response, RedirectResponse
from engine import ModelManager
from engine import ReportGenerator

# 抑制 torch 的 FutureWarning 日志噪音
warnings.filterwarnings("ignore", message=".*weights_only=False.*")

app = FastAPI()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOADS_DIR = os.path.join(STATIC_DIR, "uploads")
RESULTS_DIR = os.path.join(STATIC_DIR, "results")

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(RESULTS_DIR, exist_ok=True)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def _no_cache_html(request, call_next):
    """HTML 页面禁用浏览器缓存：模板改动后刷新即可生效，避免看到旧页面。"""
    response = await call_next(request)
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

engine = ModelManager()
executor = ThreadPoolExecutor(max_workers=1)
report_executor = ThreadPoolExecutor(max_workers=1)  # 报告生成专用线程池
gpu_work_lock = threading.Lock()

# 本次服务进程的唯一标识：每次重启都会重新生成。
# 前端登录时记录该标识，访问内页时校验，重启后标识不匹配即强制重新登录。
SERVICE_BOOT_ID = uuid.uuid4().hex

LLM_EXCLUDED_RESULT_KEYS = {
    "file_url",
    "filename",
    "image",
    "image_path",
    "image_url",
    "original_name",
    "patch_name",
    "patch_url",
    "roi_image_url",
    "chart_url",
    "organ_chart",
    "nature_chart",
    "subtype_chart",
    "roi_image",
}


# ============================================================
# SSE 辅助函数
# ============================================================

class _NumpyEncoder(json.JSONEncoder):
    """自定义 JSON 编码器，处理 numpy 类型和 NaN/Inf"""
    def default(self, obj):
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            val = float(obj)
            if np.isnan(val) or np.isinf(val):
                return None
            return val
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        return super().default(obj)

    def encode(self, o):
        """覆盖 encode，在最终字符串中额外处理 NaN/Inf"""
        return super().encode(self._sanitize(o))

    def iterencode(self, o, _one_shot=False):
        return super().iterencode(self._sanitize(o), _one_shot)

    @staticmethod
    def _sanitize(obj):
        """递归替换所有值为 NaN/Inf 的 float"""
        if isinstance(obj, float):
            if obj != obj or obj in (float('inf'), float('-inf')):
                return 0.0
            return obj
        if isinstance(obj, dict):
            return {k: _NumpyEncoder._sanitize(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [_NumpyEncoder._sanitize(v) for v in obj]
        return obj


# ============================================================
# 历史记录持久化（SQLite，数据库自动创建，路径无关）
# ============================================================

HISTORY_DB = os.path.join(BASE_DIR, "history.db")


def _db():
    conn = sqlite3.connect(HISTORY_DB)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                mode TEXT NOT NULL,
                filename TEXT NOT NULL,
                events TEXT NOT NULL,
                description TEXT,
                report TEXT
            )"""
        )


_init_db()


def _save_record(mode: str, filename: str, events: list) -> int:
    """保存一次分析的完整事件流，返回记录 id。"""
    with _db() as conn:
        cur = conn.execute(
            "INSERT INTO records (created_at, mode, filename, events) VALUES (?,?,?,?)",
            (
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                mode,
                filename,
                json.dumps(events, ensure_ascii=False, cls=_NumpyEncoder, default=str),
            ),
        )
        return cur.lastrowid


def _update_record_events(record_id: int, events: list):
    """分步向导每完成一步即更新事件流，保证中断的任务也已在历史中。"""
    if not record_id:
        return
    with _db() as conn:
        conn.execute(
            "UPDATE records SET events=? WHERE id=?",
            (json.dumps(events, ensure_ascii=False, cls=_NumpyEncoder, default=str),
             record_id),
        )


def _update_record_report(record_id, description: str, report: str):
    """把病情描述和 LLM 报告回填到对应历史记录。"""
    if not record_id:
        return
    try:
        with _db() as conn:
            conn.execute(
                "UPDATE records SET description=?, report=? WHERE id=?",
                (description or "", report or "", record_id),
            )
    except Exception as e:
        print(f"[History] 回填报告失败: {e}")


def _list_records(limit: int = 200):
    with _db() as conn:
        rows = conn.execute(
            "SELECT id, created_at, mode, filename, events, report "
            "FROM records ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return rows


def _get_record(record_id: int):
    with _db() as conn:
        return conn.execute(
            "SELECT * FROM records WHERE id=?", (record_id,)
        ).fetchone()


def _load_events(row) -> list:
    try:
        return json.loads(row["events"] or "[]")
    except Exception:
        return []


def _summarize(events: list) -> dict:
    """从事件流提取摘要，供历史列表页展示。"""
    s = {
        "mode": "single", "organ": "", "organ_cn": "", "organ_prob": None,
        "nature": "", "nature_cn": "", "nature_prob": None,
        "subtype": "", "subtype_cn": "", "lesion": None, "total": None,
        "usable": None, "quality": None, "ok_steps": 0, "has_error": False,
    }
    for evt in events or []:
        data = evt.get("data") or {}
        et = evt.get("event_type") or data.get("event_type")
        if et == "multi_summary":
            s["mode"] = "multi"
            summ = data.get("summary") or {}
            s["organ_cn"] = summ.get("top_organ_cn") or ""
            s["usable"] = f"{summ.get('usable_patches')}/{summ.get('total_patches')}"
            s["lesion"] = summ.get("total_lesion_count")
            continue
        sid = evt.get("step_id")
        if evt.get("status") == "done":
            s["ok_steps"] += 1
            if sid == 1:
                s["usable"] = "通过" if data.get("is_usable") else "未通过"
                s["quality"] = data.get("usability_score")
            elif sid == 2:
                s["organ"] = data.get("top_organ", "")
                s["organ_cn"] = data.get("top_organ_cn") or data.get("top_organ", "")
                s["organ_prob"] = data.get("top_prob")
            elif sid == 3:
                s["lesion"] = data.get("lesion_count")
                s["total"] = data.get("total_boxes")
            elif sid == 4:
                s["nature"] = data.get("top_nature", "")
                s["nature_cn"] = data.get("top_nature_cn") or ""
                s["nature_prob"] = data.get("top_prob")
            elif sid == 5:
                s["subtype"] = data.get("top_subtype", "")
                s["subtype_cn"] = data.get("top_subtype_cn") or ""
        elif evt.get("status") == "error":
            s["has_error"] = True
    return s


def _sse_json(data: dict) -> str:
    """将 dict 转为 SSE 格式的 JSON 行，自动处理 numpy 类型"""
    return f"data: {json.dumps(data, ensure_ascii=False, cls=_NumpyEncoder)}\n\n"


def _sse_response(generator):
    """创建 StreamingResponse 并设置正确的 SSE 头"""
    return StreamingResponse(
        generator,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _strip_llm_image_hints(value):
    """移除传给 LLM 的图片名称、URL 和路径字段，避免文件名影响报告生成。"""
    if isinstance(value, list):
        return [_strip_llm_image_hints(item) for item in value]
    if isinstance(value, dict):
        return {
            key: _strip_llm_image_hints(item)
            for key, item in value.items()
            if key not in LLM_EXCLUDED_RESULT_KEYS
        }
    return value


def _run_with_gpu_lock(work_name: str, fn, *args):
    """串行化视觉模型与 Ollama 报告生成，避免同时抢占同一块 GPU。"""
    print(f"[GPU-LOCK] {work_name} 等待 GPU 工作锁")
    with gpu_work_lock:
        print(f"[GPU-LOCK] {work_name} 已获取 GPU 工作锁")
        try:
            return fn(*args)
        finally:
            print(f"[GPU-LOCK] {work_name} 已释放 GPU 工作锁")

# ============================================================
# 页面路由
# ============================================================

@app.get("/favicon.ico")
async def favicon():
    """浏览器 favicon 请求，返回空响应避免 404"""
    return Response(status_code=204)

@app.get("/")
async def read_cover(request: Request):
    """系统入口：主题封面 + 登录页（未登录先到封面）。"""
    return templates.TemplateResponse(request=request, name="landing.html")


@app.get("/dashboard")
async def read_dashboard(request: Request):
    """登录后的总览仪表盘。"""
    return templates.TemplateResponse(request=request, name="dashboard.html")


# 六步引导式分步诊断：每步独立页面（step 1~6 -> 对应模板）
_DIAGNOSE_TEMPLATES = {
    1: "diagnose_1_quality.html",
    2: "diagnose_2_organ.html",
    3: "diagnose_3_detection.html",
    4: "diagnose_4_nature.html",
    5: "diagnose_5_subtype.html",
    6: "diagnose_6_report.html",
}


@app.get("/diagnose/{step}")
async def read_diagnose_step(request: Request, step: int):
    """分步诊断独立页面：质量检测/器官分类/细胞检测/病变性质/亚型/AI报告。"""
    tpl = _DIAGNOSE_TEMPLATES.get(step)
    if tpl is None:
        return JSONResponse({"error": "步骤不存在"}, status_code=404)
    return templates.TemplateResponse(
        request=request, name=tpl,
        context={"step": step, "total_steps": 6},
    )


@app.get("/multi")
async def read_multi(request: Request):
    """多图（多 patch）分析页面"""
    return templates.TemplateResponse(request=request, name="multi.html")

@app.get("/history")
async def read_history(request: Request):
    """历史记录列表页"""
    items = []
    for row in _list_records():
        events = _load_events(row)
        items.append({
            "id": row["id"],
            "created_at": row["created_at"],
            "mode": row["mode"],
            "filename": row["filename"],
            "summary": _summarize(events),
            "has_report": bool(row["report"]),
        })
    return templates.TemplateResponse(
        request=request, name="history.html", context={"records": items}
    )


@app.get("/history/{record_id}")
async def read_history_detail(request: Request, record_id: int):
    """历史记录详情页"""
    row = _get_record(record_id)
    if row is None:
        return templates.TemplateResponse(
            request=request, name="history_detail.html",
            context={"record": None, "steps": {}, "events": []}, status_code=404,
        )
    events = _load_events(row)
    steps = {}
    for evt in events:
        sid = evt.get("step_id")
        if isinstance(sid, int) and 1 <= sid <= 5 and evt.get("status") == "done":
            steps[sid] = evt.get("data") or {}
    multi_summary = None
    for evt in events:
        data = evt.get("data") or {}
        if (evt.get("event_type") or data.get("event_type")) == "multi_summary":
            multi_summary = data
            break
    return templates.TemplateResponse(
        request=request, name="history_detail.html",
        context={
            "record": row, "steps": steps, "multi_summary": multi_summary,
            "events": events,
        },
    )

# ============================================================
# 分步向导（单图）接口：一次只跑一步，用户主导节奏
# ============================================================

_TASKS = {}
_TASK_MAX = 500


@app.post("/api/tasks")
async def api_create_task(file: UploadFile = File(...), description: str = Form("")):
    """创建单图分析任务（分步向导入口），上传图片并返回 task_id。"""
    file_ext = os.path.splitext(file.filename or "")[1] or ".png"
    task_id = str(uuid.uuid4())
    filename = f"{task_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    _TASKS[task_id] = {
        "filename": file.filename or filename,
        "path": filepath,
        "description": description or "",
        "record_id": None,
        "events": [],
    }
    if len(_TASKS) > _TASK_MAX:  # 防止内存无限增长，淘汰最旧任务
        for key in list(_TASKS.keys())[:-_TASK_MAX]:
            _TASKS.pop(key, None)
    return JSONResponse({
        "task_id": task_id,
        "file_url": f"/static/uploads/{filename}",
        "message": f"已上传: {file.filename}",
    })


@app.post("/api/tasks/{task_id}/steps/{step_id}")
async def api_run_task_step(task_id: str, step_id: int):
    """
    分步执行第 step_id 步（1=质检 2=器官 3=检测 4=性质 5=亚型）。
    返回该步 event；第 5 步完成后自动把整条分析存入历史记录并返回 record_id。
    """
    task = _TASKS.get(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在或已过期，请重新上传"}, status_code=404)
    loop = asyncio.get_event_loop()
    event = await loop.run_in_executor(
        executor, _run_with_gpu_lock, f"step_{step_id}",
        engine.run_step, step_id, task["path"], RESULTS_DIR,
    )
    task["events"].append(event)
    record_id = task.get("record_id")
    # 每完成一步即落库：第 1 步完成创建记录，之后逐步更新。
    # 即便后续步骤中断，本次诊断也会保留在历史中。
    if event.get("status") == "done":
        try:
            if record_id is None:
                record_id = _save_record("single", task["filename"], task["events"])
                task["record_id"] = record_id
            else:
                _update_record_events(record_id, task["events"])
        except Exception as e:
            print(f"[History] 保存记录失败: {e}")
    payload = json.dumps({"event": event, "record_id": record_id},
                         ensure_ascii=False, cls=_NumpyEncoder)
    return JSONResponse(content=json.loads(payload))


@app.get("/api/tasks/{task_id}")
async def api_get_task(task_id: str):
    """读取分步任务当前状态（只读）：供拆分后的 6 个独立页面刷新/跨页恢复。

    返回每个步骤的最新一次事件（重跑以最新为准）；第 6 步 AI 报告文本
    在服务端按 record_id 从历史库附带返回，刷新报告页无需重复调用 LLM。
    """
    task = _TASKS.get(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在或已过期，请重新上传"}, status_code=404)
    steps = {}
    for evt in task.get("events", []):
        sid = evt.get("step_id")
        if isinstance(sid, int) and 1 <= sid <= 5:
            steps[str(sid)] = evt
    record_id = task.get("record_id")
    report_text = ""
    if record_id:
        try:
            row = _get_record(record_id)
            if row and row["report"]:
                report_text = row["report"]
        except Exception:
            pass
    file_url = f"/static/uploads/{os.path.basename(task['path'])}"
    payload = json.dumps({
        "task_id": task_id,
        "filename": task.get("filename"),
        "file_url": file_url,
        "description": task.get("description", ""),
        "record_id": record_id,
        "steps": steps,
        "report": report_text,
    }, ensure_ascii=False, cls=_NumpyEncoder)
    return JSONResponse(content=json.loads(payload))


@app.post("/api/tasks/{task_id}/warmup")
async def api_warmup(task_id: str):
    """预热全部模型（常驻模式），使后续分步分析每步秒开。"""
    task = _TASKS.get(task_id)
    if task is None:
        return JSONResponse({"error": "任务不存在或已过期，请重新上传"}, status_code=404)
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(executor, _run_with_gpu_lock, "warmup", engine.warm_up)
    return JSONResponse({"status": "warmed"})


# ============================================================
# 单入口流水线 API（SSE 流式推送）——多图模式与兼容接口
# ============================================================

@app.post("/api/pipeline")
async def api_pipeline(file: UploadFile = File(...)):
    """
    统一五级流水线入口

    上传一张图片 → 依次执行 Step 0~4 → SSE 实时推送每步进度和结果
    """
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    # 使用线程安全的 queue.Queue 替代 asyncio.Queue
    # 避免工作线程与主事件循环之间的跨线程通信问题
    event_queue = queue.Queue()
    main_loop = asyncio.get_event_loop()

    def progress_callback(event: dict):
        """由 engine 在工作线程中调用，放入线程安全队列"""
        event_queue.put(event)

    async def event_generator():
        """SSE 生成器"""
        # 先发送 init 事件
        yield _sse_json({
            "step_id": -1, "step_name": "init", "status": "started",
            "progress": 0,
            "data": {"file_url": f"/static/uploads/{filename}"},
            "message": f"开始分析: {file.filename}",
        })

        # 启动推理（在工作线程中运行）
        future = main_loop.run_in_executor(
            executor,
            _run_with_gpu_lock,
            "single_pipeline",
            engine.run_full_pipeline,
            filepath, RESULTS_DIR, progress_callback,
        )

        # 轮询 thread-safe 队列，推送给前端
        finished = False
        while not finished:
            try:
                event = await main_loop.run_in_executor(
                    None, event_queue.get, True, 1.0  # timeout=1s
                )
                yield _sse_json(event)
            except queue.Empty:
                if future.done():
                    finished = True

        # 检查是否有未取完的事件
        while not event_queue.empty():
            try:
                event = event_queue.get_nowait()
                yield _sse_json(event)
            except queue.Empty:
                break

        # 确保 future 完成（捕获异常）
        try:
            events = await future
        except Exception as e:
            traceback.print_exc()
            yield _sse_json({
                "step_id": -1, "step_name": "pipeline", "status": "error",
                "progress": 1,
                "data": {
                    "error_message": str(e),
                    "error_type": type(e).__name__,
                    "failed_step_id": -1,
                    "failed_step_name": "pipeline",
                },
                "message": f"流水线异常: {str(e)}",
            })
            events = None

        if events is not None:
            record_id = None
            try:
                record_id = _save_record("single", os.path.basename(filepath), events)
            except Exception as e:
                print(f"[History] 保存记录失败: {e}")
            yield _sse_json({
                "step_id": -1, "step_name": "pipeline", "status": "done",
                "progress": 1,
                "data": {"record_id": record_id},
                "message": "分析完成，已保存到历史记录",
            })

        # 完成信号
        yield "data: [DONE]\n\n"

    return _sse_response(event_generator())


@app.post("/api/multi-patch-pipeline")
async def api_multi_patch_pipeline(files: list[UploadFile] = File(...)):
    """
    多 patch 分析入口。

    前端可一次上传多张小图，模拟 WSI 初步切割后的 patch 集合。系统对每个
    patch 依次执行现有五级流水线，并在最后返回跨 patch 的综合汇总结果。
    """
    saved_paths = []
    patch_names = []
    patch_urls = []

    for idx, upload in enumerate(files):
        original_name = os.path.basename(upload.filename or f"patch_{idx + 1}.png")
        file_ext = os.path.splitext(original_name)[1] or ".png"
        unique_id = uuid.uuid4().hex
        filename = f"{unique_id}_{idx + 1}{file_ext}"
        filepath = os.path.join(UPLOADS_DIR, filename)
        with open(filepath, "wb") as buffer:
            shutil.copyfileobj(upload.file, buffer)
        saved_paths.append(filepath)
        patch_names.append(original_name)
        patch_urls.append(f"/static/uploads/{filename}")

    event_queue = queue.Queue()
    main_loop = asyncio.get_event_loop()

    def progress_callback(event: dict):
        event_queue.put(event)

    async def event_generator():
        yield _sse_json({
            "step_id": 0,
            "step_name": "multi_patch_init",
            "status": "started",
            "progress": 0,
            "data": {
                "event_type": "multi_init",
                "total_patches": len(saved_paths),
                "patches": [
                    {
                        "patch_index": idx + 1,
                        "patch_name": patch_names[idx],
                        "patch_url": patch_urls[idx],
                    }
                    for idx in range(len(saved_paths))
                ],
            },
            "message": f"已上传 {len(saved_paths)} 个 patch，准备开始多 patch 分析",
        })

        future = main_loop.run_in_executor(
            executor,
            _run_with_gpu_lock,
            "multi_patch_pipeline",
            engine.run_multi_patch_pipeline,
            saved_paths, RESULTS_DIR, patch_names, patch_urls, progress_callback,
        )

        finished = False
        while not finished:
            try:
                event = await main_loop.run_in_executor(
                    None, event_queue.get, True, 1.0
                )
                yield _sse_json(event)
            except queue.Empty:
                if future.done():
                    finished = True

        while not event_queue.empty():
            try:
                event = event_queue.get_nowait()
                yield _sse_json(event)
            except queue.Empty:
                break

        try:
            events = await future
        except Exception as e:
            traceback.print_exc()
            yield _sse_json({
                "step_id": -1,
                "step_name": "multi_patch_pipeline",
                "status": "error",
                "progress": 1,
                "data": {
                    "error_message": str(e),
                    "error_type": type(e).__name__,
                    "failed_step_id": -1,
                    "failed_step_name": "multi_patch_pipeline",
                },
                "message": f"多 patch 流水线异常: {str(e)}",
            })
            events = None

        if events is not None:
            record_id = None
            try:
                names = ",".join(os.path.basename(p) for p in saved_paths)
                record_id = _save_record("multi", names[:200], events)
            except Exception as e:
                print(f"[History] 保存记录失败: {e}")
            yield _sse_json({
                "step_id": -1, "step_name": "multi_patch_pipeline", "status": "done",
                "progress": 1,
                "data": {"record_id": record_id},
                "message": "分析完成，已保存到历史记录",
            })

        yield "data: [DONE]\n\n"

    return _sse_response(event_generator())

# ============================================================
# 报告生成 API
# ============================================================

@app.post("/api/report")
async def api_report(request: Request):
    """
    接收五步检测结果 + 病情描述，调用本地 LLM 生成病理报告
    """
    print(f">>> /api/report 收到请求 <<<")  # 收到请求的第一时间打印
    body = await request.json()
    description = body.get("description", "")
    results = body.get("results", [])
    record_id = body.get("record_id")
    llm_results = _strip_llm_image_hints(results)
    print(f">>> description={description[:50]}... results={len(results)}条 <<<")

    async def event_generator():
        yield _sse_json({
            "step_id": 6, "step_name": "生成分析报告", "status": "running",
            "progress": 1.0, "data": {},
            "message": "正在调用本地 LLM 生成报告...",
        })

        try:
            print("[API] /api/report 收到请求，description长度:", len(description), "results数量:", len(results))
            loop = asyncio.get_event_loop()
            report = await loop.run_in_executor(
                report_executor,
                _run_with_gpu_lock,
                "report_generation",
                ReportGenerator.generate,
                description, llm_results,
            )
            _update_record_report(record_id, description, report)

            yield _sse_json({
                "step_id": 6, "step_name": "生成分析报告", "status": "done",
                "progress": 1.0,
                "data": {"report": report, "mode": "llm"},
                "message": "报告生成完成",
            })
        except Exception as e:
            traceback.print_exc()
            yield _sse_json({
                "step_id": 6, "step_name": "生成分析报告", "status": "error",
                "progress": 1.0,
                "data": {},
                "message": f"LLM 报告生成失败: {str(e)}",
            })

        yield "data: [DONE]\n\n"

    return _sse_response(event_generator())


# ============================================================
# 保留旧 API（向后兼容，供单独页面使用）
# ============================================================

@app.post("/api/detect")
async def api_detect(file: UploadFile = File(...)):
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    roi_img_name = f"roi_{unique_id}.png"
    roi_img_path = os.path.join(RESULTS_DIR, roi_img_name)
    num_rois = engine.process_roi(filepath, roi_img_path)

    return JSONResponse({
        "status": "success",
        "roi_image": f"/static/results/{roi_img_name}",
        "num_rois": int(num_rois)
    })

@app.post("/api/organ")
async def api_organ(file: UploadFile = File(...)):
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    vit_chart_name = f"vit_{unique_id}.png"
    vit_chart_path = os.path.join(RESULTS_DIR, vit_chart_name)
    top_organ, top_prob = engine.predict_organ(filepath, vit_chart_path)

    return JSONResponse({
        "status": "success",
        "vit_chart": f"/static/results/{vit_chart_name}",
        "top_organ": top_organ,
        "top_prob": f"{top_prob:.1%}"
    })

@app.post("/api/nature")
async def api_nature(file: UploadFile = File(...)):
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    nature_chart_name = f"nature_{unique_id}.png"
    nature_chart_path = os.path.join(RESULTS_DIR, nature_chart_name)
    top_nature, top_prob = engine.predict_nature(filepath, nature_chart_path)

    return JSONResponse({
        "status": "success",
        "nature_chart": f"/static/results/{nature_chart_name}",
        "top_nature": top_nature,
        "top_prob": f"{top_prob:.1%}"
    })

@app.post("/api/subtype")
async def api_subtype(file: UploadFile = File(...)):
    file_ext = os.path.splitext(file.filename)[1] or ".png"
    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}{file_ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    subtype_chart_name = f"subtype_{unique_id}.png"
    subtype_chart_path = os.path.join(RESULTS_DIR, subtype_chart_name)
    top_subtype, top_prob = engine.predict_subtype(filepath, subtype_chart_path)

    return JSONResponse({
        "status": "success",
        "subtype_chart": f"/static/results/{subtype_chart_name}",
        "top_subtype": top_subtype,
        "top_prob": f"{top_prob:.1%}"
    })


# ============================================================
# 新增页面路由（BC 融合主题）
# ============================================================

@app.get("/explorer")
async def read_explorer(request: Request):
    return templates.TemplateResponse(request=request, name="explorer.html")


@app.get("/models")
async def read_models(request: Request):
    return templates.TemplateResponse(request=request, name="models.html")


@app.get("/report")
async def read_report(request: Request):
    return templates.TemplateResponse(request=request, name="report.html")


@app.get("/datasets")
async def read_datasets(request: Request):
    return templates.TemplateResponse(request=request, name="datasets.html")


# ============================================================
# 新增数据 API（仪表盘 / 3D 浏览器 / 最新报告）
# ============================================================

@app.get("/api/stats")
async def api_stats():
    """系统统计：历史记录聚合 + 上传图数量，供总览仪表盘使用。"""
    rows = _list_records(limit=1000)
    total = len(rows)
    single = sum(1 for r in rows if r["mode"] == "single")
    multi = total - single
    with_report = sum(1 for r in rows if r["report"])
    organ_counter = {}
    recent = []
    for r in rows:
        events = _load_events(r)
        s = _summarize(events)
        if s["organ_cn"]:
            organ_counter[s["organ_cn"]] = organ_counter.get(s["organ_cn"], 0) + 1
        if len(recent) < 6:
            recent.append({
                "id": r["id"],
                "created_at": r["created_at"],
                "mode": r["mode"],
                "filename": r["filename"],
                "organ_cn": s["organ_cn"] or "-",
                "nature_cn": s["nature_cn"] or "-",
                "usable": s["usable"] if s["usable"] is not None else "-",
                "has_report": bool(r["report"]),
            })
    organs = sorted(
        ({"name": k, "count": v} for k, v in organ_counter.items()),
        key=lambda x: -x["count"],
    )[:8]
    try:
        uploads = len([f for f in os.listdir(UPLOADS_DIR)
                       if os.path.isfile(os.path.join(UPLOADS_DIR, f))])
    except Exception:
        uploads = 0
    return JSONResponse({
        "total": total, "single": single, "multi": multi,
        "withReport": with_report, "organs": organs,
        "recent": recent, "uploads": uploads,
    })


@app.get("/api/explorer-images")
async def api_explorer_images(limit: int = 48):
    """返回 uploads 目录下最新的真实图片，供 3D 病理浏览器使用。"""
    exts = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
    items = []
    try:
        files = [f for f in os.listdir(UPLOADS_DIR)
                 if os.path.splitext(f)[1].lower() in exts]
        files.sort(key=lambda f: os.path.getmtime(os.path.join(UPLOADS_DIR, f)),
                   reverse=True)
        for f in files[:limit]:
            items.append({"url": f"/static/uploads/{f}", "name": f})
    except Exception as e:
        print(f"[Explorer] 读取 uploads 失败: {e}")
    return JSONResponse({"images": items, "count": len(items)})


@app.get("/api/latest-report")
async def api_latest_report():
    """返回最新一条含 AI 报告的历史记录，供 AI 诊断报告页使用。"""
    with _db() as conn:
        row = conn.execute(
            "SELECT * FROM records WHERE report IS NOT NULL AND report != '' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        return JSONResponse({"found": False})
    return JSONResponse({
        "found": True,
        "id": row["id"],
        "created_at": row["created_at"],
        "mode": row["mode"],
        "filename": row["filename"],
        "description": row["description"] or "",
        "report": row["report"],
    })


# ============================================================
# 手机扫码上传（局域网配对）
# ============================================================

# session -> {"images": [{"url","name"}, ...], "delivered": int}
# 一个配对会话内手机可连续上传多张，全部累积，轮询端按游标取走新图。
_MOBILE_SESSIONS = {}


def _lan_ip() -> str:
    """取本机局域网 IPv4（UDP 探测路由出口，不实际发包）。"""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except Exception:
        ip = "127.0.0.1"
    finally:
        s.close()
    return ip


@app.get("/api/lan-info")
async def api_lan_info():
    return JSONResponse({"ip": _lan_ip(), "port": 8001})


@app.get("/api/boot-id")
async def api_boot_id():
    """返回当前服务进程启动标识；服务重启后变化，前端据此强制重新登录。"""
    return JSONResponse({"bootId": SERVICE_BOOT_ID})


@app.get("/m")
async def read_mobile_upload(request: Request):
    """手机端上传页（扫码进入）。"""
    return templates.TemplateResponse(request=request, name="m.html")


@app.post("/api/mobile-upload")
async def api_mobile_upload(request: Request, session: str = ""):
    """手机端直传图像：原始字节 + X-File-Name 头，按 session 暂存供电脑端轮询。"""
    if not session:
        return JSONResponse({"ok": False, "error": "缺少 session"}, status_code=400)
    body = await request.body()
    if not body:
        return JSONResponse({"ok": False, "error": "空文件"}, status_code=400)
    name = request.headers.get("X-File-Name", "手机图像")
    try:
        from urllib.parse import unquote
        name = unquote(name)
    except Exception:
        pass
    ext = os.path.splitext(name)[1].lower()
    if ext not in {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff"}:
        ext = ".png"
    filename = f"mobile_{session}_{uuid.uuid4().hex[:8]}{ext}"
    filepath = os.path.join(UPLOADS_DIR, filename)
    with open(filepath, "wb") as f:
        f.write(body)
    url = f"/static/uploads/{filename}"
    # 同一会话累积多图（修复：旧实现用单槽位直接覆盖，后续图片会把前一张顶掉）
    slot = _MOBILE_SESSIONS.setdefault(session, {"images": [], "delivered": 0})
    slot["images"].append({"url": url, "name": name})
    if len(_MOBILE_SESSIONS) > 200:
        for key in list(_MOBILE_SESSIONS.keys())[:-200]:
            _MOBILE_SESSIONS.pop(key, None)
    print(f"[Mobile] 收到手机上传: {name} -> {filename} "
          f"(session={session}, 本会话累计 {len(slot['images'])} 张)")
    return JSONResponse({"ok": True, "url": url, "name": name,
                         "total": len(slot["images"])})


@app.get("/api/mobile-poll")
async def api_mobile_poll(session: str = ""):
    """电脑端轮询：返回该 session 自上次轮询以来新增的全部图像（游标递增，不丢图）。

    兼容旧契约：仅 1 张时同时带 url/name 字段；多张走 images 数组。
    会话保留（不再一次性 pop），手机可继续往同一会话追加图片。
    """
    slot = _MOBILE_SESSIONS.get(session)
    if not slot:
        return JSONResponse({"hasImage": False, "images": []})
    new_images = slot["images"][slot["delivered"]:]
    slot["delivered"] = len(slot["images"])
    if not new_images:
        return JSONResponse({"hasImage": False, "images": [],
                             "total": slot["delivered"]})
    resp = {
        "hasImage": True,
        "images": new_images,
        "total": slot["delivered"],
    }
    resp.update(new_images[0])  # url / name 兼容旧前端
    return JSONResponse(resp)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)
