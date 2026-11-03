"""Persistent per-task Top-3 branches followed by combined optimization.

The supervised optimization agent performs the experiments. This ledger selects
and pins the parents, enforces phase order, and records completed evidence.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import uuid

try:
    from .pipeline import Pipeline, PipelineError, TASKS, positive, read_json, sha256, write_json
except ImportError:
    from pipeline import Pipeline, PipelineError, TASKS, positive, read_json, sha256, write_json


class Search:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.path = pipeline.storage / 'research/top3.json'

    def _load(self):
        return read_json(self.path) if self.path.exists() else {
            'schema': 1, 'strategy': 'top3_independent_then_combined', 'width': 3, 'tasks': {}}

    def _save(self, state):
        state['updated_at'] = self.pipeline.now_string()
        write_json(self.path, state)

    def _new_cycle(self, task):
        ranking = self.pipeline.top_candidates(task)
        roots = ranking['candidates']
        return {
            'cycle_id': f'{self.pipeline.now().strftime("%Y%m%dT%H%M%S")}-{task}-{uuid.uuid4().hex[:8]}',
            'task': task, 'created_at': self.pipeline.now_string(),
            'status': 'active' if roots else 'waiting_for_verified_candidates',
            'roots': roots, 'ranking_exclusions': ranking['excluded'],
            'shortfall': 3 - len(roots),
            'steps': [dict(key=f'top{index}', phase='independent', parents=[root['id']], status='pending')
                      for index, root in enumerate(roots, 1)] +
                     [dict(key='combined', phase='combined', parents=[root['id'] for root in roots],
                           status='blocked' if len(roots) >= 2 else 'unavailable',
                           reason=None if len(roots) >= 2 else 'fewer_than_two_distinct_verified_parents')],
        }

    def plan(self, task=None):
        self.pipeline.active()
        with self.pipeline.locked():
            state = self._load()
            names = [task] if task else TASKS
            # A general run finishes the current round across all three tasks;
            # a fast task cannot repeatedly refresh while another is untouched.
            refresh = all(state['tasks'].get(name, {}).get('status') in
                          {'completed', 'waiting_for_verified_candidates'} for name in names)
            for name in names:
                previous = state['tasks'].get(name)
                if (not previous or previous['status'] == 'waiting_for_verified_candidates'
                        or previous['status'] == 'completed' and refresh):
                    if previous and previous['status'] == 'completed':
                        write_json(self.path.parent / 'top3-history' / (previous['cycle_id'] + '.json'), previous)
                    state['tasks'][name] = self._new_cycle(name)
                elif previous['status'] == 'active':
                    self._check_roots(previous)
            self._save(state)
            return state

    def _outcome(self, cid, task, parents):
        path, candidate = self.pipeline.candidate(cid)
        ancestry = candidate.get('parents') or ([candidate['parent']] if candidate.get('parent') else [])
        if candidate['task'] != task or set(ancestry) != set(parents) or cid in parents:
            raise PipelineError('Result must be a new same-task candidate with all and only the step parents')
        if candidate.get('verification'):
            _, _, report = self.pipeline.verified(cid)
            record = candidate['verification']
        else:
            official = [run for run in candidate.get('runs', []) if run.get('kind') == 'official']
            if not official or not official[-1].get('finished_at') or official[-1].get('passed') is not False:
                raise PipelineError('Result lacks a completed official validation; unfinished work stays pending')
            record = official[-1]
            report = self.pipeline._attested_report(path, candidate, record)
            if report.get('status') != 'FAIL':
                raise PipelineError('Failed attempt has no conclusive official FAIL report')
        return {'id': cid, 'status': report['status'],
                'cost': positive(report['score']) if report['status'] == 'PASS' else None,
                'report': record['report'], 'report_sha256': record['report_sha256'],
                'artifacts': record['artifacts']}

    def _check_parent(self, parent):
        _, candidate, _ = self.pipeline.verified(parent['id'])
        evidence = candidate['verification']
        if evidence['artifacts'] != parent['artifacts'] or evidence['report_sha256'] != parent['report_sha256']:
            raise PipelineError('Pinned parent evidence changed; restore the original parent before continuing this cycle')

    def _check_roots(self, cycle):
        for root in cycle['roots']:
            self._check_parent(root)

    def record(self, task, cycle_id, step_key, candidates=(), evidence=None):
        self.pipeline.active()
        with self.pipeline.locked():
            state = self._load()
            cycle = state['tasks'].get(task)
            if not cycle or cycle['cycle_id'] != cycle_id:
                raise PipelineError('Search cycle changed or is missing; read the current plan')
            step = next((item for item in cycle['steps'] if item['key'] == step_key), None)
            if step is None or step['status'] != 'pending':
                raise PipelineError('Search step is not pending; finish all independent branches before combining')
            self._check_roots(cycle)
            for parent in step.get('sources', []):
                self._check_parent(parent)
            results = [self._outcome(cid, task, step['parents']) for cid in dict.fromkeys(candidates)]
            proof = None
            if evidence is not None:
                path = Path(evidence).resolve()
                if not path.is_relative_to(self.pipeline.storage):
                    raise PipelineError('Screen evidence must be stored under the configured artifact root')
                document = read_json(path)
                if (document.get('task') != task or document.get('cycle_id') != cycle_id
                        or document.get('step') != step_key or set(document.get('parents', [])) != set(step['parents'])
                        or document.get('conclusion') not in {'infeasible', 'no_change'}
                        or not document.get('reason') or not document.get('measurements')):
                    raise PipelineError('Screen evidence needs matching task/cycle/step/parents, a concrete conclusion, reason and measurements')
                proof = {'path': str(path), 'sha256': sha256(path), 'conclusion': document['conclusion']}
            if not results and not proof:
                raise PipelineError('Completion needs officially checked candidates or measured infeasibility/no-change evidence')
            step.update(status='completed', completed_at=self.pipeline.now_string(), results=results, evidence=proof)
            branches = [item for item in cycle['steps'] if item['phase'] == 'independent']
            combined = cycle['steps'][-1]
            if combined['status'] == 'blocked' and all(item['status'] == 'completed' for item in branches):
                sources = []
                for root, branch in zip(cycle['roots'], branches):
                    # The original stays eligible when a branch fails or gets worse.
                    choices = [root] + [item for item in branch['results'] if item['status'] == 'PASS']
                    winner = min(choices, key=lambda item: item['cost'])
                    self._check_parent(winner)
                    sources.append(winner)
                combined.update(status='pending', parents=[parent['id'] for parent in sources], sources=sources)
            if all(item['status'] in {'completed', 'unavailable'} for item in cycle['steps']):
                cycle.update(status='completed', completed_at=self.pipeline.now_string())
            self._save(state)
            return cycle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default=str(Path(__file__).with_name('config.json')))
    commands = parser.add_subparsers(dest='command', required=True)
    plan = commands.add_parser('plan', help='Resume frozen cycles; refresh Top-3 only after combined work completes')
    plan.add_argument('--task', choices=TASKS)
    record = commands.add_parser('record', help='Complete one branch or combined step with exact evidence')
    record.add_argument('task', choices=TASKS)
    record.add_argument('step', choices=['top1', 'top2', 'top3', 'combined'])
    record.add_argument('--cycle', required=True)
    record.add_argument('--candidate', action='append', default=[])
    record.add_argument('--evidence', type=Path)
    args = parser.parse_args()
    search = Search(Pipeline(args.config))
    result = search.plan(args.task) if args.command == 'plan' else search.record(
        args.task, args.cycle, args.step, args.candidate, args.evidence)
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (PipelineError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
