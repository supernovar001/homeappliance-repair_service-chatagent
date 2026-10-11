"""
세탁기 A/S RAG 챗봇 성능 평가 (체크포인트 및 중단 후 재개 지원)

평가 항목
- Scope Accuracy: 전체 500문항
- Hit@5 / MRR@5: 정답 페이지가 지정된 340문항
- RAGAS: 최대 340문항 (Faithfulness, Answer Relevancy)
  * 답변 및 Context가 정상 생성된 문항만 평가
  * 기본 50문항, --ragas-limit 0 지정 시 전체 후보 평가

평가 데이터셋
- eval/washer_500_synthetic.json (500문항)

실행 방법
- 기본 평가 (RAGAS 50문항):
  python -u run_production_500_resume.py --dataset eval/washer_500_synthetic.json

- 전체 평가 (RAGAS 최대 340문항):
  python -u run_production_500_resume.py --dataset eval/washer_500_synthetic.json --ragas-limit 0

체크포인트
- 질문별 평가 결과 및 RAGAS 평가 결과를 JSONL로 저장
- 중단 시 동일 명령어로 재실행하면 저장된 결과부터 이어서 평가
- 평가 결과는 results/ 디렉터리에 CSV로 저장
"""
import argparse
import csv
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path


def write_json_atomic(path, value):
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    os.replace(tmp, path)


def append_jsonl(path, value):
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False) + '\n')
        f.flush()
        os.fsync(f.fileno())


def load_jsonl(path):
    found = {}
    if path.exists():
        with path.open(encoding='utf-8') as f:
            for line in f:
                try:
                    record = json.loads(line)
                    found[record['id']] = record
                except (ValueError, KeyError):
                    continue  # Ignore a truncated final line after abrupt shutdown.
    return found


def mean(values):
    nums = []
    for value in values:
        try:
            n = float(value)
            if math.isfinite(n):
                nums.append(n)
        except (TypeError, ValueError):
            pass
    return (sum(nums) / len(nums), len(nums)) if nums else (float('nan'), 0)


