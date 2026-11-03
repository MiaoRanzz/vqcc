"""Run the private Web process independently of the computation supervisor."""
import argparse
import fcntl
import json
import os
from pathlib import Path

from automation.jobs import Jobs
from automation.runner import load_config, verify_environment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'serve', 'schema'])
    parser.add_argument('--config', type=Path, default=Path('automation/config.json'))
    parser.add_argument('--port', type=int, default=8766)
    parser.add_argument('--read-only', action='store_true')
    parser.add_argument('--key-path', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    cfg = load_config(args.config)
    verify_environment(cfg)
    if args.command == 'init':
        Jobs(args.config, initialize=True)
        print('控制状态已初始化；Web 与调度器仍需分别启动。')
        return
    from web.backend.app import create_app
    app = create_app(args.config, read_only=args.read_only, key_path=args.key_path)
    if args.command == 'schema':
        target = args.output or Path('web/openapi.json')
        target.write_text(json.dumps(app.openapi(), ensure_ascii=False, indent=2) + '\n')
        return
    import uvicorn
    console = Path(cfg['storage_root']) / 'console'
    console.mkdir(parents=True, exist_ok=True)
    with (console / 'web.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('该数据目录已有 Web 实例。')
        print(f'控制台 http://127.0.0.1:{args.port}；登录密钥文件：{args.key_path or console / "session-key"}')
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False, timeout_graceful_shutdown=3)


if __name__ == '__main__':
    main()
