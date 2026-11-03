"""Persistent per-task Top-3 branches followed by combined optimization.

The supervised optimization agent performs the experiments. This ledger selects
and pins the parents, enforces phase order, and records completed evidence.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta
import json
import math
from pathlib import Path
import sys
import uuid

try:
    from .pipeline import Pipeline, PipelineError, TASKS, positive, read_json, sha256, write_json
except ImportError:
    from pipeline import Pipeline, PipelineError, TASKS, positive, read_json, sha256, write_json


# Observed milestones (references/tasks.md); the final deadline comes from config.
MILESTONES = ('2026-11-21T07:59:00+08:00', '2027-01-05T07:59:00+08:00')
CLOSED_HYPOTHESIS = {'done', 'completed', 'closed', 'rejected', 'abandoned', 'superseded', 'infeasible'}
# Allocation shares: every task keeps a floor; the rest follows public headroom.
SHARE_FLOOR = 0.15
# Two-day review periods (Asia/Shanghai calendar days), labelled by start date.
REVIEW_ANCHOR = date(2026, 11, 1)


class Search:
    def __init__(self, pipeline):
        self.pipeline = pipeline
        self.path = pipeline.storage / 'research/top3.json'
        self.frontier_path = pipeline.storage / 'research/frontier.json'
        self.handoff_path = pipeline.storage / 'research/handoff.json'
        self.hypotheses_path = pipeline.storage / 'research/hypotheses.json'

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
        rows.sort(key=lambda row: (order[row['status']], -(row['log_score_headroom'] or 0)))
        # Suggested split of run time, validation slots and subagent effort.
        behind = {row['task']: row['log_score_headroom'] for row in rows if row['status'] == 'behind'}
        unknown = [row['task'] for row in rows if row['status'] == 'unknown_frontier']
        spare = 1 - SHARE_FLOOR * len(rows)
        for row in rows:
            if behind:
                extra = spare * behind.get(row['task'], 0) / sum(behind.values())
            elif unknown:
                extra = spare / len(unknown) if row['task'] in unknown else 0
            else:
                extra = spare / len(rows)
            row['share'] = round(SHARE_FLOOR + extra, 3)
        return rows

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

    def _auto_no_change(self, task, cycle, step):
        """Write exact-identity evidence when at most one branch changed its root."""
        if step['key'] != 'combined':
            raise PipelineError('--auto-no-change applies only to the combined step')
        roots = {root['id'] for root in cycle['roots']}
        changed = [source for source in step.get('sources', []) if source['id'] not in roots]
        if len(changed) > 1:
            raise PipelineError('Two or more branches improved; build and validate a real combined candidate')
        branches = [item for item in cycle['steps'] if item['phase'] == 'independent']
        reason = ('No independent branch produced a verified improvement over its root, so there is no branch change to combine'
                  if not changed else
                  f'Only branch result {changed[0]["id"]} improved its root; the combination equals that already verified candidate')
        document = {'task': task, 'cycle_id': cycle['cycle_id'], 'step': 'combined', 'parents': step['parents'],
                    'conclusion': 'no_change', 'reason': reason, 'generated_by': 'search.py record --auto-no-change',
                    'measurements': {'roots': [{'id': root['id'], 'cost': root['cost']} for root in cycle['roots']],
                                     'branch_results': {item['key']: [{key: result.get(key) for key in ('id', 'status', 'cost')}
                                                                      for result in item.get('results', [])] for item in branches},
                                     'branch_evidence': {item['key']: item.get('evidence') for item in branches},
                                     'selected_sources': [{'id': source['id'], 'cost': source['cost']} for source in step.get('sources', [])]}}
        path = self.pipeline.storage / 'research/top3-evidence' / f'{cycle["cycle_id"]}-combined-no-change.json'
        write_json(path, document)
        return path

    def record(self, task, cycle_id, step_key, candidates=(), evidence=None, auto_no_change=False):
        self.pipeline.active()
        with self.pipeline.locked():
            state = self._load()
            cycle = state['tasks'].get(task)
            if not cycle or cycle['cycle_id'] != cycle_id:
                raise PipelineError('Search cycle changed or is missing; read the current plan')
            step = next((item for item in cycle['steps'] if item['key'] == step_key), None)
            if step is None or step['status'] != 'pending':
                raise PipelineError('Search step is not pending; finish all independent branches before combining')
            if auto_no_change:
                if evidence is not None or candidates:
                    raise PipelineError('--auto-no-change replaces --evidence and takes no candidates')
                evidence = self._auto_no_change(task, cycle, step)
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

    # ---- relay handoff, startup brief, hypothesis ranking and report skeleton ----

    def handoff(self, task=None, next_action=None, step=None, candidates=(), commands=(), notes=None, run_id=None):
        """Save (with TASK and --next) or show the per-task note the next relay run reads first."""
        with self.pipeline.locked():
            document = read_json(self.handoff_path) if self.handoff_path.exists() else {'schema': 1, 'tasks': {}}
            if task is not None:
                if not next_action:
                    raise PipelineError('A handoff needs --next describing the next concrete action')
                cycle = self._load()['tasks'].get(task, {})
                entry = {'updated_at': self.pipeline.now_string(), 'run_id': run_id, 'cycle_id': cycle.get('cycle_id'),
                         'step': step, 'next_action': next_action, 'candidates': list(dict.fromkeys(candidates)),
                         'commands': list(commands), 'notes': notes}
                previous = document['tasks'].get(task)
                history = (previous or {}).pop('history', []) + ([previous] if previous else [])
                document['tasks'][task] = {**entry, 'history': history[-20:]}
                document['updated_at'] = entry['updated_at']
                write_json(self.handoff_path, document)
            return document

    def rank(self, limit=None):
        """Resume unfinished work first, then order by expected log gain x success / effort."""
        document = read_json(self.hypotheses_path) if self.hypotheses_path.exists() else {}
        resume, scored, unscored = [], [], []
        for index, item in enumerate(document.get('queue', [])):
            status = str(item.get('status', 'pending')).lower()
            if status in CLOSED_HYPOTHESIS:
                continue
            row = {'index': index, 'id': item.get('id'), 'task': item.get('task'), 'status': status,
                   'hypothesis': item.get('hypothesis', item.get('title')),
                   'candidates': item.get('candidate_ids') or item.get('experiment_ids') or [],
                   'remaining_commands': item.get('remaining_commands') or []}
            gain, chance, effort = (item.get(key) for key in ('expected_log_combined_gain_prior', 'p_success', 'effort_hours'))
            if row['candidates'] and ('pending' in status or row['remaining_commands']):
                resume.append(row)
            elif all(isinstance(value, (int, float)) and not isinstance(value, bool) for value in (gain, chance, effort)) and effort > 0:
                row['priority'] = gain * chance / effort
                scored.append(row)
            else:
                row['missing'] = [key for key, value in (('expected_log_combined_gain_prior', gain), ('p_success', chance),
                                                          ('effort_hours', effort)) if value is None]
                unscored.append(row)
        scored.sort(key=lambda row: -row['priority'])
        ordered = resume + scored + unscored
        return {'resume': len(resume), 'scored': len(scored), 'unscored': len(unscored),
                'formula': 'expected_log_combined_gain_prior * p_success / effort_hours',
                'items': ordered[:limit] if limit else ordered}

    def review_period(self, today=None):
        """The previous completed review period: [start, end) of review_period_days days."""
        days = int(self.pipeline.config.get('review_period_days', 2))
        today = today or self.pipeline.now().date()
        current = REVIEW_ANCHOR + timedelta(days=(today - REVIEW_ANCHOR).days // days * days)
        start = current - timedelta(days=days)
        return {'period': start.isoformat(), 'interval': [start.isoformat(), current.isoformat()], 'days': days}

    def _due(self):
        """Which recurring research is due now (Asia/Shanghai day / two-day review period)."""
        now = self.pipeline.now()
        storage = self.pipeline.storage
        public = storage / 'research/public-code/index.json'
        reviews = storage / 'research/reviews/index.json'
        papers = storage / 'research/papers/index.json'
        public_doc = read_json(public) if public.exists() else {}
        review_doc = read_json(reviews) if reviews.exists() else {}
        paper_doc = read_json(papers) if papers.exists() else {}
        last_scan = public_doc.get('last_successful_scan_day')
        period = self.review_period(now.date())
        last_review = review_doc.get('last_completed_period')
        library = paper_doc.get('papers', {})
        return {'quick_public_check': {'due': True, 'cap_minutes': 5},
                'daily_public_scan': {'due': last_scan != now.date().isoformat(), 'last_successful_scan_day': last_scan,
                                      'cap_fraction': 0.15},
                'review': {**period, 'due': not last_review or str(last_review) < period['period'],
                           'last_completed_period': last_review, 'cap_fraction': 0.25,
                           'includes': ['retrospective', 'paper_reading', 'optimization_suggestions']},
                'papers': {'in_library': len(library),
                           'read': sum(item.get('status') == 'read' for item in library.values() if isinstance(item, dict)),
                           'queued': len(paper_doc.get('queue', []))}}

    def _agent_validations(self):
        path = self.pipeline.storage / 'console/state.json'
        if not path.exists():
            return []
        cutoff = (self.pipeline.now() - timedelta(days=2)).isoformat()
        jobs = read_json(path).get('jobs', {}).values()
        return [{key: job.get(key) for key in ('job_id', 'candidate_id', 'task', 'robustness', 'state', 'blocked_reason',
                                               'created_at', 'finished_at', 'stop_reason', 'trigger_run_id')}
                for job in jobs if job.get('kind') == 'local_validate' and job.get('origin') == 'agent'
                and (job.get('state') in {'queued', 'blocked', 'starting', 'running', 'unknown'} or (job.get('finished_at') or '') >= cutoff)]

    def _cycles(self):
        state = self._load()
        rows = {}
        for task in TASKS:
            cycle = state['tasks'].get(task)
            if not cycle:
                rows[task] = None
                continue
            rows[task] = {'cycle_id': cycle['cycle_id'], 'status': cycle['status'], 'shortfall': cycle.get('shortfall'),
                          'roots': [{'id': root['id'], 'cost': root['cost']} for root in cycle['roots']],
                          'steps': [{'key': step['key'], 'status': step['status'], 'parents': step['parents'],
                                     'results': [{key: result.get(key) for key in ('id', 'status', 'cost')}
                                                 for result in step.get('results', []) or []],
                                     'evidence': (step.get('evidence') or {}).get('conclusion')}
                                    for step in cycle['steps']]}
        return rows

    def _best_costs(self):
        costs = {}
        for task in TASKS:
            cid = self.pipeline.state.get('best', {}).get(task)
            try:
                costs[task] = {'id': cid, 'cost': positive(self.pipeline.verified(cid)[2]['score'])} if cid else None
            except (PipelineError, OSError, ValueError, KeyError):
                costs[task] = {'id': cid, 'cost': None}
        return costs

    def brief(self):
        """One read-only startup view for a relay run (run `plan` first to advance cycles)."""
        with self.pipeline.locked():
            best = self._best_costs()
            allocation = self._allocation()
            submissions = self.pipeline.state.get('submissions', {})
            submitted = self.pipeline.state.get('last_submitted_costs', {})
        handoff = read_json(self.handoff_path).get('tasks', {}) if self.handoff_path.exists() else {}
        ranking = self.rank(limit=8)
        latest = max(submissions.values(), key=lambda item: item.get('created_at', ''), default=None)
        return {'now': self.pipeline.now_string(), 'best': best,
                'local_improvement_vs_last_submitted': self._improvement(best, submitted),
                'cycles': self._cycles(), 'allocation': allocation,
                'handoff': {task: {key: value for key, value in entry.items() if key != 'history'} for task, entry in handoff.items()},
                'agent_validations': self._agent_validations(), 'hypotheses': ranking, 'due': self._due(),
                'latest_submission': {key: (latest or {}).get(key) for key in ('token', 'status', 'submission_id', 'created_at', 'public_score')} if latest else None,
                'reminders': self._reminders()}

    @staticmethod
    def _improvement(best, submitted):
        if not all(best.get(task) and best[task].get('cost') and submitted.get(task) for task in TASKS):
            return None
        return math.prod(submitted[task] / best[task]['cost'] for task in TASKS) ** (1 / 3)

    def _reminders(self):
        now = self.pipeline.now()
        rows = []
        for label, stamp in [('milestone', item) for item in MILESTONES] + [('final_deadline', self.pipeline.config['deadline'])]:
            moment = datetime.fromisoformat(stamp)
            if moment > now:
                rows.append({'kind': label, 'at': stamp, 'days_left': round((moment - now).total_seconds() / 86400, 1)})
        return rows

    def report(self):
        """Chinese report skeleton with the measured ledger state; the run adds analysis."""
        brief = self.brief()
        lines = [f'# VQCC 优化运行报告（{brief["now"]}）', '', '## 当前最佳（官方完整验证）', '',
                 '| 任务 | 候选 | 官方成本 |', '|---|---|---|']
        for task in TASKS:
            item = brief['best'][task] or {}
            lines.append(f'| {task} | {item.get("id") or "—"} | {item.get("cost") if item.get("cost") is not None else "未知"} |')
        ratio = brief['local_improvement_vs_last_submitted']
        lines += ['', f'相对上次提交组合的本地几何改进：{f"{ratio:.6f}x" if ratio else "未知（缺少已提交成本或当前成本）"}',
                  '（本地比值，不是平台分数。）', '', '## Top-3 周期进度', '']
        for task, cycle in brief['cycles'].items():
            if not cycle:
                lines.append(f'- **{task}**：尚无周期')
                continue
            roots = '，'.join(f'{root["id"]}（{root["cost"]}）' for root in cycle['roots']) or '无'
            lines.append(f'- **{task}** `{cycle["cycle_id"]}`（{cycle["status"]}；缺额 {cycle.get("shortfall", 0)}）根：{roots}')
            for step in cycle['steps']:
                results = '；'.join(f'{r["id"]} {r["status"]} {r["cost"] if r["cost"] is not None else ""}'.strip()
                                   for r in step['results']) or ('证据：' + step['evidence'] if step['evidence'] else '—')
                lines.append(f'  - {step["key"]}：{step["status"]}，父 {", ".join(step["parents"]) or "—"}；结果 {results}')
        lines += ['', '## 资源分配建议（公开前沿差距）', '']
        for row in brief['allocation']:
            headroom = row['log_score_headroom']
            lines.append(f'- {row["task"]}：{row["status"]}，share {row["share"]}，'
                         f'headroom {f"{headroom:.4f}" if headroom is not None else "未知"}')
        lines += ['', '## 代理排队的官方验证', '']
        lines += [f'- {job["candidate_id"]}：{job["state"]}{"（" + job["blocked_reason"] + "）" if job.get("blocked_reason") else ""}'
                  for job in brief['agent_validations']] or ['- 无']
        lines += ['', '## 研究到期情况', '']
        due = brief['due']
        lines += [f'- 每日公开代码扫描：{"到期" if due["daily_public_scan"]["due"] else "已完成"}（上次 {due["daily_public_scan"]["last_successful_scan_day"]}）',
                  f'- 两日复盘 {due["review"]["interval"][0]}–{due["review"]["interval"][1]}（含论文阅读与优化建议）：'
                  f'{"到期" if due["review"]["due"] else "已完成"}',
                  f'- 论文库：{due["papers"]["in_library"]} 篇，已读 {due["papers"]["read"]}，待读 {due["papers"]["queued"]}']
        latest = brief['latest_submission']
        lines += ['', '## 优化思路建议（来自复盘与论文；运行填写，注明依据与最便宜的筛查）', '']
        lines += ['', '## 提交状态', '', f'- 最近提交：{json.dumps(latest, ensure_ascii=False) if latest else "无记录"}（平台分数仅以平台返回为准）',
                  '', '## 里程碑与最终选择提醒', '']
        lines += [f'- {row["kind"]}：{row["at"]}（剩余 {row["days_left"]} 天）' for row in brief['reminders']]
        lines += ['- 最终提交选择需用户审阅后执行。', '', '## 本次实验与每个可行候选的去向（运行填写）', '',
                  '<!-- 每个可行候选：已完成官方结果 / 复用匹配证据 / 待办及下一条命令 -->', '',
                  '## 下一步假设（运行填写）', '']
        for task, entry in brief['handoff'].items():
            lines.append(f'- {task}：{entry.get("next_action")}')
        return '\n'.join(lines) + '\n'


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
    record.add_argument('--auto-no-change', action='store_true',
                        help='combined only: write exact-identity evidence when at most one branch improved its root')
    commands.add_parser('brief', help='Read-only startup view: cycles, handoff, queued validations, ranked hypotheses, due research')
    commands.add_parser('report', help='Print the Chinese run-report skeleton from the ledgers')
    rank = commands.add_parser('rank', help='Order open hypotheses: resumable work first, then gain x chance / effort')
    rank.add_argument('--limit', type=int)
    handoff = commands.add_parser('handoff', help='Show, or with TASK --next save, the next-run handoff')
    handoff.add_argument('task', nargs='?', choices=TASKS)
    handoff.add_argument('--next', dest='next_action')
    handoff.add_argument('--step', choices=['top1', 'top2', 'top3', 'combined'])
    handoff.add_argument('--candidate', action='append', default=[])
    handoff.add_argument('--command', action='append', default=[], dest='commands')
    handoff.add_argument('--notes')
    handoff.add_argument('--run-id')
    frontier = commands.add_parser('frontier', help='Record a public per-task cost, or show the headroom allocation')
    frontier.add_argument('task', nargs='?', choices=TASKS)
    frontier.add_argument('--cost', type=float)
    frontier.add_argument('--source', help='Notebook/dataset ref and version')
    frontier.add_argument('--basis', choices=['local_official', 'claimed'])
    args = parser.parse_args()
    search = Search(Pipeline(args.config))
    if args.command == 'frontier' and (args.task is None) != (args.cost is None):
        parser.error('frontier takes both TASK and --cost, or neither')
    if args.command == 'report':
        print(search.report(), end='')
        return
    result = (search.plan(args.task) if args.command == 'plan' else
              search.frontier(args.task, args.cost, args.source, args.basis) if args.command == 'frontier' else
              search.brief() if args.command == 'brief' else
              search.rank(args.limit) if args.command == 'rank' else
              search.handoff(args.task, args.next_action, args.step, args.candidate, args.commands, args.notes, args.run_id)
              if args.command == 'handoff' else
              search.record(args.task, args.cycle, args.step, args.candidate, args.evidence, args.auto_no_change))
    print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == '__main__':
    try:
        main()
    except (PipelineError, OSError, ValueError, KeyError) as error:
        print(json.dumps({'status': 'error', 'error': str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