def save_csv(path, rows):
    if not rows:
        return
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    os.replace(tmp, path)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', default='eval/washer_500_synthetic.json')
    p.add_argument('--mode', default='child_rerank_code')
    p.add_argument('--ragas-limit', type=int, default=50, help='0=all eligible, -1=skip')
    p.add_argument('--ragas-batch-size', type=int, default=10)
    p.add_argument('--output', default='results/washer_500_improved_resume.csv')
    p.add_argument('--judge-model', default='gpt-4o-mini')
    p.add_argument('--embedding-model', default='text-embedding-3-small')
    a = p.parse_args()
    if a.ragas_limit < -1 or a.ragas_batch_size < 1:
        p.error('ragas-limit must be >= -1 and ragas-batch-size >= 1')

    items = json.loads(Path(a.dataset).read_text(encoding='utf-8'))
    if len(items) != 500 or len({x['id'] for x in items}) != 500:
        raise ValueError('Dataset must have 500 unique IDs')
    labeled = [x for x in items if x.get('reference_pages')]
    ragas_pool = [] if a.ragas_limit == -1 else labeled[:a.ragas_limit] if a.ragas_limit else labeled
    ragas_ids = {x['id'] for x in ragas_pool}
    output = Path(a.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    checkpoint = output.with_suffix('.jsonl')
    ragas_checkpoint = output.with_name(output.stem + '_ragas.jsonl')
    score_csv = output.with_name(output.stem + '_ragas.csv')
    meta = output.with_suffix('.meta.json')
    signature = {
        'dataset_sha256': hashlib.sha256(Path(a.dataset).read_bytes()).hexdigest(), 'mode': a.mode,
        'ragas_limit': a.ragas_limit, 'judge_model': a.judge_model, 'embedding_model': a.embedding_model,
        'top_k': 5, 'checkpoint_version': 1,
    }
    if meta.exists():
        if json.loads(meta.read_text(encoding='utf-8')) != signature:
            raise RuntimeError(f'Existing checkpoints use different settings. Choose another --output or remove checkpoints: {meta}')
    else:
        if checkpoint.exists() or ragas_checkpoint.exists():
            raise RuntimeError('Checkpoint exists without matching metadata; choose another --output')
        write_json_atomic(meta, signature)

    import app
    retriever = app.build_retriever(a.mode)
    k = getattr(retriever, 'top_n', getattr(retriever, 'k', None))
    if k != 5:
        raise ValueError(f'MRR@5 requires exactly 5 returned documents; got {k}')
    saved = load_jsonl(checkpoint)
    ragas_saved = load_jsonl(ragas_checkpoint)
    # A completed RAGAS-eligible question MUST have a durable sample (or explicitly marked missing).
    for item in items:
        if item['id'] in saved and item['id'] in ragas_ids and item['id'] not in ragas_saved:
            del saved[item['id']]
    print(f'[RESUME] loaded {len(saved)}/500 question results, {len(ragas_saved)} RAGAS results', flush=True)
    print(f'[SETUP] labeled={len(labeled)}, ragas_target={len(ragas_ids)}, mode={a.mode}', flush=True)

    for i, item in enumerate(items, 1):
        qid = item['id']
        if qid in saved:
            continue
        t = time.perf_counter()
        gold = {int(x) for x in item.get('reference_pages') or []}
        row = {'id': qid, 'source_id': item.get('source_id', ''), 'variant': item.get('variant', ''),
               'question': item['question'], 'gold_pages': json.dumps(sorted(gold)), 'retrieved_pages': '',
               'first_rank': '', 'rr': '', 'hit': '', 'expected_scope': item.get('expected_scope', ''),
               'predicted_scope': '', 'scope_correct': '', 'expected_routes': json.dumps(item.get('acceptable_routes') or [], ensure_ascii=False),
               'predicted_route': '', 'route_correct': '', 'answer': '', 'citation_valid': '', 'latency_sec': '', 'error': ''}
        sample = None
        try:
            if qid in ragas_ids:
                state = app.consult_flow.invoke({'question': item['question'], 'history': []})
                result = state['result']
                row['predicted_scope'] = result.get('scope', '')
                docs = state.get('documents', [])
                row['answer'] = result.get('answer', '')
                row['predicted_route'] = result.get('route', '')
                if item.get('acceptable_routes'):
                    row['route_correct'] = int(row['predicted_route'] in item['acceptable_routes'])
                used_pages = {int(v) for v in result.get('retrieved_pages') or []}
                cited = {int(v) for v in re.findall(r'\[PDF\s*(\d+)쪽\]', row['answer'])}
                row['citation_valid'] = int(bool(cited) and cited.issubset(used_pages)) if used_pages else ''
                contexts = [d['text'] for d in result.get('contexts', []) if d.get('text')]
                if row['answer'] and contexts:
                    sample = {'id': qid, 'question': item['question'], 'answer': row['answer'], 'contexts': contexts}
            else:
                scope = app.check_scope(item['question'])
                row['predicted_scope'] = scope.product
                docs = retriever.invoke(item['question']) if gold else []
            if item.get('expected_scope'):
                row['scope_correct'] = int(row['predicted_scope'] == item['expected_scope'])
            if gold:
                pages = [int(d.metadata['page']) if hasattr(d, 'metadata') else int(d['page']) for d in docs[:5]]
                rank = next((position for position, page in enumerate(pages, 1) if page in gold), None)
                row.update(retrieved_pages=json.dumps(pages), first_rank=rank or '', rr=1/rank if rank else 0., hit=int(rank is not None))
        except Exception as exc:
            row['error'] = f'{type(exc).__name__}: {exc}'
        row['latency_sec'] = round(time.perf_counter() - t, 2)
        if qid in ragas_ids:
            # Record a missing sample too, so it can be skipped safely after restart.
            append_jsonl(ragas_checkpoint, sample or {'id': qid, 'missing': True})
            ragas_saved[qid] = sample or {'id': qid, 'missing': True}
        append_jsonl(checkpoint, row)
        saved[qid] = row
        print(f'[QUESTION] {i}/500 id={qid} seconds={row["latency_sec"]} error={bool(row["error"])}', flush=True)
        if i % 25 == 0:
            save_csv(output, [saved[x['id']] for x in items if x['id'] in saved])
            print(f'[CHECKPOINT] {len(saved)}/500 saved to {checkpoint}', flush=True)

    rows = [saved[item['id']] for item in items if item['id'] in saved]
    save_csv(output, rows)
    retrieval = [r for r in rows if r['rr'] != '' and not r['error']]
    scopes = [r for r in rows if r['scope_correct'] != '' and not r['error']]
    routes = [r for r in rows if r['route_correct'] != '' and not r['error']]
    cites = [r for r in rows if r['citation_valid'] != '' and not r['error']]
    print('\n=== SEARCH & CLASSIFICATION ===', flush=True)
    print(f'MRR@5: {mean([r["rr"] for r in retrieval])[0]:.4f} (valid={len(retrieval)}/{len(labeled)})')
    print(f'Hit@5: {sum(int(r["hit"]) for r in retrieval)}/{len(retrieval)}')
    print(f'Scope accuracy: {sum(int(r["scope_correct"]) for r in scopes)}/{len(scopes)}')
    print(f'Route accuracy (generated subset): {sum(int(r["route_correct"]) for r in routes)}/{len(routes)}')
    print(f'Citation validity (generated subset): {sum(int(r["citation_valid"]) for r in cites)}/{len(cites)}')
    print(f'Errors: {sum(bool(r["error"]) for r in rows)} | CSV: {output}', flush=True)
    if a.ragas_limit == -1:
        return

    samples = [ragas_saved[x['id']] for x in ragas_pool if x['id'] in ragas_saved and not ragas_saved[x['id']].get('missing')]
    if not samples:
        print('[RAGAS] No valid answer/context samples to evaluate', flush=True)
        return
    existing_scores = load_jsonl(score_csv.with_suffix('.jsonl'))
    def valid_score(record):
        return record is not None and all(isinstance(record.get(k), (int, float)) and math.isfinite(float(record[k])) for k in ('faithfulness', 'answer_relevancy'))

    pending = [s for s in samples if not valid_score(existing_scores.get(s['id']))]
    print(f'[RAGAS] valid_cached={sum(valid_score(existing_scores.get(s["id"])) for s in samples)}, pending={len(pending)}, batch_size={a.ragas_batch_size}', flush=True)
    if pending:
        from datasets import Dataset
        from langchain_openai import ChatOpenAI, OpenAIEmbeddings
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy
        judge = ChatOpenAI(model=a.judge_model, temperature=0)
        embedding = OpenAIEmbeddings(model=a.embedding_model)
        for j in range(0, len(pending), a.ragas_batch_size):
            batch = pending[j:j + a.ragas_batch_size]
            ds = Dataset.from_list([{k: x[k] for k in ('question', 'answer', 'contexts')} for x in batch])
            try:
                result = evaluate(ds, metrics=[faithfulness, answer_relevancy], llm=judge,
                                  embeddings=embedding, raise_exceptions=True, show_progress=True)
                frame = result.to_pandas()
                for sample, (_, data) in zip(batch, frame.iterrows()):
                    record = {'id': sample['id'], 'faithfulness': float(data.get('faithfulness', float('nan'))),
                              'answer_relevancy': float(data.get('answer_relevancy', float('nan')))}
                    append_jsonl(score_csv.with_suffix('.jsonl'), record)
                    existing_scores[record['id']] = record
            except Exception as exc:
                import traceback
                traceback.print_exc()
                print(f'[RAGAS ERROR] batch={j // a.ragas_batch_size + 1}: {type(exc).__name__}: {exc}', flush=True)
                raise  # Keep previous scores; rerun to retry this batch.
            scores = [existing_scores[x['id']] for x in samples if valid_score(existing_scores.get(x['id']))]
            save_csv(score_csv, scores)
            print(f'[RAGAS CHECKPOINT] {len(scores)}/{len(samples)} completed', flush=True)
    scores = [existing_scores[x['id']] for x in samples if valid_score(existing_scores.get(x['id']))]
    print('\n=== RAGAS METRICS ===')
    for key in ('faithfulness', 'answer_relevancy'):
        avg, n = mean([x.get(key) for x in scores])
        print(f'{key}: {avg:.4f} (valid={n}/{len(samples)})')
    print(f'Saved: {score_csv}', flush=True)


if __name__ == '__main__':
    main()
