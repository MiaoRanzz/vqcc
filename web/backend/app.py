"""Private VQCC HTTP service. Requests enqueue work; the existing runner executes it."""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime, timezone
import io
import json
import os
from pathlib import Path
import secrets
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from automation.jobs import Jobs, ControlError
from automation.runner import load_config
from web.backend.schemas import (SessionInput, JobInput, CancelInput, StopInput,
                                 ConfigInput, ActivateInput, ResearchInput)
from web.backend.read_model import ReadModel
from web.backend.event_feed import EventFeed
from web.backend.control_service import ResearchControl

ROOT = Path(__file__).resolve().parents[2]
PREFIX = '/api/v1'


def create_app(config_path=None, *, read_only=False, key_path=None):
    config_path = Path(config_path or os.environ.get('VQCC_CONFIG', ROOT / 'automation/config.json')).resolve()
    cfg = load_config(config_path)
    storage = Path(cfg['storage_root'])
    jobs = Jobs(config_path)
    reader = ReadModel(config_path, jobs=jobs)
    feed = EventFeed(storage)
    research_control = ResearchControl(storage)
    key_path = Path(key_path) if key_path else storage / 'console/session-key'
    if not key_path.exists():
        key_path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(key_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'w') as out:
            out.write(secrets.token_urlsafe(32) + '\n')
    bootstrap_key = key_path.read_text().strip()
    sessions = {}
    app = FastAPI(title='VQCC 私有控制台', version='0.1.0', docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.jobs, app.state.reader, app.state.feed = jobs, reader, feed
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', '[::1]', 'testserver'])

    def error(code, message, status=400, **fields):
        return JSONResponse({'code': code, 'message': message, 'field_errors': {},
                             'retryable': False, 'operation_id': None, 'current_revision': None,
                             **fields}, status_code=status)

    def secure_text_equal(left, right):
        """Compare user-controlled text without compare_digest's ASCII-only str limit."""
        return secrets.compare_digest(left.encode('utf-8'), right.encode('utf-8'))

    @app.exception_handler(ControlError)
    async def control_error(request, exc):
        return error(exc.code, exc.message, getattr(exc, 'status', 409),
                     field_errors=getattr(exc, 'field_errors', {}),
                     current_revision=getattr(exc, 'current_revision', None))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        return error('INVALID_PARAMETERS', '请求参数不符合接口定义', 422,
                     field_errors={'.'.join(map(str, e['loc'])): e['msg'] for e in exc.errors()})

    @app.exception_handler(FileNotFoundError)
    async def not_found(request, exc):
        return error('NOT_FOUND', '记录或报告尚未出现', 404)

    @app.exception_handler(KeyError)
    async def missing_record(request, exc):
        return error('NOT_FOUND', '记录或报告不存在', 404)

    @app.exception_handler(ValueError)
    async def invalid_value(request, exc):
        return error('INVALID_PARAMETERS', str(exc), 422)

    @app.middleware('http')
    async def session_boundary(request, call_next):
        path, method = request.url.path, request.method
        if path.startswith(PREFIX):
            origin = request.headers.get('origin')
            if origin and origin != f'{request.url.scheme}://{request.headers.get("host")}':
                return error('ORIGIN_REJECTED', '请从本机控制台发起请求', 403)
            login = path == PREFIX + '/session' and method == 'POST'
            if not login:
                token = request.cookies.get('vqcc_session')
                session = sessions.get(token)
                if session is None or session['expires'] <= time.time():
                    return error('SESSION_REQUIRED', '请先登录私有控制台', 401)
                request.state.session = session
                if method not in ('GET', 'HEAD'):
                    if not secure_text_equal(request.headers.get('x-csrf-token', ''), session['csrf_token']):
                        return error('CSRF_REQUIRED', '会话已变化，请刷新页面后重试', 403)
                    preview = path.endswith('/preview')
                    if read_only and method != 'DELETE' and not preview:
                        return error('READ_ONLY', '此实例为只读验收模式', 409)
                    if not preview and method != 'DELETE' and not request.headers.get('idempotency-key'):
                        return error('IDEMPOTENCY_KEY_REQUIRED', '写操作需要操作标识', 400)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'no-referrer'
        response.headers['Cache-Control'] = 'no-store' if path.startswith(PREFIX) else 'no-cache'
        return response

    @app.post(PREFIX + '/session')
    def login(body: SessionInput, request: Request):
        if not secure_text_equal(body.key, bootstrap_key):
            return error('INVALID_SESSION_KEY', '登录密钥不匹配', 401)
        token = secrets.token_urlsafe(32)
        session = {'csrf_token': secrets.token_urlsafe(24), 'expires': time.time() + 43200}
        sessions[token] = session
        response = JSONResponse({'csrf_token': session['csrf_token'], 'read_only': read_only})
        response.set_cookie('vqcc_session', token, httponly=True, samesite='strict',
                            secure=request.url.scheme == 'https', max_age=43200)
        return response

    @app.get(PREFIX + '/session')
    def session(request: Request):
        return {'csrf_token': request.state.session['csrf_token'], 'read_only': read_only}

    @app.delete(PREFIX + '/session')
    def logout(request: Request):
        sessions.pop(request.cookies.get('vqcc_session'), None)
        response = Response(status_code=204)
        response.delete_cookie('vqcc_session')
        return response

    def wrap(data):
        return reader.envelope(data)

    def operation_key(request):
        return request.headers['idempotency-key']

    @app.get(PREFIX + '/overview')
    def overview():
        return wrap(reader.overview())

    @app.get(PREFIX + '/tasks/history')
    def task_history(task: str | None = None):
        return wrap(reader.task_history(task=task))

    @app.get(PREFIX + '/jobs')
    def list_jobs(state: str | None = None, cursor: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)):
        return wrap(reader.list_jobs(state=state, cursor=cursor, limit=limit))

    @app.get(PREFIX + '/jobs/{job_id}')
    def get_job(job_id: str):
        return wrap(reader.job(job_id))

    @app.post(PREFIX + '/jobs/preview')
    def preview_job(body: JobInput):
        return wrap(jobs.preview(body.model_dump(exclude_none=True, by_alias=True)))

    @app.post(PREFIX + '/jobs', status_code=202)
    def enqueue_job(body: JobInput, request: Request):
        return jobs.enqueue(body.model_dump(exclude_none=True, by_alias=True), operation_key(request))

    @app.post(PREFIX + '/jobs/{job_id}/cancel-queued')
    def cancel_job(job_id: str, body: CancelInput, request: Request):
        return jobs.cancel(job_id, body.expected_state, body.revision, operation_key(request))

    @app.post(PREFIX + '/jobs/{job_id}/stop', status_code=202)
    def stop_job(job_id: str, body: StopInput, request: Request):
        return jobs.stop(job_id, body.run_id, body.revision, operation_key(request))

    @app.post(PREFIX + '/scheduler/{action}')
    def scheduler(action: str, request: Request):
        if action not in ('pause', 'resume', 'start', 'stop'):
            raise HTTPException(404)
        return jobs.scheduler(action, operation_key(request))

    @app.get(PREFIX + '/runs/{run_id}')
    def run(run_id: str):
        return wrap(reader.runs(run_id))

    @app.get(PREFIX + '/experiments')
    def experiments(task: str | None = None, validation: str | None = None,
                    cursor: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                    parent: str | None = None, generator_revision: str | None = None,
                    best: bool | None = None, query: str | None = None):
        return wrap(reader.experiments(task=task, validation=validation, cursor=cursor, limit=limit,
                                       parent=parent, generator_revision=generator_revision, best=best, query=query))

    @app.get(PREFIX + '/experiments/compare')
    def compare(ids: str, format: str | None = None):
        data = reader.compare(ids.split(','))
        if format == 'csv':
            items = data['items'] if isinstance(data, dict) else data
            stream = io.StringIO()
            fields = ['id', 'task', 'official_cost', 'validation_status', 'validation_reason', 'parent', 'parameters']
            writer = csv.DictWriter(stream, fields, extrasaction='ignore')
            writer.writeheader()
            for item in items:
                writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else
                                 ("'" + v if isinstance(v, str) and v.startswith(('=', '+', '-', '@')) else v)
                                 for k, v in item.items() if k in fields})
            return Response(stream.getvalue(), media_type='text/csv; charset=utf-8',
                            headers={'Content-Disposition': 'attachment; filename="vqcc-comparison.csv"'})
        return wrap(data)

    @app.get(PREFIX + '/experiments/{candidate_id}')
    def experiment(candidate_id: str):
        return wrap(reader.experiment(candidate_id))

    @app.get(PREFIX + '/experiments/{candidate_id}/export')
    def export(candidate_id: str):
        return Response(json.dumps(reader.experiment(candidate_id), ensure_ascii=False, indent=2),
                        media_type='application/json',
                        headers={'Content-Disposition': 'attachment; filename="vqcc-experiment.json"'})

    @app.get(PREFIX + '/research')
    def research():
        return wrap(reader.research())

    @app.post(PREFIX + '/research/{research_id}/update')
    def update_research(research_id: str, body: ResearchInput, request: Request):
        if research_id not in {item['id'] for item in reader.research()['items']}:
            raise FileNotFoundError(research_id)
        for candidate_id in body.experiment_ids:
            reader.experiment(candidate_id)
        return research_control.update(research_id, body.model_dump(), operation_key(request))

    @app.get(PREFIX + '/submissions')
    def submissions():
        return wrap(reader.submissions())

    @app.get(PREFIX + '/config')
    def config():
        return wrap(jobs.config_view())

    @app.post(PREFIX + '/config/preview')
    def config_preview(body: ConfigInput):
        return wrap(jobs.config_preview(body.config))

    @app.post(PREFIX + '/config/revisions')
    def config_save(body: ConfigInput, request: Request):
        return jobs.save_config(body.config, body.expected_revision, operation_key(request))

    @app.post(PREFIX + '/config/activate')
    def config_activate(body: ActivateInput, request: Request):
        return jobs.activate_config(body.revision, body.expected_revision, operation_key(request))

    @app.get(PREFIX + '/parameter-schemas')
    def parameters(generator_revision: str | None = None):
        schema = jobs.parameter_schemas()
        if generator_revision and generator_revision != schema['generator_revision']:
            raise ControlError('CONFIG_CONFLICT', '生成器版本已变化，请刷新参数定义')
        return wrap(schema)

    @app.get(PREFIX + '/usage')
    def usage(date: str | None = None):
        return wrap(reader.usage(date))

    @app.get(PREFIX + '/artifacts/{artifact_id}')
    def artifact(artifact_id: str):
        return Response(reader.artifacts.read(artifact_id), media_type='text/plain; charset=utf-8',
                        headers={'Content-Disposition': 'inline'})

    @app.get(PREFIX + '/openapi.json')
    def openapi():
        return app.openapi()

    @app.get(PREFIX + '/events')
    async def events(request: Request, run_id: str | None = None, after: str | None = None):
        async def stream():
            cursor = request.headers.get('last-event-id') or after
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                if (request.state.session['expires'] <= time.time()
                        or request.cookies.get('vqcc_session') not in sessions):
                    break
                batch, resync, newest = await asyncio.to_thread(feed.replay, cursor, run_id)
                if resync:
                    yield 'event: resync\ndata: {"reason":"cursor_expired"}\n\n'
                for event_id, event in batch:
                    yield f'id: {event_id}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n'
                cursor = newest or cursor
                if time.monotonic() - heartbeat >= 15:
                    yield ': heartbeat\n\n'
                    heartbeat = time.monotonic()
                await asyncio.sleep(1)
        return StreamingResponse(stream(), media_type='text/event-stream',
                                 headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

    dist = ROOT / 'web/frontend/dist'
    if dist.is_dir():
        app.mount('/', StaticFiles(directory=dist, html=True), name='console')
    return app
