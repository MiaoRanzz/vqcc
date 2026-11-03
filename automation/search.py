"""Persistent per-task Top-3 branches followed by combined optimization.

The supervised optimization agent performs the experiments. This ledger selects
and pins the parents, enforces phase order, and records completed evidence.
"""
from __future__ import annotations

import argparse
import json
import math
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
        self.frontier_path = pipeline.storage / 'research/frontier.json'

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
                    leader = self._preempting_leader(name, previous)
                    if leader:
                        previous.update(status='preempted', preempted_at=self.pipeline.now_string(),
                                        preempted_by={'id': leader['id'], 'cost': leader['cost']})
                        write_json(self.path.parent / 'top3-history' / (previous['cycle_id'] + '.json'), previous)
                        state['tasks'][name] = self._new_cycle(name)
                        state['tasks'][name]['replaces'] = {'cycle_id': previous['cycle_id'], 'reason': 'preempted_by_leader',
                                                            'leader': previous['preempted_by']}
            state['allocation'] = self._allocation()
            self._save(state)
            return state

    def _preempting_leader(self, task, cycle):
        """A verified result far below every root refreshes this task before the round ends."""
        fraction = float(self.pipeline.config.get('top3_preempt_fraction', 0))
        if fraction <= 0 or not cycle['roots']:
            return None
        ranking = self.pipeline.top_candidates(task, limit=1)['candidates']
        if not ranking or ranking[0]['id'] in {root['id'] for root in cycle['roots']}:
            return None
        leader = ranking[0]
        return leader if leader['cost'] < min(root['cost'] for root in cycle['roots']) * (1 - fraction) else None

    def _allocation(self):
        """Order tasks by log-score headroom to the best known public cost."""
        frontier = read_json(self.frontier_path) if self.frontier_path.exists() else {}
        rows = []
        for task in TASKS:
            best = self.pipeline.state.get('best', {}).get(task)
            ours = public = None
            if best:
                try:
                    ours = positive(self.pipeline.verified(best)[2]['score'])
                except (PipelineError, OSError, ValueError, KeyError):
                    ours = None
            if task in frontier:
                public = frontier[task]['cost']
            # log(ours/public)/3 is the combined-score gain from matching the public cost.
            headroom = math.log(ours / public) / 3 if ours and public else None
            rows.append({'task': task, 'ours': ours, 'public_best': public,
                         'public_source': frontier.get(task, {}).get('source'), 'log_score_headroom': headroom,
                         'status': 'unknown_frontier' if public is None else 'behind' if headroom > 0 else 'leading'})
        order = {'behind': 0, 'unknown_frontier': 1, 'leading': 2}
        return sorted(rows, key=lambda row: (order[row['status']], -(row['log_score_headroom'] or 0)))

    def frontier(self, task=None, cost=None, source=None, basis=None):
        """Record the best known public per-task cost; without a cost, report the allocation."""
        with self.pipeline.locked():
            if task is not None:
                if not source or basis not in {'local_official', 'claimed'}:
                    raise PipelineError('A frontier entry needs its source and basis local_official or claimed')
                frontier = read_json(self.frontier_path) if self.frontier_path.exists() else {}
                entry = {'cost': positive(cost), 'source': source, 'basis': basis, 'observed_at': self.pipeline.now_string()}
                current = frontier.get(task)
                history = (current or {}).get('history', []) + [entry]
                frontier[task] = {**(entry if current is None or entry['cost'] < current['cost'] else
                                     {key: current[key] for key in ('cost', 'source', 'basis', 'observed_at')}),
                                  'history': history[-50:]}
                write_json(self.frontier_path, frontier)
            return {'allocation': self._allocation()}

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
    frontier = commands.add_parser('frontier', help='Record a public per-task cost, or show the headroom allocation')
    frontier.add_argument('task', nargs='?', choices=TASKS)
    frontier.add_argument('--cost', type=float)
    frontier.add_argument('--source', help='Notebook/dataset ref and version')
    frontier.add_argument('--basis', choices=['local_official', 'claimed'])
    args = parser.parse_args()
    search = Search(Pipeline(args.config))
    if args.command == 'frontier' and (args.task is None) != (args.cost is None):
        parser.error('frontier takes both TASK and --cost, or neither')
    result = (search.plan(args.task) if args.command == 'plan' else
              search.frontier(args.task, args.cost, args.source, args.basis) if args.command == 'frontier' else
              search.record(args.task, args.cycle, args.step, args.candidate, args.evidence))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (PipelineError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
