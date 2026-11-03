"""One supervised local operation. No model invocation or background workers."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from events import emit
from pipeline import Pipeline, write_json
from runner import redact
from model_config import generator_revision

ROOT = Path(__file__).resolve().parents[1]


def run(job, config_path, run_dir):
    pipeline = Pipeline(config_path)
    kind = job['kind']
    cid = job.get('candidate_id')
    def stage(name, text, **extra):
        emit(run_dir, 'stage.started', job_id=job['job_id'], stage=name, message=text, **extra)
    if kind == 'local_experiment':
        if job['generator_revision'] != generator_revision():
            raise ValueError('Generator changed after dispatch; create a new job with current source')
        if job['task'] == 'dfthcsos':
            with (ROOT / 'sample_submission/dfthcsos/submission.npz').open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != job['dataset_sha256']:
                    raise ValueError('Dataset changed after preview; create a new job with current data')
        stage('create', '创建隔离候选')
        candidate = pipeline.create(job['task'], job['hypothesis'],
                                    'Web console; generator ' + job['generator_revision'],
                                    'Repository generator; preserve upstream attribution',
                                    job.get('parent_candidate_id'))
        cid = candidate['id']
        write_json(run_dir / 'candidate-link.json', {'candidate_id': cid})
        candidate_dir = Path(candidate['output']).parent
        write_json(candidate_dir / 'console-job.json', job)
        parameters = candidate_dir / 'parameters.json'
        write_json(parameters, job['parameters'])
        command = [sys.executable, str(ROOT / 'generators/generate.py'), job['task'],
                   '--output-dir', candidate['output'], '--params', str(parameters)]
        if job['task'] == 'dfthcsos':
            command += ['--source-npz', str(ROOT / 'sample_submission/dfthcsos/submission.npz')]
        stage('generate', '生成与初筛', candidate_id=cid)
        subprocess.run(command, check=True)
        # Also enforce this for queued jobs created before validation was mandatory.
        stage('official_validate', '开始完整官方验证', candidate_id=cid)
        result = pipeline.validate(cid)
    elif kind == 'local_validate':
        stage('robustness' if job.get('robustness') else 'official_validate', '开始独立复核' if job.get('robustness') else '开始完整官方验证', candidate_id=cid)
        result = pipeline.validate(cid, job.get('robustness', False))
    elif kind == 'local_promote':
        stage('promote', '检查证据并请求晋级', candidate_id=cid)
        result = pipeline.promote(cid)
    elif kind == 'prepare_preview':
        stage('prepare', '检查证据并准备组合预览')
        result = pipeline.prepare()
    else:
        raise ValueError(f'Unsupported local job kind: {kind}')
    write_json(run_dir / 'operation-result.json', result)
    emit(run_dir, 'stage.completed', job_id=job['job_id'], stage=kind, message='本地操作结束', candidate_id=cid)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--config', required=True, type=Path)
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    job = json.loads(args.job.read_text())
    try:
        result = run(job, args.config, args.run_dir)
    except Exception as error:
        (args.run_dir / 'report.md').write_text(
            f"# 本地操作失败\n\n作业：{job['job_id']}\n\n"
            f"原因：{redact(str(error))}\n\n未完成的验证不算 PASS；已有证据保留。\n")
        raise
    (args.run_dir / 'report.md').write_text(
        f"# 本地操作结束\n\n作业：{job['job_id']}\n\n"
        "执行结束与科学验证结论分别记录；本次操作结果：\n\n```json\n"
        + redact(json.dumps(result, ensure_ascii=False, indent=2)) + "\n```\n")
    print(json.dumps(result, ensure_ascii=False))
